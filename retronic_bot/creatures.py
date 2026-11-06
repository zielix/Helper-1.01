"""Stwory na ekranie gry: pozycje w polach, cel ataku i osiągalność.

Klient rysuje mapę w prostokącie z czarną ramką, zawsze 15 × 11 pól, z
postacią na środkowym polu (7, 5). Nad każdym stworem jest pasek życia:
czarna ramka i kolorowe wypełnienie; pod paskiem własnej postaci jest
jeszcze niebieski pasek many — po tym bot odróżnia siebie od potworów.
Atakowany stwór ma czysto czerwony kwadrat wielkości pola.
"""

import heapq

VIEW_TILES = (15, 11)
PLAYER_TILE = (7, 5)


def _masks(image_bgr):
    """Return (image, max channel, min channel) as uint8; cv2 is ~20× faster than numpy here."""
    import cv2

    blue, green, red = cv2.split(image_bgr[:, :, :3])
    high = cv2.max(cv2.max(blue, green), red)
    low = cv2.min(cv2.min(blue, green), red)
    return image_bgr[:, :, :3], high, low


def find_game_view(image_bgr):
    """Return (left, top, right, bottom) of the game map inside the client, or None.

    Mapa ma 1–2 px czarnej ramki, a za nią szare tło paneli klienta. Szukamy
    kolumn i wierszy, w których czarny piksel sąsiaduje z szarym tłem na
    długim odcinku, i sprawdzamy proporcje 15 : 11.
    """
    import numpy

    _pixels, high, low = _masks(image_bgr)
    height, width = high.shape
    import cv2

    black = high <= 6
    panel = (low >= 12) & (high <= 70) & (cv2.subtract(high, low) <= 14)

    left_edge = numpy.zeros_like(black)
    left_edge[:, 1:] = black[:, 1:] & panel[:, :-1]
    right_edge = numpy.zeros_like(black)
    right_edge[:, :-1] = black[:, :-1] & panel[:, 1:]
    top_edge = numpy.zeros_like(black)
    top_edge[1:, :] = black[1:, :] & panel[:-1, :]
    bottom_edge = numpy.zeros_like(black)
    bottom_edge[:-1, :] = black[:-1, :] & panel[1:, :]

    def candidates(scores, minimum, keep=6):
        order = numpy.argsort(scores)[::-1]
        picked = []
        for index in order:
            if scores[index] < minimum or len(picked) >= keep:
                break
            if all(abs(int(index) - other) > 3 for other in picked):
                picked.append(int(index))
        return picked

    lefts = candidates(left_edge.sum(axis=0), height * 0.25)
    rights = candidates(right_edge.sum(axis=0), height * 0.25)
    tops = candidates(top_edge.sum(axis=1), width * 0.2)
    bottoms = candidates(bottom_edge.sum(axis=1), width * 0.2)
    best = None
    for left in lefts:
        for right in rights:
            if right - left < width * 0.25:
                continue
            for top in tops:
                for bottom in bottoms:
                    if bottom - top < height * 0.25:
                        continue
                    view_w, view_h = right - left - 1, bottom - top - 1
                    ratio = (view_w / VIEW_TILES[0]) / (view_h / VIEW_TILES[1])
                    if not 0.94 <= ratio <= 1.06:
                        continue
                    area = view_w * view_h
                    if best is None or area > best[0]:
                        best = (area, (left + 1, top + 1, right, bottom))
    return best[1] if best else None


def tile_size(view):
    left, top, right, bottom = view
    return ((right - left) / VIEW_TILES[0] + (bottom - top) / VIEW_TILES[1]) / 2


