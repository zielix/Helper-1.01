"""Chodzenie po waypointach przez klikanie w minimapę klienta.

Klient OTClient po lewym kliknięciu w minimapę sam prowadzi postać do
klikniętego pola (autowalk). Bot wyznacza więc tylko trasę po polach z pliku
.otmm i klika najdalsze pole tej trasy, które jest widoczne na minimapie.
Pozycja postaci pochodzi z dopasowania minimapy, bez czytania pamięci.
"""

import heapq
import json
import random
from pathlib import Path

from . import human
from .minimap import FLAG_NOT_PATHABLE, FLAG_NOT_WALKABLE, FLAG_SEEN


WAYPOINT_TYPES = {"walk": "Idź", "stand": "Stój", "ladder": "Drabina", "rope": "Lina"}
# Waypointy z akcją: bot staje dokładnie na polu i używa drabiny albo liny,
# a po zmianie piętra przechodzi do następnego waypointu na nowym piętrze.
ACTION_TYPES = {"ladder", "rope"}
EXACT_TYPES = {"stand"} | ACTION_TYPES
CAVEBOT_PROFILE_PATH = Path(__file__).resolve().parent.parent / "cavebot.json"
PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
# Te pola tworzą nazwany profil (trasa + potwory); tryb Human jest globalny.
PROFILE_KEYS = ("waypoints", "monsters", "ignored", "monster_modes", "pause_on_battle", "waypoint_type", "inspect_corpses", "learn_loot", "use_meat", "loot_items", "loot_immediately")


def load_profile(path=CAVEBOT_PROFILE_PATH):
    """Read waypoints, attacked monsters and options saved by the Cavebot tab."""
    profile = {
        "waypoints": [], "monsters": [], "pause_on_battle": True, "waypoint_type": "walk",
        "inspect_corpses": False, "learn_loot": False, "use_meat": True, "loot_items": False,
        "loot_immediately": True,
        "human": True, "ignored": [], "profile": "", "monster_modes": {},
        "player_center": None, "rope_slot": None, "loot_slot": None,
    }
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return profile
    if not isinstance(saved, dict):
        return profile
    for item in saved.get("waypoints", []):
        try:
            waypoint = {
                "x": int(item["x"]), "y": int(item["y"]), "z": int(item["z"]),
                "type": item.get("type", "walk") if item.get("type") in WAYPOINT_TYPES else "walk",
            }
        except (KeyError, TypeError, ValueError):
            continue
        profile["waypoints"].append(waypoint)
    profile["monsters"] = [str(name) for name in saved.get("monsters", []) if str(name).strip()]
    profile["pause_on_battle"] = bool(saved.get("pause_on_battle", True))
    profile["inspect_corpses"] = bool(saved.get("inspect_corpses", False))
    profile["learn_loot"] = bool(saved.get("learn_loot", False))
    profile["use_meat"] = bool(saved.get("use_meat", True))
    profile["loot_items"] = bool(saved.get("loot_items", False))
    profile["loot_immediately"] = bool(saved.get("loot_immediately", True))
    profile["human"] = bool(saved.get("human", True))
    profile["ignored"] = [str(name).casefold() for name in saved.get("ignored", []) if str(name).strip()]
    profile["profile"] = str(saved.get("profile", ""))
    modes = saved.get("monster_modes", {})
    if isinstance(modes, dict):
        profile["monster_modes"] = {
            str(name).casefold(): mode for name, mode in modes.items() if mode in ("chase", "stand")
        }
    for key in ("player_center", "rope_slot", "loot_slot"):
        point = saved.get(key)
        if isinstance(point, list) and len(point) == 2 and all(isinstance(v, int) for v in point):
            profile[key] = point
    if saved.get("waypoint_type") in WAYPOINT_TYPES:
        profile["waypoint_type"] = saved["waypoint_type"]
    return profile


def save_profile(profile, path=CAVEBOT_PROFILE_PATH):
    Path(path).write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _profile_path(name):
    safe = "".join(char for char in name.strip() if char not in '\\/:*?"<>|').strip()
    if not safe:
        raise ValueError("Nazwa profilu nie może być pusta.")
    return PROFILES_DIR / f"{safe}.json", safe


