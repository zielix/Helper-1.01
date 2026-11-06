"""Otwieranie ciała, rozpoznawanie przedmiotów i lootowanie.

Bot zamyka okna starych ciał, klika prawym przyciskiem pole ciała, czeka na
nowe okno i rozpoznaje je po tytule („Dead…”, „Slain…”), bo otwarcie okna
przestawia inne okna panelu. Ikony w slotach porównuje z katalogiem
`loot_patterns`, wzorzec „Meat” zjada, wzorce z „Zabieraj” przeciąga (całe
stosy) na slot plecaka zaznaczony przez gracza, a na koniec zamyka okno
ciała. Moduł nie zna GUI: dostaje migawkę stanu i zwraca słownik
z komunikatem, więc może działać w osobnym wątku.
"""

import time

from . import human
from .battle import capture_region
from .battle_window import find_mini_window_frames, panel_columns, read_titles
from .creatures import PLAYER_TILE, find_game_view, locate_creatures, tile_size
from .loot_patterns import (
    find_slot_items,
    identify_items,
    is_meat,
    learn_unknown,
    load_patterns,
    save_debug_image,
)
from .mana import find_tesseract
from .mouse import drag_item, foreground_client_bounds, send_left_click, send_right_click

# Słowa w tytułach okien ciał (OCR, małe litery): „Dead larva”, „Slain rat”, „Remains of…”.
CORPSE_TITLE_WORDS = {"dead", "slain", "remains", "lifeless", "corpse", "body", "split", "burnt"}
# Czekanie na okno ciała: podstawa i dodatek za każde pole, które klient musi przejść.
# Okno sąsiedniego ciała pojawia się po ok. 0,5–1 s; dłuższe czekanie tylko blokuje atak.
OPEN_TIMEOUT = 1.5
WALK_TIME_PER_TILE = 0.6
# Dłużej czekamy tylko, dopóki postać idzie; po tylu sekundach w miejscu przestajemy.
STILL_TIME = 1.2
MAX_OPEN_WAIT = 10.0
POLL_DELAY = 0.2
# Chwila na ułożenie się okien panelu po otwarciu ciała i po zamknięciu starego.
SETTLE_DELAY = 0.15
CLOSE_DELAY = 0.25
# Najwyższe sensowne okno ciała (przy skali 1): ok. 5 rzędów slotów.
MAX_CORPSE_HEIGHT = 5 * 36
# Ciała w kolejce starsze niż tyle sekund są pomijane.
CORPSE_MAX_AGE = 60.0
# Tyle razy próbujemy otworzyć jedno ciało (kolejne próby już po walce, z szukaniem obok).
CORPSE_TRIES = 2
# Najwięcej kliknięć w pola wokół postaci, gdy wyliczone pole ciała nie odpowiada
# (8 sąsiednich i własne, bez już klikniętych).
MAX_SEARCH_CLICKS = 8
# Pole w zasięgu ręki: tyle czekamy przed kliknięciem następnego. Okno pojawia się
# zwykle po 0,6–1,1 s, ale spóźnione okno i tak wyłapiemy przy kolejnym polu
# (porównujemy z obrazem sprzed wszystkich kliknięć), więc nie czekamy do końca.
QUICK_OPEN_WAIT = 0.6
# Po ostatnim kliknięciu czekamy jeszcze tyle na spóźnione okno.
LATE_WINDOW_WAIT = 1.0
# Pola wokół postaci przeszukujemy tylko, gdy wyliczone ciało leży najwyżej tyle pól od niej.
SEARCH_RANGE = 3
# Skala okien klienta z poprzedniego ciała (szukanie we wszystkich skalach trwa kilka razy dłużej).
_last_scale = None
# Czas na przesunięcie przedmiotu przez serwer przed ponownym zrzutem.
MOVE_DELAY = 0.35
# Najwięcej przeciągnięć z jednego ciała (zabezpieczenie przed pętlą).
MAX_LOOT_MOVES = 20
# Tyle razy z rzędu przedmiot może zostać w ciele, zanim uznamy plecak za pełny.
MAX_MOVE_FAILURES = 2
# Jedzenie: prób i przerwa między nimi (serwer ma odstęp między użyciami przedmiotów).
MEAT_ATTEMPTS = 2
MEAT_RETRY_DELAY = 1.0


