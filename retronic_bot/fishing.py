"""Wędkowanie: pola wody w widoku gry i łączenie ryb w plecaku w jeden stos.

Wodę bot rozpoznaje z pliku .otmm: pole wody ma na minimapie kolor 40
(RGB 51, 0, 204). Z pozycji postaci (minimapa) i stałego widoku 15 × 11 pól
wie, które pola na ekranie są wodą; zrzut mapy gry tylko to potwierdza
(woda jest niebieska), a bez pozycji z minimapy służy jako jedyne źródło.

Złowiona ryba trafia do pierwszego slotu plecaka jako nowy stos, bo klient
nie łączy jej z rybami w innych slotach. Bot znajduje sloty z rybą po wzorcu
(tylko górna część ikony — liczba sztuk jest w dolnym rogu) i przeciąga
pierwszy slot na kolejny, który nie jest pełny (100 sztuk).
"""

import random

from .creatures import PLAYER_TILE, VIEW_TILES, tile_size

WATER_COLOR = 40
# Górna część wzorca ryby, bez liczby sztuk w prawym dolnym rogu.
TEMPLATE_TOP = 0.55


NEIGHBORS = [(nx, ny) for ny in (-1, 0, 1) for nx in (-1, 0, 1) if (nx, ny) != (0, 0)]


def is_inner(is_water, dx, dy):
    """True when the tile and all 8 neighbors are water.

    Brzeg to pole wody z nałożoną krawędzią lądu: na minimapie ma kolor wody,
    ale łowić na nim się nie da. Krawędź leży na polu wody obok lądu, więc
    łowne jest tylko pole otoczone wodą ze wszystkich stron (także po skosie).
    """
    return is_water(dx, dy) and all(is_water(dx + nx, dy + ny) for nx, ny in NEIGHBORS)


def water_tiles(otmm_map, position, max_distance=6):
    """Offsets (dx, dy) of fishable water tiles (no shore) visible in the game view."""
    x, y, z = position
    half_w, half_h = PLAYER_TILE

    def is_water(dx, dy):
        tile = otmm_map.tile(x + dx, y + dy, z)
        return tile is not None and tile[0] == WATER_COLOR

    tiles = []
    for dy in range(-half_h, VIEW_TILES[1] - half_h):
        for dx in range(-half_w, VIEW_TILES[0] - half_w):
            if (dx, dy) == (0, 0) or max(abs(dx), abs(dy)) > max_distance:
                continue
            if is_inner(is_water, dx, dy):
                tiles.append((dx, dy))
    return tiles


def tile_center(view, dx, dy):
    """Client pixel at the center of the tile (dx, dy) away from the character."""
    left, top = view[0], view[1]
    size = tile_size(view)
    return (int(left + (PLAYER_TILE[0] + dx + 0.5) * size),
            int(top + (PLAYER_TILE[1] + dy + 0.5) * size))


def looks_like_water(image_bgr, view, dx, dy, min_share=0.5):
    """True when most of the tile's middle is blue (water sprites, not grass or a creature)."""
    import numpy

    size = tile_size(view)
    cx, cy = tile_center(view, dx, dy)
    half = max(2, int(size * 0.3))
    crop = image_bgr[max(0, cy - half):cy + half, max(0, cx - half):cx + half, :3]
    if crop.size == 0:
        return False
    pixels = crop.astype(numpy.int16)
    blue = pixels[:, :, 0] - numpy.maximum(pixels[:, :, 1], pixels[:, :, 2])
    return float((blue >= 25).mean()) >= min_share


def visible_water(image_bgr, view, max_distance=6):
    """Fishable water offsets judged from the screenshot alone (no minimap position).

    Pola poza widokiem są nieznane, więc pole na skraju widoku nie przejdzie
    sprawdzenia sąsiadów — lepiej je pominąć, niż rzucać w brzeg.
    """
    half_w, half_h = PLAYER_TILE
    water = {
        (dx, dy)
        for dy in range(-half_h, VIEW_TILES[1] - half_h)
        for dx in range(-half_w, VIEW_TILES[0] - half_w)
        if looks_like_water(image_bgr, view, dx, dy)
    }
    return sorted(
        (dx, dy) for dx, dy in water
        if (dx, dy) != (0, 0) and max(abs(dx), abs(dy)) <= max_distance
        and is_inner(lambda tx, ty: (tx, ty) in water, dx, dy)
    )


def pick_tile(candidates, recent=(), rng=random):
    """Random water tile, avoiding the last few used ones while others remain."""
    if not candidates:
        return None
    fresh = [tile for tile in candidates if tile not in recent]
    return rng.choice(fresh or list(candidates))


def find_fish_slots(image_bgr, template, threshold=0.85, exclude=()):
    """Centers (x, y) of every slot showing the fish, in container order.

    exclude — prostokąty (left, top, right, bottom) pomijane przy szukaniu,
    np. mapa gry, gdzie ryba może leżeć na ziemi.
    """
    import cv2
    import numpy

    if template is None:
        return []
    height, width = template.shape[:2]
    top = template[:max(4, int(height * TEMPLATE_TOP)), :, :3]
    if image_bgr.shape[0] < top.shape[0] or image_bgr.shape[1] < top.shape[1]:
        return []
    scores = cv2.matchTemplate(image_bgr[:, :, :3], top, cv2.TM_CCOEFF_NORMED)
    found = []
    for y, x in zip(*numpy.nonzero(scores >= threshold)):
        found.append((float(scores[y, x]), int(x) + width // 2, int(y) + height // 2))
    found.sort(reverse=True)
    slots = []
    for _score, x, y in found:
        if any(ex_l <= x < ex_r and ex_t <= y < ex_b for ex_l, ex_t, ex_r, ex_b in exclude):
            continue
        # Jedno dopasowanie na slot: sąsiednie piksele tego samego slotu odpadają.
        if all(abs(x - sx) >= width * 0.6 or abs(y - sy) >= height * 0.6 for sx, sy in slots):
            slots.append((x, y))
    return reading_order(slots, height)


def reading_order(points, row_height):
    """Sort slot centers row by row (top to bottom), left to right in a row."""
    rows = []
    for point in sorted(points, key=lambda p: p[1]):
        if rows and abs(point[1] - rows[-1][0][1]) < row_height * 0.5:
            rows[-1].append(point)
        else:
            rows.append([point])
    return [point for row in rows for point in sorted(row)]


def stack_move(slots, is_full):
    """(source, target) for the next merge, or None when nothing can be merged.

    Nowa ryba pojawia się w pierwszym slocie, więc ten slot jest źródłem;
    celem jest najbliższy kolejny slot, którego stos nie jest pełny.
    is_full(slot) mówi, czy stos w slocie ma już 100 sztuk.
    """
    if len(slots) < 2:
        return None
    source = slots[0]
    for target in slots[1:]:
        if not is_full(target):
            return source, target
    return None
