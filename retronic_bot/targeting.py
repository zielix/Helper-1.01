"""Decyzje targetingu: kolejność celów, śledzenie HP i progi czasowe.

Funkcje są czyste: dostają wiersze Battle i stwory z mapy gry (słowniki
z battle.py i creatures.py) i nic nie klikają, więc dają się testować bez
klienta. Stan (cel, zegary) trzyma okno bota.

Wiersz Battle: {"key", "name", "hp", "y", "allowed", "attacked", ...}.
Stwór z mapy: {"dx", "dy", "hp", "steps" (None = nieosiągalny), "player_like", ...}.
"""

# Ten sam pasek HP na liście Battle i nad stworem może różnić się o kilka %.
HP_MATCH_TOLERANCE = 3
# Gdy liczba kroków nie jest znana, cel trafia na koniec kolejki.
UNKNOWN_STEPS = 99
# Atakowany cel, do którego nie ma drogi, zmieniamy po tym czasie (s).
UNREACHABLE_RETARGET_AFTER = 1.5
# Cel, który nie traci HP przez tyle sekund, zmieniamy na inny.
STALL_RETARGET_AFTER = 7.0
# Atakowanego potwora bot nie porzuca dla ważniejszego z listy; priorytet
# decyduje tylko o wyborze następnego celu.
# Gdy nie widać mapy gry: cel, który przy ostatnim odczycie miał najwyżej tyle
# % HP, a potem zniknęła jego ramka, uznajemy za zabitego.
DEATH_HP = 60
# Od tylu sekund bez obrażeń status pokazuje ostrzeżenie.
STALL_NOTICE_AFTER = 2.0
# Zablokowany typ potwora jest pomijany przez tyle sekund.
UNREACHABLE_SKIP_FOR = 20.0
# Po tylu kliknięciach bez czerwonej ramki bot robi przerwę.
MAX_ENGAGE_ATTEMPTS = 4
ENGAGE_REST = 6.0
# Najkrótszy odstęp między zmianami celu (s).
RETARGET_MIN_INTERVAL = 3.0
# Wzrost HP celu powyżej tej wartości oznacza, że to inny stwór (regeneracja jest wolna).
HP_REGEN_TOLERANCE = 5


def normalize_name(name):
    """Key used to compare monster names: single spaces, case-insensitive."""
    return " ".join(name.split()).casefold() if name else None


def engage_wait(attempt):
    """Seconds to wait for the target marker after click number `attempt` (2, 3, 4.5, 6.75…)."""
    return 2.0 * 1.5 ** (attempt - 1)


def chebyshev(dx, dy):
    return max(abs(dx), abs(dy))


def creature_at(creatures, offset):
    """Creature nearest to the tile offset (dx, dy), or None when there are none."""
    return min(
        creatures,
        key=lambda creature: chebyshev(creature["dx"] - offset[0], creature["dy"] - offset[1]),
        default=None,
    )


def matching_creatures(creatures, hp):
    """Creatures whose health bar matches a Battle row with `hp` percent."""
    if hp is None:
        return []
    return [creature for creature in creatures if abs(creature["hp"] - hp) <= HP_MATCH_TOLERANCE]


def screen_click_possible(rows, creatures, suppressed):
    """True when every creature on the map is surely an allowed monster.

    Klik na mapie gry jest bezpieczny tylko wtedy, gdy każdy wpis Battle to
    dozwolony potwór jednego rodzaju, a liczba stworów na mapie zgadza się
    z Battle — wtedy żaden ze stworów na mapie nie jest graczem ani NPC.
    """
    names = {row["key"] for row in rows if row["allowed"]}
    return (
        creatures is not None
        and all(row["allowed"] for row in rows)
        and len(names) == 1
        and not names.intersection(suppressed)
        and len(creatures) == len(rows)
        and not any(creature["player_like"] for creature in creatures)
    )