def list_profiles():
    if not PROFILES_DIR.is_dir():
        return []
    return sorted((path.stem for path in PROFILES_DIR.glob("*.json")), key=str.casefold)


def save_named_profile(name, profile):
    path, safe = _profile_path(name)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    save_profile({key: profile[key] for key in PROFILE_KEYS}, path)
    return safe


def load_named_profile(name):
    path, _safe = _profile_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"Nie ma profilu „{name}”.")
    loaded = load_profile(path)
    return {key: loaded[key] for key in PROFILE_KEYS}


def delete_named_profile(name):
    path, _safe = _profile_path(name)
    path.unlink(missing_ok=True)


def waypoint_text(index, waypoint):
    kind = WAYPOINT_TYPES.get(waypoint["type"], waypoint["type"])
    return f"{index + 1:>3}.  {kind}   {waypoint['x']}, {waypoint['y']}, {waypoint['z']}"


def find_path(otmm_map, start, goal, max_nodes=40000):
    """Return the list of (x, y) tiles from start to goal on one floor, or None.

    Pola nieodkryte, nieprzechodnie i omijane przez autowalk (np. pola z ogniem)
    są blokadą; pole startu i celu są zawsze dozwolone, bo schody i dziury
    mają flagę „nie do autowalku”, a to na nie chcemy wejść.
    """
    sx, sy, z = start
    gx, gy, gz = goal
    if z != gz or z not in otmm_map.floors:
        return None
    origin_x, origin_y, _colors, flags = otmm_map.floors[z]
    height, width = flags.shape
    blocked = FLAG_NOT_WALKABLE | FLAG_NOT_PATHABLE

    def passable(x, y):
        if (x, y) == (gx, gy):
            return True
        row, col = y - origin_y, x - origin_x
        if not (0 <= row < height and 0 <= col < width):
            return False
        value = int(flags[row, col])
        return bool(value & FLAG_SEEN) and not value & blocked

    def estimate(x, y):
        dx, dy = abs(x - gx), abs(y - gy)
        return max(dx, dy) + 0.4 * min(dx, dy)

    steps = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
             (1, 1, 1.4), (1, -1, 1.4), (-1, 1, 1.4), (-1, -1, 1.4)]
    queue = [(estimate(sx, sy), 0.0, sx, sy)]
    cost = {(sx, sy): 0.0}
    parent = {(sx, sy): None}
    expanded = 0
    while queue:
        _priority, spent, x, y = heapq.heappop(queue)
        if (x, y) == (gx, gy):
            path = []
            node = (x, y)
            while node is not None:
                path.append(node)
                node = parent[node]
            return path[::-1]
        if spent > cost.get((x, y), float("inf")):
            continue
        expanded += 1
        if expanded > max_nodes:
            return None
        for dx, dy, step in steps:
            nx, ny = x + dx, y + dy
            if not passable(nx, ny):
                continue
            new_cost = spent + step
            if new_cost < cost.get((nx, ny), float("inf")):
                cost[(nx, ny)] = new_cost
                parent[(nx, ny)] = (x, y)
                heapq.heappush(queue, (new_cost + estimate(nx, ny), new_cost, nx, ny))
    return None