def find_health_bars(image_bgr, view=None):
    """Return health bars drawn above creatures on the map.

    Każdy wpis: {"x": środek x, "y": środek y paska, "width", "hp": 0–100,
    "player": True dla własnej postaci (pasek many pod spodem)}.
    """
    import cv2
    import numpy

    left, top = (view[0], view[1]) if view else (0, 0)
    area = image_bgr[view[1]:view[3], view[0]:view[2]] if view else image_bgr
    pixels, high, low = _masks(area)
    black = (high <= 8).astype(numpy.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(black, connectivity=4)
    bars = []
    widths, heights = stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]
    shaped = numpy.nonzero((widths >= 16) & (heights >= 4) & (heights <= 40) & (widths >= 3 * heights))[0]
    for index in shaped:
        if index == 0:
            continue
        x, y, w, h, _size = (int(value) for value in stats[index])
        box = pixels[y:y + h, x:x + w].astype(numpy.int16)
        box_black = black[y:y + h, x:x + w].astype(bool)
        # Ramka paska: górny i dolny wiersz oraz boki prawie całe czarne.
        if box_black[0].mean() < 0.9 or box_black[-1].mean() < 0.9:
            continue
        if box_black[:, 0].mean() < 0.9 or box_black[:, -1].mean() < 0.9:
            continue
        # Ramka ma 1 px w skali 100% i 2 px przy 200%.
        border = 2 if h >= 8 and box_black[1].mean() >= 0.9 else 1
        inner = box[border:-border, border:-border]
        if inner.size == 0:
            continue
        inner_high = inner.max(axis=2)
        inner_low = inner.min(axis=2)
        inner_dark = inner_high <= 45
        colored = (inner_high >= 60) & (inner_high - inner_low >= 50)
        # Wnętrze: tylko wypełnienie i ciemne tło pustej części paska.
        if not (colored | inner_dark).mean() >= 0.97 or not colored.any():
            continue
        blue = colored & (inner[:, :, 0] > inner[:, :, 1] + 30) & (inner[:, :, 0] > inner[:, :, 2] + 30)
        health_rows = [row for row in range(inner.shape[0])
                       if colored[row].any() and not blue[row].any()]
        if not health_rows:
            continue
        middle = health_rows[len(health_rows) // 2]
        filled = int((colored[middle] & ~blue[middle]).sum())
        bars.append({
            "x": left + x + w / 2,
            "y": top + y + (health_rows[0] + health_rows[-1]) / 2 + 1,
            "width": w,
            "hp": round(100 * filled / max(1, inner.shape[1])),
            "player": bool(blue.any()),
        })
    return bars


def attack_square(image_bgr, view):
    """Return (x, y) center of the red attack square on the map, or None."""
    import numpy

    area = image_bgr[view[1]:view[3], view[0]:view[2], :3]
    red = (area[:, :, 2] >= 225) & (area[:, :, 1] <= 40) & (area[:, :, 0] <= 40)
    tile = tile_size(view)
    # Kwadrat to dwa długie poziome boki o długości pola; krew i czary są krótsze.
    rows = numpy.nonzero(red.sum(axis=1) >= tile * 0.6)[0]
    cols = numpy.nonzero(red.sum(axis=0) >= tile * 0.6)[0]
    if len(rows) < 2 or len(cols) < 2:
        return None
    if not (tile * 0.75 <= rows[-1] - rows[0] <= tile * 1.25
            and tile * 0.75 <= cols[-1] - cols[0] <= tile * 1.25):
        return None
    return (view[0] + (cols[0] + cols[-1]) / 2, view[1] + (rows[0] + rows[-1]) / 2)


def locate_creatures(image_bgr, view):
    """Return (creatures, player_found) with tile offsets relative to the player.

    Pozycję w polach liczymy względem paska własnej postaci, który zawsze
    wisi nad środkowym polem; w trakcie chodzenia cała mapa przesuwa się
    o ułamek pola, a różnica względem postaci zostaje stała.
    """
    tile = tile_size(view)
    bars = find_health_bars(image_bgr, view)
    players = [bar for bar in bars if bar["player"]]
    center_x = view[0] + (PLAYER_TILE[0] + 0.5) * tile
    center_y = view[1] + (PLAYER_TILE[1] + 0.5) * tile
    if players:
        me = min(players, key=lambda bar: abs(bar["x"] - center_x) + abs(bar["y"] - center_y))
        anchor_x, anchor_y = me["x"], me["y"]
    else:
        me = None
        # Bez paska many: pasek wisi ok. 0,8 pola nad środkiem pola postaci.
        anchor_x, anchor_y = center_x - 0.2 * tile, center_y - 0.8 * tile
    creatures = []
    for bar in bars:
        if bar is me:
            continue
        creatures.append({
            "dx": round((bar["x"] - anchor_x) / tile),
            "dy": round((bar["y"] - anchor_y) / tile),
            "hp": bar["hp"],
            "x": bar["x"],
            "y": bar["y"],
            "player_like": bar["player"],
        })
    return creatures, me is not None


def square_offset(square, view):
    """Tile offset of the attack square relative to the player tile."""
    tile = tile_size(view)
    x, y = square
    return (int((x - view[0]) // tile) - PLAYER_TILE[0], int((y - view[1]) // tile) - PLAYER_TILE[1])


def reach_steps(otmm_map, start, target, blocked=(), limit=14):
    """Steps needed to stand next to target (x, y), or None when unreachable.

    Szukamy drogi po polach z mapy .otmm; pola innych stworów są blokadą,
    bo w Tibii nie da się przez nie przejść (stąd potwory „zablokowane” w
    tunelu przez inne potwory).
    """
    from .minimap import FLAG_NOT_PATHABLE, FLAG_NOT_WALKABLE, FLAG_SEEN

    sx, sy, z = start
    tx, ty = target
    if max(abs(sx - tx), abs(sy - ty)) <= 1:
        return 0
    if z not in otmm_map.floors:
        return None
    origin_x, origin_y, _colors, flags = otmm_map.floors[z]
    height, width = flags.shape
    stop = FLAG_NOT_WALKABLE | FLAG_NOT_PATHABLE
    blocked = set(blocked) | {(tx, ty)}

    def passable(x, y):
        if (x, y) in blocked:
            return False
        row, col = y - origin_y, x - origin_x
        if not (0 <= row < height and 0 <= col < width):
            return False
        value = int(flags[row, col])
        return bool(value & FLAG_SEEN) and not value & stop

    queue = [(0, sx, sy)]
    seen = {(sx, sy): 0}
    while queue:
        steps, x, y = heapq.heappop(queue)
        if max(abs(x - tx), abs(y - ty)) <= 1:
            return steps
        if steps >= limit:
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not dx and not dy:
                    continue
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen or not passable(nx, ny):
                    continue
                seen[(nx, ny)] = steps + 1
                heapq.heappush(queue, (steps + 1, nx, ny))
    return None