class CorpseQueue:
    """Corpses waiting to be opened after the fight, in world coordinates.

    Bot nie lootuje w trakcie walki (stałby plecami do żywych potworów):
    każde zabicie dopisuje pole ciała, a gdy w zasięgu nie ma już celów, bot
    otwiera ciała od najbliższego. Ciała starsze niż max_age pomija (rozkładają
    się albo ktoś je już ograbił); dwa ciała na jednym polu to jedno wejście,
    bo i tak otwiera się to na wierzchu.
    """

    def __init__(self, max_age=CORPSE_MAX_AGE):
        self.max_age = max_age
        self.entries = []

    def __len__(self):
        return len(self.entries)

    def add(self, world, now, name=None, tries=0):
        """Queue a corpse; tries — failed attempts so far (a retry searches nearby tiles)."""
        if any(entry["world"] == tuple(world) for entry in self.entries):
            return False
        self.entries.append({"world": tuple(world), "at": now, "name": name, "tries": tries})
        return True

    def prune(self, now):
        self.entries = [entry for entry in self.entries if now - entry["at"] <= self.max_age]

    def pending(self, player, now):
        """Fresh corpses on the player's floor."""
        self.prune(now)
        if player is None:
            return []
        return [entry for entry in self.entries if entry["world"][2] == player[2]]

    def pop_nearest(self, player, now):
        """Remove and return the nearest fresh corpse on the player's floor, or None."""
        candidates = self.pending(player, now)
        if not candidates:
            return None
        entry = min(candidates, key=lambda item: (
            max(abs(item["world"][0] - player[0]), abs(item["world"][1] - player[1])), item["at"]))
        self.entries.remove(entry)
        return entry

    def clear(self):
        self.entries = []


def corpse_offset(corpse_world, player_position, fallback_offset):
    """Return (dx, dy) of the corpse tile relative to the player.

    Pozycja w świecie jest pewniejsza (postać mogła się ruszyć po zabiciu
    celu), ale tylko na tym samym piętrze; w innym wypadku zostaje
    przesunięcie zapamiętane z mapy gry w chwili ataku.
    """
    if (corpse_world is not None and player_position is not None
            and corpse_world[2] == player_position[2]):
        return corpse_world[0] - player_position[0], corpse_world[1] - player_position[1]
    return tuple(fallback_offset) if fallback_offset is not None else None


def click_offsets(corpse_world, player_position, fallback_offset, screen_first=False):
    """Tiles to right-click in turn, the first one most likely to hold the corpse.

    Pozycja z minimapy spóźnia się, gdy postać idzie za celem, więc pole
    wyliczone ze świata bywa przesunięte o jedno. Druga próba to pole
    zapamiętane prosto z mapy gry (względem postaci). Pola poza widokiem odpadają;
    pole postaci (0, 0) jako druga próba też — tam mogą leżeć schody czy drabina.
    screen_first — pole z mapy gry jest świeże (sprzed ułamka sekundy), więc idzie
    pierwsze, a pole ze świata (spóźniona minimapa) dopiero po nim.
    """
    offsets = []
    world = corpse_offset(corpse_world, player_position, fallback_offset)
    screen = tuple(fallback_offset) if fallback_offset is not None else None
    if screen == (0, 0):
        screen = None
    order = (screen, world) if screen_first else (world, screen)
    for offset in order:
        if (offset is not None and offset not in offsets
                and abs(offset[0]) <= PLAYER_TILE[0] and abs(offset[1]) <= PLAYER_TILE[1]):
            offsets.append(offset)
    return offsets