def rank_candidates(rows, creatures, reach_known, priority, suppressed=(),
                    allow_screen=True, attacked_row=None, attacked_offset=None):
    """Return (allowed targets best first, number skipped as unreachable).

    priority(key) zwraca pozycję potwora na liście (mniej = ważniejszy).
    Gdy klik na mapie jest bezpieczny, kandydaci to stwory z mapy
    (najbliższy, potem najmniej HP). W innym wypadku to wiersze Battle
    w kolejności: priorytet z listy, najbliższy osiągalny, najmniej HP,
    wyżej w Battle; mapa służy do sprawdzenia osiągalności (dopasowanie po % HP).
    """
    suppressed = set(suppressed)
    allowed_rows = [row for row in rows if row["allowed"] and row is not attacked_row
                    and not row.get("attacked") and row["key"] not in suppressed]
    if not allowed_rows:
        return [], 0
    if allow_screen and screen_click_possible(rows, creatures, suppressed):
        first = next(row for row in rows if row["allowed"])
        pool = [creature for creature in creatures
                if attacked_offset is None
                or chebyshev(creature["dx"] - attacked_offset[0], creature["dy"] - attacked_offset[1]) > 0]
        reachable = [creature for creature in pool if creature["steps"] is not None]
        reachable.sort(key=lambda creature: (creature["steps"], creature["hp"]))
        return [
            {"key": first["key"], "name": first["name"], "via": "screen", "creature": creature,
             "steps": creature["steps"], "row": None, "hp": creature["hp"]}
            for creature in reachable
        ], len(pool) - len(reachable)

    candidates = []
    skipped = 0
    all_unreachable = bool(reach_known and creatures and all(c["steps"] is None for c in creatures))
    for row in allowed_rows:
        steps = None
        if creatures:
            same = matching_creatures(creatures, row["hp"])
            if same:
                reachable_matches = [creature for creature in same if creature["steps"] is not None]
                if reach_known and not reachable_matches:
                    skipped += 1
                    continue
                if len(same) == 1:
                    steps = same[0]["steps"]
                elif reachable_matches:
                    # HP nie rozróżnia identycznych pasków; przypisz wiersz
                    # do najbliższego osiągalnego stwora zamiast losować cel.
                    steps = min(creature["steps"] for creature in reachable_matches)
        if all_unreachable:
            skipped += 1
            continue
        candidates.append({"key": row["key"], "name": row["name"], "via": "battle", "creature": None,
                           "steps": steps, "row": row, "hp": row["hp"]})
    candidates.sort(key=lambda item: (
        priority(item["key"]),
        item["steps"] if item["steps"] is not None else UNKNOWN_STEPS,
        item["hp"],
        item["row"]["y"],
    ))
    return candidates, skipped


def track_health(tracked, row_y, hp, now, row_tolerance):
    """Update the target-health record; return (record, seconds without damage).

    Rekord zaczyna się od nowa, gdy cel jest nowy (inny wiersz Battle),
    traci HP albo zyskał wyraźnie więcej, niż daje regeneracja.
    """
    if (tracked is None or hp is None or abs(row_y - tracked["y"]) > row_tolerance
            or hp < tracked["hp"] or hp > tracked["hp"] + HP_REGEN_TOLERANCE):
        return {"y": row_y, "hp": hp, "since": now}, 0.0
    return tracked, now - tracked["since"]


def unreachable_since(screen, offset, since, now):
    """Start time of the attacked creature being unreachable, or None when it is reachable.

    `offset` to pole czerwonego kwadratu (atakowany stwór) względem postaci.
    """
    if offset is None or not screen or not screen["reach_known"]:
        return None
    target = creature_at(screen["creatures"], offset)
    if target is None or target["steps"] is not None:
        return None
    return since if since is not None else now


def retarget_reason(blocked_since, stalled, now):
    """Why the current target should be dropped, or None to keep attacking."""
    if blocked_since is not None and now - blocked_since >= UNREACHABLE_RETARGET_AFTER:
        return "nieosiągalny (droga zablokowana)"
    if stalled >= STALL_RETARGET_AFTER:
        return f"nie traci HP od {stalled:.0f} s"
    return None


def target_died(last_hp, still_listed, still_on_tile):
    """Decide whether the target whose attack marker disappeared was killed.

    still_on_tile: czy na ostatnim polu celu stoi stwór (None — nie wiadomo).
    Ramka celu znika prawie zawsze dlatego, że potwór zginął, więc gdy mapa
    gry pokazuje puste pole celu, to wystarczy — nawet przy 100% HP w ostatnim
    odczycie (słabe potwory giną między odczytami Battle). still_listed=False
    (w Battle ubyło potworów o tej nazwie) rozstrzyga zawsze: na pole celu
    często od razu wchodzi następny potwór. Bez mapy: mało HP.
    """
    if not still_listed:
        return True
    if still_on_tile is not None:
        return not still_on_tile
    return last_hp is not None and last_hp <= DEATH_HP


def attack_status(name, hp, stalled):
    """Status line while attacking (without the final period)."""
    text = f"Atakuję „{name}”" + (f" · HP {hp}%" if hp is not None else "")
    if stalled >= STALL_NOTICE_AFTER:
        text += f" · bez obrażeń od {stalled:.0f} s"
    return text


def corpse_offset_from_screen(screen, attacked_hp):
    """Tile offset of the attacked creature (where its corpse will lie), or None."""
    if not screen:
        return None
    offset = screen.get("square")
    if offset is not None:
        return tuple(offset)
    same = matching_creatures(screen["creatures"], attacked_hp)
    if len(same) == 1:
        return same[0]["dx"], same[0]["dy"]
    return None