class CavebotWalker:
    """Decide where to click next so the character follows the waypoint list."""

    def __init__(self, otmm_map, waypoints):
        self.map = otmm_map
        self.waypoints = waypoints
        self.index = 0
        self.pause_until = 0.0
        self.reset_progress()

    def reset_progress(self):
        self.click_target = None
        self.last_click_at = None
        self.click_wait = 0.8
        self.last_position = None
        self.last_move_at = None
        self.best_distance = None
        self.progress_at = None
        self.action_at = None
        self.action_attempts = 0

    def next_waypoint(self):
        self.index = (self.index + 1) % len(self.waypoints)
        self.reset_progress()

    def step(self, position, now, can_click):
        """Return ("click", dx, dy, message) or ("wait", message).

        can_click(dx, dy) mówi, czy pole przesunięte o (dx, dy) od postaci jest
        widoczne na minimapie i nie leży pod przyciskami minimapy.
        """
        if not self.waypoints:
            return "wait", "Brak waypointów; dodaj je kliknięciem w mapę."
        self.index %= len(self.waypoints)
        if now < self.pause_until:
            return "wait", f"Krótka przerwa (tryb Human), {self.pause_until - now:.1f} s."
        rest = human.maybe_break(chance=0.0015)
        if rest:
            self.pause_until = now + rest
            self.reset_progress()
            return "wait", f"Krótka przerwa (tryb Human), {rest:.1f} s."
        x, y, z = position
        if position != self.last_position:
            self.last_position = position
            self.last_move_at = now
        waypoint = self.waypoints[self.index]

        if z != waypoint["z"]:
            # Po wejściu na schody lub zejściu do dziury postać jest już na
            # piętrze kolejnego waypointu; przechodzimy do niego.
            for offset in range(1, min(4, len(self.waypoints))):
                candidate = (self.index + offset) % len(self.waypoints)
                if self.waypoints[candidate]["z"] == z:
                    self.index = candidate
                    self.reset_progress()
                    return "wait", f"Zmiana piętra; dalej waypoint {candidate + 1}."
            return "wait", (
                f"Postać jest na piętrze {z}, a waypoint {self.index + 1} na {waypoint['z']}; "
                "podejdź do trasy."
            )

        distance = max(abs(x - waypoint["x"]), abs(y - waypoint["y"]))
        if distance == 0 and waypoint["type"] in ACTION_TYPES:
            label = WAYPOINT_TYPES[waypoint["type"]]
            if self.action_attempts >= 3:
                skipped = self.index + 1
                self.next_waypoint()
                return "wait", f"{label} na waypoincie {skipped} nie zadziałała 3 razy; pomijam go."
            # 4 s na odczyt nowego piętra z minimapy, zanim akcja zostanie powtórzona.
            if self.action_at is None or now - self.action_at > 4.0:
                self.action_at = now
                self.action_attempts += 1
                return "action", waypoint["type"], f"{label}: używam (próba {self.action_attempts}/3)."
            return "wait", "Czekam na zmianę piętra…"
        if distance <= (0 if waypoint["type"] in EXACT_TYPES else 1) and waypoint["type"] not in ACTION_TYPES:
            reached = self.index + 1
            self.next_waypoint()
            # Człowiek po dojściu na miejsce zwykle chwilę się rozgląda.
            self.pause_until = now + human.reaction("waypoint")
            return "wait", f"Waypoint {reached} osiągnięty."

        if self.best_distance is None or distance < self.best_distance:
            self.best_distance = distance
            self.progress_at = now
        if now - self.progress_at > 20:
            skipped = self.index + 1
            self.next_waypoint()
            return "wait", f"Brak postępu do waypointu {skipped} przez 20 s; pomijam go."

        if self.last_click_at is not None:
            target_left = max(abs(x - self.click_target[0]), abs(y - self.click_target[1]))
            still_walking = now - self.last_move_at < 1.2
            if now - self.last_click_at < self.click_wait or (still_walking and target_left > 1):
                return "wait", f"Idę do waypointu {self.index + 1} (zostało {distance} pól)."

        path = find_path(self.map, position, (waypoint["x"], waypoint["y"], waypoint["z"]))
        if path is None:
            skipped = self.index + 1
            self.next_waypoint()
            return "wait", f"Nie znaleziono drogi do waypointu {skipped}; pomijam go."
        visible = [(tile_x, tile_y) for tile_x, tile_y in reversed(path[1:])
                   if can_click(tile_x - x, tile_y - y)]
        if not visible:
            return "wait", "Następne pole trasy nie jest widoczne na minimapie."
        tile_x, tile_y = visible[0]
        if human.enabled() and len(visible) > 1:
            # Człowiek nie klika zawsze w najdalszy możliwy punkt trasy.
            tile_x, tile_y = random.choice(visible[:max(1, min(8, len(visible) // 3))])
        self.click_target = (tile_x, tile_y)
        self.last_click_at = now
        self.click_wait = 0.8 + human.reaction("walk")
        return "click", tile_x - x, tile_y - y, f"Idę do waypointu {self.index + 1} (zostało {distance} pól)."