def open_ground(otmm_map, world):
    """True when the .otmm map shows a plain walkable tile there (no stairs, ladder or hole).

    Prawy klik na polu to „użyj” górnego przedmiotu: na schodach czy drabinie
    zmieniłby piętro, więc pola obok przewidywanego ciała klikamy tylko,
    gdy mapa pokazuje zwykłą podłogę.
    """
    from .minimap import FLAG_NOT_PATHABLE, FLAG_NOT_WALKABLE, FLAG_SEEN

    if otmm_map is None or world is None:
        return False
    tile = otmm_map.tile(*world)
    return (tile is not None and bool(tile[1] & FLAG_SEEN)
            and not tile[1] & (FLAG_NOT_WALKABLE | FLAG_NOT_PATHABLE))


def search_offsets(estimate, player, open_tile):
    """Tiles the player reaches without walking, nearest to the estimated corpse tile first.

    estimate — wyliczone przesunięcie ciała względem postaci (albo None).
    Ciało często leży gdzie indziej, niż wyszło z obliczeń (minimapa spóźniona,
    potwór w ruchu, ostatnia klatka z czerwonym kwadratem sprzed 1–2 s), ale
    przy walce wręcz prawie zawsze tuż obok postaci. Bierzemy więc wszystkie
    pola w zasięgu ręki (także własne), tylko zwykłą podłogę, najbliższe
    wyliczonemu najpierw.
    """
    cx, cy = estimate if estimate is not None else (0, 0)
    if player is None or open_tile is None or max(abs(cx), abs(cy)) > SEARCH_RANGE:
        return []
    result = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if (dx, dy) == (cx, cy):
                continue
            if open_tile((player[0] + dx, player[1] + dy, player[2])):
                result.append((dx, dy))
    result.sort(key=lambda offset: (abs(offset[0] - cx) + abs(offset[1] - cy),
                                    max(abs(offset[0] - cx), abs(offset[1] - cy)), offset == (0, 0)))
    return result


def tile_click_point(view, tile, dx, dy):
    """Screen point in the middle of the tile (dx, dy), kept inside the game view."""
    x = int(view[0] + (PLAYER_TILE[0] + dx + 0.5) * tile)
    y = int(view[1] + (PLAYER_TILE[1] + dy + 0.5) * tile)
    x = min(view[2] - 2, max(view[0] + 1, x))
    y = min(view[3] - 2, max(view[1] + 1, y))
    return x, y


def inside(point, region):
    return region[0] <= point[0] < region[2] and region[1] <= point[1] < region[3]


def loot_slot_problem(loot_slot, corpse_region, windows):
    """Why the marked backpack slot cannot receive loot now, or None when it is fine."""
    if loot_slot is None:
        return "nie ustawiono slotu plecaka na loot"
    if inside(loot_slot, corpse_region):
        return "zaznaczony slot plecaka jest teraz zasłonięty oknem ciała"
    if not any(inside(loot_slot, region) for region in windows if region != corpse_region):
        return "zaznaczony slot plecaka nie leży w żadnym otwartym oknie (zamknięty plecak?)"
    return None


def lootable(items, patterns, use_meat):
    """Items to move to the backpack: enabled patterns, without Meat when it is eaten."""
    result = []
    for item in items:
        pattern = patterns.get(item.get("pattern"))
        if pattern is None or not pattern["enabled"]:
            continue
        if use_meat and is_meat(pattern):
            continue
        result.append(item)
    return result


def summary_message(new_names, known_names, crop_count, learn, meat_note=None,
                    looted=(), loot_note=None, skipped=()):
    """Status line describing what was found in (and taken from) the corpse.

    known_names — rozpoznane wzorce z „Zabieraj”, skipped — rozpoznane bez
    „Zabieraj” (bot ich nie bierze; zwykle trzeba im nadać nazwę i zaznaczyć).
    """
    if looted:
        message = f"Ciało: zabrano {', '.join(looted)}."
    elif known_names:
        message = f"Ciało: rozpoznane przedmioty: {', '.join(known_names)}."
    elif skipped or new_names:
        message = "Ciało otwarte."
    elif crop_count and not learn:
        message = (
            f"Otwarto ciało; widzę {crop_count} ikon. "
            "Włącz automatyczny zapis, aby dodać nieznane wzorce."
        )
    elif crop_count:
        message = f"Otwarto ciało; widzę {crop_count} ikon, ale żadnej nie rozpoznałem."
    else:
        message = "Otwarto ciało; jest puste."
    if skipped:
        message += f" Pomijam (bez „Zabieraj”): {', '.join(skipped)}."
    if new_names:
        sample = ", ".join(new_names[:3])
        suffix = f" i {len(new_names) - 3} kolejnych" if len(new_names) > 3 else ""
        message += f" Nowe wzorce ({len(new_names)}): {sample}{suffix} — nadaj im nazwy w karcie Loot."
    if meat_note:
        message += f" {meat_note}"
    if loot_note:
        message += f" Loot: {loot_note}."
    return message


def inspect_corpse(pid, corpse_world, fallback_offset, player_position,
                   cached_view=None, learn=False, use_meat=True,
                   loot=False, loot_slot=None, should_stop=None, player_now=None,
                   open_tile=None, screen_first=False):
    """Open the corpse and return {"message", "new_patterns", "looted", "debug", "timing", "retry"}.

    new_patterns i looted to listy nazw, debug to ścieżka obrazu z wykrytymi
    slotami (albo None), timing — czasy etapów do logu. player_now() zwraca
    bieżącą pozycję postaci (z minimapy): dopóki się zmienia, bot czeka na okno.
    retry — ciało się nie otworzyło, ale warto spróbować jeszcze raz po walce.
    Gdy wyliczone pole ciała nie odpowiada, klikamy też pola wokół postaci
    (tylko te, dla których open_tile(pole świata) zwraca True).

    Wywołuj poza wątkiem GUI: funkcja robi zrzuty, klika i czeka na okno.
    Nigdy nie rzuca wyjątku; błąd trafia do komunikatu. should_stop() może
    przerwać lootowanie między przeciągnięciami (np. STOP / F12).
    """
    result = {"message": "Nie udało się otworzyć ciała.", "new_patterns": [], "looted": [],
              "debug": None, "timing": None, "retry": False}
    try:
        result["message"] = _inspect(
            pid, corpse_world, fallback_offset, player_position, cached_view,
            learn, use_meat, loot, loot_slot, should_stop or (lambda: False), player_now, result,
            open_tile, screen_first,
        )
    except Exception as exc:
        result["message"] = f"Sprawdzanie ciała nie powiodło się: {exc}"
    return result


def is_corpse_title(title):
    """True for corpse window titles such as „Dead larva”, „Slain rat”, „Remains of a ghoul”."""
    words = "".join(char if char.isalpha() else " " for char in title.casefold()).split()
    return any(word in CORPSE_TITLE_WORDS for word in words)


def open_timeout(dx, dy):
    """Seconds to wait for the corpse window; the client first walks next to a distant corpse."""
    return OPEN_TIMEOUT + WALK_TIME_PER_TILE * max(0, max(abs(dx), abs(dy)) - 1)


class OpenWait:
    """When to stop waiting for the corpse window.

    Czekamy co najmniej `minimum` sekund; dłużej tylko dopóki postać idzie
    (zmienia się jej pozycja z minimapy) albo stoi krócej niż STILL_TIME —
    klient po prawym kliku sam podchodzi do dalszego ciała. Nigdy dłużej
    niż MAX_OPEN_WAIT. Bez pozycji postaci (None) — samo minimum.
    """

    def __init__(self, minimum, now, position):
        self.start = now
        self.minimum = minimum
        self.position = position
        self.moved_at = now

    def expired(self, now, position):
        if position != self.position:
            self.position = position
            self.moved_at = now
        if now - self.start >= MAX_OPEN_WAIT:
            return True
        if now - self.start < self.minimum:
            return False
        if position is None:
            return True
        return now - self.moved_at >= STILL_TIME


def corpse_body(body, scale):
    """Body rectangle limited to the height of a corpse (the window bottom is sometimes misread)."""
    left, top, right, bottom = body
    limit = top + int(MAX_CORPSE_HEIGHT * max(1.0, float(scale or 1.0)))
    return left, top, right, min(bottom, limit)


def _same_header(frame, others, tolerance=2):
    return any(abs(frame["close"][0] - other["close"][0]) <= tolerance
               and abs(frame["close"][1] - other["close"][1]) <= tolerance for other in others)


def _tesseract():
    try:
        return find_tesseract()
    except RuntimeError:
        return None


def pick_corpse_window(candidates, titles):
    """Choose the corpse among windows that appeared after the click.

    Z tytułami (OCR) wybieramy okno, którego tytuł wygląda na ciało. Bez
    Tesseract — najmniejsze nowe okno: inne okna panelu po przestawieniu
    (Skills, VIP) są większe, a ciało ma tylko kilka slotów.
    """
    if titles is not None:
        return next((frame for frame, title in zip(candidates, titles) if is_corpse_title(title)), None)
    if not candidates:
        return None
    return min(candidates, key=lambda frame: (frame["body"][2] - frame["body"][0])
               * (frame["body"][3] - frame["body"][1]))


def _close_open_corpses(pid, image, frames, scale, tesseract):
    """Close corpse windows left open (a new corpse would reuse such a window); return True if any."""
    closed = False
    for frame, title in zip(frames, read_titles(image, frames, scale, tesseract)):
        if is_corpse_title(title):
            closed = send_left_click(pid, *frame["close"]) or closed
    return closed


def cell_changed(before, after, level=40, fraction=0.004):
    """True when the slot looks different after an action (item eaten or moved).

    Liczy odsetek wyraźnie zmienionych pikseli, a nie średnią: przy stosie
    mięsa po zjedzeniu jednego zmienia się tylko cyfra liczby sztuk.
    """
    import numpy

    if before is None or after is None or before.shape != after.shape:
        return True
    diff = numpy.abs(before.astype(numpy.int16) - after.astype(numpy.int16)).max(axis=2)
    return float((diff > level).mean()) >= fraction


class _Timer:
    """Czasy etapów otwierania ciała do logu (diagnostyka opóźnień)."""

    def __init__(self):
        self.start = self.last = time.monotonic()
        self.parts = []

    def mark(self, label):
        now = time.monotonic()
        self.parts.append(f"{label} {now - self.last:.1f}s")
        self.last = now

    def text(self):
        return f"{', '.join(self.parts)}; razem {time.monotonic() - self.start:.1f}s"


def _inspect(pid, corpse_world, fallback_offset, player_position, cached_view,
             learn, use_meat, loot, loot_slot, should_stop, player_now, result, open_tile=None,
             screen_first=False):
    bounds = foreground_client_bounds(pid)
    if bounds is None:
        return "Nie otworzyłem ciała: okno gry nie jest aktywne."
    client = (0, 0, bounds[2], bounds[3])
    before = capture_region(pid, client, grayscale=False, label="okna klienta")
    if before is None:
        return "Nie otworzyłem ciała: brak aktywnego obrazu gry."
    timer = _Timer()
    tesseract = _tesseract()
    view = cached_view or find_game_view(before[:, :, :3])
    if view is None:
        return "Nie otworzyłem ciała: nie rozpoznaję mapy gry."
    # Małe okna leżą tylko w panelach obok mapy gry; skala z poprzedniego ciała.
    columns = panel_columns(bounds[2], view)

    def frames_of(image):
        global _last_scale
        found_scale, found = find_mini_window_frames(image, _last_scale, columns=columns)
        if found_scale is not None:
            _last_scale = found_scale
        return found_scale, found

    scale, before_frames = frames_of(before)
    closed = bool(tesseract) and _close_open_corpses(pid, before, before_frames, scale, tesseract)
    timer.mark("stare ciała")
    if closed:
        time.sleep(CLOSE_DELAY)
        before = capture_region(pid, client, grayscale=False, label="okna klienta")
        if before is None:
            return "Nie otworzyłem ciała: brak aktywnego obrazu gry."
        scale, before_frames = frames_of(before)
    start = player_now() if player_now else None
    here = start or player_position
    offsets = click_offsets(corpse_world, here, fallback_offset, screen_first)
    estimate = corpse_offset(corpse_world, here, fallback_offset)
    if not offsets:
        # Szukanie wokół postaci ma sens tylko, gdy ciało jest blisko (zabite wręcz).
        if estimate is None:
            return "Ciało leży na innym piętrze; pomijam je."
        return f"Ciało jest poza widokiem gry ({estimate[0]:+d}, {estimate[1]:+d}); pomijam je."
    game_area = before[view[1]:view[3], view[0]:view[2], :3]
    local_view = (0, 0, view[2] - view[0], view[3] - view[1])
    visible_creatures, _player_found = locate_creatures(game_area, local_view)
    occupied = {(item["dx"], item["dy"]) for item in visible_creatures}

    def next_click(tried):
        """Next tile to click, relative to the current player position, or None.

        Po pierwszym kliku postać mogła podejść do ciała, więc przesunięcia
        liczymy od nowa; pole zapamiętane z mapy gry (względem starej pozycji)
        ma sens tylko, dopóki postać się nie ruszyła. Pole z żywym stworem
        pomijamy (tylko dopóki obraz sprzed kliknięć jest aktualny).
        """
        position = player_now() if player_now else None
        moved = start is not None and position is not None and position != start
        position = position or here
        fallback = None if moved else fallback_offset
        fresh = click_offsets(corpse_world, position, fallback, screen_first)
        nearby = search_offsets(corpse_offset(corpse_world, position, fallback), position, open_tile)
        for offset in fresh + nearby:
            key = (position[0] + offset[0], position[1] + offset[1]) if position else offset
            if key in tried or (not moved and offset in occupied):
                continue
            tried.add(key)
            return offset
        return None

    after, after_frames, changed, clicks, tried_offsets, tried = None, [], False, [], [], set()
    limit = 2 + (MAX_SEARCH_CLICKS if open_tile is not None else 0)

    def wait_for_window(minimum, walking):
        """Poll until the window headers change or the wait expires; return an error or None.

        walking — klient może iść do ciała, więc czekamy dłużej, dopóki postać się rusza.
        """
        nonlocal after, after_frames, changed, scale
        position = (lambda: player_now() if player_now else None) if walking else (lambda: None)
        wait = OpenWait(minimum, time.monotonic(), position())
        while True:
            time.sleep(POLL_DELAY)
            if should_stop():
                return "Otwieranie ciała przerwane (STOP)."
            after = capture_region(pid, client, grayscale=False, label="otwartego ciała")
            if after is None:
                result["retry"] = True
                return "Kliknąłem ciało, ale nie mogę odczytać okna gry."
            scale, after_frames = frames_of(after)
            changed = (len(after_frames) != len(before_frames)
                       or any(not _same_header(frame, before_frames) for frame in after_frames))
            if changed or wait.expired(time.monotonic(), position()):
                return None

    while len(tried_offsets) < limit:
        offset = next_click(tried)
        if offset is None:
            break
        dx, dy = offset
        tried_offsets.append(offset)
        x, y = tile_click_point(view, tile_size(view), dx, dy)
        clicks.append((x, y))
        if not send_right_click(pid, x, y):
            return "Nie otworzyłem ciała: okno gry przestało być aktywne."
        # Czekamy, aż zmienią się nagłówki okien. Do dalszego ciała klient najpierw
        # podchodzi, a postać idzie różnie szybko — czekamy, dopóki się porusza.
        # Pole w zasięgu ręki: krótko, gdy zostały jeszcze inne pola do sprawdzenia.
        quick = open_tile is not None and max(abs(dx), abs(dy)) <= 1
        error = wait_for_window(QUICK_OPEN_WAIT if quick else open_timeout(dx, dy), not quick)
        if error:
            return error
        if changed:
            break
    if clicks and not changed:
        # Okno z któregoś kliknięcia mogło się spóźnić.
        error = wait_for_window(LATE_WINDOW_WAIT, False)
        if error:
            return error
    if not tried_offsets:
        result["retry"] = True
        return "Nie kliknąłem: na polu ciała stoi żywa postać."
    timer.mark("okno")
    if not changed:
        result["timing"] = timer.text()
        # Obraz mapy z krzyżykami kliknięć: widać, czy ciało leżało obok.
        result["debug"] = save_debug_image(before, view, scale, [], label="miss", marks=clicks, grid=False)
        result["retry"] = True
        tried = ", ".join(f"({dx:+d}, {dy:+d})" for dx, dy in tried_offsets)
        return f"Kliknąłem pole ciała {tried}, ale nie pojawiło się okno ciała."
    if tesseract:
        # Okno ciała mogło stanąć w miejscu innego okna i przesunąć resztę panelu,
        # więc nie ufamy pozycjom: czytamy tytuły wszystkich okien (z pamięci,
        # a nieznane równolegle). Stare ciała zamknęliśmy przed kliknięciem,
        # więc okno z tytułem ciała jest nowe.
        time.sleep(SETTLE_DELAY)
        settled = capture_region(pid, client, grayscale=False, label="otwartego ciała")
        if settled is not None:
            after = settled
        scale, after_frames = frames_of(after)
        candidates = after_frames
        titles = read_titles(after, candidates, scale, tesseract)
    else:
        candidates = [frame for frame in after_frames if not _same_header(frame, before_frames)]
        titles = None
    timer.mark("tytuły")
    corpse = pick_corpse_window(candidates, titles)
    if corpse is None:
        result["timing"] = timer.text()
        seen = ", ".join(f"„{title}”" for title in titles or [] if title) or "brak tytułów"
        result["retry"] = True
        return f"Nowe okno nie wygląda na ciało ({seen})."
    region = corpse_body(corpse["body"], scale)
    close_button = corpse["close"]

    items = find_slot_items(after, region, scale)
    patterns = load_patterns()
    identify_items(items, patterns)
    new_names = learn_unknown(items, patterns) if learn else []
    result["new_patterns"] = new_names
    known_names, skipped = [], []
    for item in items:
        pattern = patterns.get(item["pattern"])
        if pattern is None or pattern["name"] in new_names:
            continue
        if pattern["enabled"]:
            if pattern["name"] not in known_names:
                known_names.append(pattern["name"])
        elif not is_meat(pattern) and pattern["name"] not in skipped:
            skipped.append(pattern["name"])
    result["debug"] = save_debug_image(after, region, scale, items)
    timer.mark("sloty")

    # Jedzenie nie zależy od „Zabieraj”: to pole mówi tylko, czy przenosić do plecaka.
    meat = next((item for item in items if item["pattern"] is not None
                 and is_meat(patterns[item["pattern"]])), None)
    meat_note = None
    if use_meat and meat is not None:
        meat_note = _eat_meat(pid, client, region, scale, items, meat)
        timer.mark("meat")

    loot_note = None
    if loot:
        windows = [frame["body"] for frame in after_frames]
        loot_note = loot_slot_problem(loot_slot, corpse["body"], windows)
        if loot_note is None:
            looted, loot_note = _move_loot(pid, client, region, scale, patterns, loot_slot,
                                           use_meat, should_stop)
            result["looted"] = looted
        timer.mark("loot")
    if not should_stop():
        # Okno zamykamy zawsze: kolejne ciało otworzyłoby się w tym samym oknie,
        # a otwarte okna zasłaniają plecak.
        send_left_click(pid, *close_button)
    result["timing"] = timer.text()
    return summary_message(new_names, known_names, len(items), learn, meat_note,
                           result["looted"], loot_note, skipped)


def _eat_meat(pid, client, region, scale, items, meat):
    """Right-click the meat until its slot changes; return the status sentence.

    Serwer odrzuca użycie przedmiotu zbyt szybko po poprzedniej akcji (tu:
    otwarciu ciała), więc po nieudanej próbie czekamy i klikamy jeszcze raz.
    Obraz „meat” w loot_debug pokazuje miejsce kliknięcia (czerwony krzyżyk)
    i slot po ostatniej próbie.
    """
    box = meat["box"]
    check = None
    eaten = False
    for attempt in range(MEAT_ATTEMPTS):
        if attempt:
            time.sleep(MEAT_RETRY_DELAY)
        if not send_right_click(pid, *meat["center"]):
            return "Nie kliknąłem Meat (okno gry nieaktywne)."
        time.sleep(MOVE_DELAY)
        check = capture_region(pid, client, grayscale=False, label="ciała po jedzeniu")
        cell = None if check is None else check[box[1]:box[3], box[0]:box[2], :3]
        if cell_changed(meat["cell"], cell):
            eaten = True
            break
    if check is not None:
        save_debug_image(check, region, scale, items, label="meat", marks=[meat["center"]])
    if eaten:
        return "Zjadłem Meat."
    # Klient nie je, gdy postać jest najedzona („You are full”).
    return f"Meat zostało w ciele po {MEAT_ATTEMPTS} kliknięciach (najedzona albo klik obok — obraz „meat” w loot_debug)."


def _move_loot(pid, client, region, scale, patterns, loot_slot, use_meat, should_stop):
    """Drag enabled items to the backpack slot; return (looted names, note or None)."""
    looted = []
    pending = None  # (wzorzec, ile takich było przed przeciągnięciem)
    failures = 0
    spread = max(1, round(4 * max(1.0, float(scale or 1.0))))
    for _move in range(MAX_LOOT_MOVES + 1):
        if should_stop():
            return looted, "przerwano (STOP)"
        image = capture_region(pid, client, grayscale=False, label="ciała przy lootowaniu")
        if image is None:
            return looted, "okno gry przestało być aktywne"
        items = identify_items(find_slot_items(image, region, scale), patterns)
        if pending is not None:
            pattern_id, count = pending
            name = patterns[pattern_id]["name"]
            if sum(item["pattern"] == pattern_id for item in items) < count:
                looted.append(name)
                failures = 0
            else:
                # Przedmiot nadal leży w ciele: serwer odrzucił przeniesienie.
                failures += 1
                if failures >= MAX_MOVE_FAILURES:
                    return looted, f"„{name}” nie przenosi się (plecak pełny albo za ciężki)"
            pending = None
        targets = lootable(items, patterns, use_meat)
        if not targets:
            return looted, None
        if _move == MAX_LOOT_MOVES:
            break
        item = targets[0]
        pending = (item["pattern"], sum(other["pattern"] == item["pattern"] for other in items))
        source = (human.jitter(item["center"][0], spread), human.jitter(item["center"][1], spread))
        target = (human.jitter(loot_slot[0], spread), human.jitter(loot_slot[1], spread))
        # Klient przenosi cały stos zwykłym przeciągnięciem (bez Ctrl).
        if not drag_item(pid, *source, *target,
                         out_of_window_message="Slot ciała lub plecaka jest poza oknem gry."):
            return looted, "okno gry przestało być aktywne"
        time.sleep(MOVE_DELAY + human.reaction("walk"))
    return looted, f"przerwano po {MAX_LOOT_MOVES} przeciągnięciach"
