"""Pozycja postaci z minimapy klienta (piksele) dopasowanej do pliku .otmm.

Plik .otmm (format minimapy OTClienta) zawiera kolor i flagi każdego pola.
Klient rysuje minimapę tymi samymi kolorami z palety 6 × 6 × 6, więc wystarczy
zamienić zrzut minimapy na siatkę kolorów pól i znaleźć ją w pliku. Bot nie
czyta przy tym pamięci klienta.
"""

import os
import struct
import time
import zlib
from collections import Counter, namedtuple
from pathlib import Path


DEFAULT_OTMM_PATH = Path(__file__).resolve().parent.parent / "maps" / "map74.otmm"
CLIENT_DIR = Path(__file__).resolve().parents[3] / "Retronic-Client"
UNKNOWN = 255
FLAG_SEEN = 1
FLAG_NOT_PATHABLE = 2
FLAG_NOT_WALKABLE = 4
BLOCK_SIZE = 64
# Paleta ma kroki co 51; tolerancja pozwala na drobne odchylenia przy zrzucie.
PALETTE_STEP = 51
PALETTE_TOLERANCE = 8

MinimapMatch = namedtuple(
    "MinimapMatch", "ok x y z score second_score known reason elapsed_ms"
)


class OtmmMap:
    """Floors of a .otmm file as dense color/flag arrays."""

    def __init__(self, floors):
        # z -> (origin_x, origin_y, colors[H, W], flags[H, W])
        self.floors = floors
        self._color_counts = {}
        self._color_positions = {}

    @classmethod
    def load(cls, path):
        import numpy

        data = Path(path).read_bytes()
        if data[:4] != b"OTMM":
            raise ValueError("Wybrany plik nie jest minimapą w formacie OTMM.")
        offset = struct.unpack_from("<H", data, 4)[0]
        blocks = []
        while offset + 5 <= len(data):
            x, y, z = struct.unpack_from("<HHB", data, offset)
            offset += 5
            if x == 0xFFFF and y == 0xFFFF:
                break
            size = struct.unpack_from("<H", data, offset)[0]
            offset += 2
            raw = zlib.decompress(data[offset:offset + size])
            offset += size
            if len(raw) != BLOCK_SIZE * BLOCK_SIZE * 3:
                raise ValueError("Uszkodzony blok w pliku minimapy.")
            blocks.append((x, y, z, raw))
        if not blocks:
            raise ValueError("Plik minimapy nie zawiera żadnych bloków.")

        # Plik bywa zaśmiecony pojedynczymi blokami daleko od mapy (np. x=0),
        # które rozdęłyby tablice. Zostawiamy tylko gęsto zapełnione obszary.
        density = Counter((x >> 10, y >> 10) for x, y, _z, _raw in blocks)
        blocks = [block for block in blocks if density[(block[0] >> 10, block[1] >> 10)] >= 8]

        floors = {}
        for z in sorted({block[2] for block in blocks}):
            items = [block for block in blocks if block[2] == z]
            min_x = min(x for x, _y, _z, _raw in items)
            min_y = min(y for _x, y, _z, _raw in items)
            width = max(x for x, _y, _z, _raw in items) + BLOCK_SIZE - min_x
            height = max(y for _x, y, _z, _raw in items) + BLOCK_SIZE - min_y
            colors = numpy.full((height, width), UNKNOWN, dtype=numpy.uint8)
            flags = numpy.zeros((height, width), dtype=numpy.uint8)
            for x, y, _z, raw in items:
                # Kafelek w bloku ma indeks y * 64 + x, czyli wiersze to Y.
                tiles = numpy.frombuffer(raw, dtype=numpy.uint8).reshape(
                    BLOCK_SIZE, BLOCK_SIZE, 3
                )
                seen = (tiles[:, :, 0] & FLAG_SEEN).astype(bool)
                rows = slice(y - min_y, y - min_y + BLOCK_SIZE)
                cols = slice(x - min_x, x - min_x + BLOCK_SIZE)
                colors[rows, cols] = numpy.where(seen, tiles[:, :, 1], UNKNOWN)
                flags[rows, cols] = tiles[:, :, 0]
            # Czarny (0) to w kliencie pole nieodkryte, więc nie służy do dopasowania.
            colors[colors == 0] = UNKNOWN
            floors[z] = (min_x, min_y, colors, flags)
        return cls(floors)

    def tile(self, x, y, z):
        """Return (color, flags) of one world tile, or None outside the file."""
        floor = self.floors.get(z)
        if floor is None:
            return None
        origin_x, origin_y, colors, flags = floor
        row, col = y - origin_y, x - origin_x
        if not (0 <= row < colors.shape[0] and 0 <= col < colors.shape[1]):
            return None
        return int(colors[row, col]), int(flags[row, col])

    def is_walkable(self, x, y, z):
        tile = self.tile(x, y, z)
        return tile is not None and bool(tile[1] & FLAG_SEEN) and not tile[1] & FLAG_NOT_WALKABLE

    def color_counts(self, z):
        import numpy

        if z not in self._color_counts:
            self._color_counts[z] = numpy.bincount(
                self.floors[z][2].ravel(), minlength=256
            )
        return self._color_counts[z]

    def color_positions(self, z, color):
        import numpy

        key = (z, color)
        if key not in self._color_positions:
            rows, cols = numpy.nonzero(self.floors[z][2] == color)
            self._color_positions[key] = (rows.astype(numpy.int32), cols.astype(numpy.int32))
        return self._color_positions[key]


def palette_index_image(image_bgr):
    """Map every captured pixel to a palette color index, UNKNOWN when off-palette."""
    import numpy

    rgb = image_bgr[:, :, 2::-1].astype(numpy.int16)
    steps = numpy.rint(rgb / PALETTE_STEP).astype(numpy.int16)
    exact = numpy.all(numpy.abs(rgb - steps * PALETTE_STEP) <= PALETTE_TOLERANCE, axis=2)
    index = (steps[:, :, 0] * 36 + steps[:, :, 1] * 6 + steps[:, :, 2]).astype(numpy.uint8)
    index[~exact] = UNKNOWN
    index[index == 0] = UNKNOWN
    return index


def detect_scale(index, max_scale=40, min_boundaries=30, min_concentration=0.85):
    """Return (pixels_per_tile, phase_x, phase_y, concentration) or None.

    Every color change on the minimap happens on a tile edge, so for the real
    tile size nearly all edges share one remainder modulo that size. Smaller
    divisors also pass the test, therefore the largest passing size wins.
    """
    import numpy

    known_x = (index[:, :-1] != UNKNOWN) & (index[:, 1:] != UNKNOWN)
    known_y = (index[:-1, :] != UNKNOWN) & (index[1:, :] != UNKNOWN)
    edges_x = numpy.nonzero(known_x & (index[:, :-1] != index[:, 1:]))[1] + 1
    edges_y = numpy.nonzero(known_y & (index[:-1, :] != index[1:, :]))[0] + 1
    total = len(edges_x) + len(edges_y)
    if total < min_boundaries:
        return None
    best = None
    for scale in range(1, max_scale + 1):
        hist_x = numpy.bincount(edges_x % scale, minlength=scale)
        hist_y = numpy.bincount(edges_y % scale, minlength=scale)
        concentration = (hist_x.max() + hist_y.max()) / total
        if concentration >= min_concentration:
            best = (scale, int(hist_x.argmax()), int(hist_y.argmax()), float(concentration))
    return best


def find_otmm_file():
    """Newest .otmm saved by the client, or the bundled map when there is none.

    Klient zapisuje minimapę w %APPDATA%\\Retronic (przy wylogowaniu), więc
    najnowszy plik zawiera też ostatnio odkryte miejsca.
    """
    roots = [Path(os.environ.get("APPDATA", "")) / "Retronic", CLIENT_DIR]
    found = []
    for root in roots:
        if root.is_dir():
            try:
                found.extend(path for path in root.rglob("*.otmm") if path.is_file())
            except OSError:
                pass
    if not found:
        return DEFAULT_OTMM_PATH
    return max(found, key=lambda path: path.stat().st_mtime)


def find_minimap_region(image_bgr, min_size=40):
    """Return (left, top, right, bottom) of the minimap inside a client screenshot.

    Minimapa to jedyny duży obszar złożony z kolorów palety 6 × 6 × 6; mapa gry
    ma tekstury, a panele są ciemnoszare. Zwraca kandydatów od największego.
    """
    import cv2
    import numpy

    # Kandydatów szukamy na obrazie pomniejszonym 4 ×, bo okno klienta ma
    # miliony pikseli; brzegi poprawiamy potem w pełnej rozdzielczości.
    step = 4
    small = palette_index_image(image_bgr[::step, ::step])
    colored = (small != UNKNOWN).astype(numpy.float32)
    density = cv2.boxFilter(colored, -1, (5, 5))
    mask = (density >= 0.6).astype(numpy.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    height, width = image_bgr.shape[:2]
    regions = []
    for label in numpy.argsort(stats[1:, cv2.CC_STAT_AREA])[::-1] + 1:
        left, top, w, h, area = (int(value) for value in stats[label])
        if w * step < min_size or h * step < min_size or area < 0.5 * w * h:
            continue
        # Wycinek z zapasem, żeby rozszerzanie brzegów miało gdzie sięgnąć.
        margin = 24
        x0, y0 = max(0, left * step - margin), max(0, top * step - margin)
        x1 = min(width, (left + w) * step + margin)
        y1 = min(height, (top + h) * step + margin)
        crop = image_bgr[y0:y1, x0:x1, :3]
        # Czarny to pole nieodkryte; należy do minimapy, ale nie do palety.
        like = (palette_index_image(crop) != UNKNOWN) | numpy.all(crop <= PALETTE_TOLERANCE, axis=2)
        l, t, r, b = _refine_region(
            like, left * step - x0, top * step - y0, (left + w) * step - x0, (top + h) * step - y0
        )
        if r - l >= min_size and b - t >= min_size:
            regions.append((x0 + l, y0 + t, x0 + r, y0 + b))
        if len(regions) == 3:
            break
    return _whole_minimap_windows(image_bgr, regions) or regions


def _whole_minimap_windows(image_bgr, blobs):
    """Replace color blobs by the body of the client window that contains them.

    W jaskini minimapa jest prawie cała czarna (pola nieodkryte), więc kolorowa
    plama to tylko kawałek minimapy, a jej środek nie jest postacią. Okno
    klienta (nagłówek z przyciskiem zamykania, ramka, listwa na dole) wyznacza
    cały obszar minimapy bez względu na to, ile na niej widać.
    """
    import cv2

    from .battle_window import find_window_headers, window_bounds

    if not blobs:
        return []
    scale, buttons = find_window_headers(image_bgr)
    if not buttons:
        return []
    gray = cv2.cvtColor(image_bgr[:, :, :3], cv2.COLOR_BGR2GRAY)
    pad = max(1, int(round(2 * scale)))
    windows = []
    for left, top, right, bottom in blobs:
        cx, cy = (left + right) // 2, (top + bottom) // 2
        for button in buttons:
            bounds = window_bounds(gray, button, scale)
            if bounds is None:
                continue
            w_left, _w_top, w_right, header_bottom, w_bottom = bounds
            if w_left <= cx < w_right and header_bottom <= cy < w_bottom:
                region = (w_left + pad, header_bottom + pad, w_right - pad, w_bottom)
                if region not in windows:
                    windows.append(region)
                break
    return windows


def _refine_region(like, left, top, right, bottom, min_fill=0.85):
    """Move each edge to the border where minimap-like pixels end."""
    height, width = like.shape
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)

    def column(x):
        return like[top:bottom, x].mean()

    def row(y):
        return like[y, left:right].mean()

    # Najpierw zwężamy brzegi, które zahaczyły o ramkę, potem rozszerzamy na
    # czarne (nieodkryte) pasy przy krawędzi minimapy.
    while right - left > 10 and column(left) < min_fill:
        left += 1
    while right - left > 10 and column(right - 1) < min_fill:
        right -= 1
    while bottom - top > 10 and row(top) < min_fill:
        top += 1
    while bottom - top > 10 and row(bottom - 1) < min_fill:
        bottom -= 1
    for _ in range(2):
        while left > 0 and column(left - 1) >= min_fill:
            left -= 1
        while right < width and column(right) >= min_fill:
            right += 1
        while top > 0 and row(top - 1) >= min_fill:
            top -= 1
        while bottom < height and row(bottom) >= min_fill:
            bottom += 1
    return int(left), int(top), int(right), int(bottom)


def find_player_cross(image_bgr, search=14):
    """Pixel center of the white player cross near the middle of the minimap, or None."""
    import cv2
    import numpy

    height, width = image_bgr.shape[:2]
    cx, cy = width // 2, height // 2
    x0, y0 = max(0, cx - search), max(0, cy - search)
    window = image_bgr[y0:cy + search + 1, x0:cx + search + 1, :3]
    white = numpy.all(window >= 240, axis=2).astype(numpy.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(white, connectivity=4)
    best = None
    for label in range(1, count):
        left, top, w, h, area = stats[label]
        # Krzyżyk: kwadratowa ramka 5–21 px wypełniona w 25–70%, w odróżnieniu
        # od pełnych pól śniegu.
        if not (5 <= w <= 21 and 5 <= h <= 21 and abs(w - h) <= 2):
            continue
        if not 0.25 <= area / (w * h) <= 0.7:
            continue
        # Klient rysuje krzyżyk na środku pola postaci. Przy parzystej szerokości
        # (np. 10 px) środek wypada między pikselami, a w // 2 trafiałoby przy
        # skali 1 px na pole w pole obok — pozycja wychodziła o (1, 1) za daleko.
        center = (x0 + left + (w - 1) // 2, y0 + top + (h - 1) // 2)
        distance = abs(center[0] - cx) + abs(center[1] - cy)
        if best is None or distance < best[0]:
            best = (distance, center)
    return best[1] if best else None


def extract_tile_grid(index, scale, phase_x, phase_y, offset=(0, 0), center_px=None):
    """Return (grid of tile colors, (center_col, center_row)) for the player tile."""
    import numpy

    height, width = index.shape
    center_x, center_y = center_px if center_px else (width // 2, height // 2)
    # Pierwsze pełne pole zaczyna się na pozycji phase; niepełne brzegi pomijamy.
    rows = (height - phase_y) // scale
    cols = (width - phase_x) // scale
    if rows < 3 or cols < 3:
        raise RuntimeError("Obszar minimapy jest za mały dla wykrytej skali.")
    blocks = index[
        phase_y:phase_y + rows * scale, phase_x:phase_x + cols * scale
    ].reshape(rows, scale, cols, scale)
    first = blocks[:, 0, :, 0]
    uniform = numpy.all(blocks == first[:, None, :, None], axis=(1, 3))
    grid = numpy.where(uniform, first, UNKNOWN).astype(numpy.uint8)
    # Minimapa jest wyśrodkowana na postaci; offset pozwala skorygować o pole.
    center_col = (center_x - phase_x) // scale + offset[0]
    center_row = (center_y - phase_y) // scale + offset[1]
    # Krzyżyk postaci jest biały, czyli ma kolor śniegu z palety; maskujemy go.
    radius = max(1, -(-6 // scale))
    grid[
        max(0, center_row - radius):center_row + radius + 1,
        max(0, center_col - radius):center_col + radius + 1,
    ] = UNKNOWN
    return grid, (center_col, center_row)


def _score_offsets(colors, sample_rows, sample_cols, values, offset_rows, offset_cols):
    """Fraction of sampled grid cells matching the map for every candidate offset."""
    import numpy

    height, width = colors.shape
    scores = numpy.empty(len(offset_rows), dtype=numpy.float32)
    chunk = max(1, 4_000_000 // max(1, len(values)))
    for start in range(0, len(offset_rows), chunk):
        rows = offset_rows[start:start + chunk, None] + sample_rows[None, :]
        cols = offset_cols[start:start + chunk, None] + sample_cols[None, :]
        inside = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
        found = colors[numpy.clip(rows, 0, height - 1), numpy.clip(cols, 0, width - 1)]
        scores[start:start + chunk] = ((found == values[None, :]) & inside).mean(axis=1)
    return scores


class MinimapLocator:
    """Find the grid on the map: locally around the last position, else globally."""

    def __init__(self, otmm_map, min_score=0.85, min_margin=0.05, max_samples=400):
        self.map = otmm_map
        self.min_score = min_score
        self.min_margin = min_margin
        self.max_samples = max_samples

    def locate(self, grid, center, hint=None, radius=12):
        import numpy

        started = time.perf_counter()
        rows, cols = numpy.nonzero(grid != UNKNOWN)
        if len(rows) < 30:
            return self._result(False, reason="Za mało rozpoznanych pól na minimapie.",
                                known=len(rows), started=started)
        if len(rows) > self.max_samples:
            pick = numpy.linspace(0, len(rows) - 1, self.max_samples).astype(int)
            rows, cols = rows[pick], cols[pick]
        values = grid[rows, cols]
        rows = rows.astype(numpy.int32)
        cols = cols.astype(numpy.int32)

        candidates = []
        if hint is not None:
            hint_x, hint_y, hint_z = hint
            # Zwykle postać jest na tym samym piętrze; sąsiednie (schody, drabiny,
            # czasem z przesunięciem o pole) sprawdzamy dopiero, gdy ono nie pasuje.
            if hint_z in self.map.floors:
                candidates = self._local(hint_z, hint_x, hint_y, center, rows, cols, values, radius)
                result = self._pick(list(candidates), center, len(rows), started)
                if result.ok and result.score >= 0.95:
                    return result
            for z in (hint_z - 1, hint_z + 1, hint_z - 2, hint_z + 2):
                if z in self.map.floors:
                    candidates.extend(self._local(z, hint_x, hint_y, center, rows, cols, values, radius))
            result = self._pick(candidates, center, len(rows), started)
            if result.ok:
                return result
            candidates = []
        preferred = hint[2] if hint else 7
        floors = sorted(self.map.floors, key=lambda z: (abs(z - preferred), z))
        for z in floors:
            candidates.extend(self._global(z, rows, cols, values))
            # Pełne przeszukanie wszystkich pięter trwa kilka sekund; przerywamy,
            # gdy któreś piętro dało niemal idealne i wyraźnie jedyne trafienie.
            result = self._pick(list(candidates), center, len(rows), started)
            if result.ok and result.score >= 0.97 and result.score - result.second_score >= 0.15:
                return result
        return self._pick(candidates, center, len(rows), started)

    def _local(self, z, x, y, center, rows, cols, values, radius):
        import numpy

        origin_x, origin_y, colors, _flags = self.map.floors[z]
        base_col = x - origin_x - center[0]
        base_row = y - origin_y - center[1]
        span = numpy.arange(-radius, radius + 1, dtype=numpy.int32)
        offset_rows, offset_cols = numpy.meshgrid(base_row + span, base_col + span, indexing="ij")
        offset_rows, offset_cols = offset_rows.ravel(), offset_cols.ravel()
        scores = _score_offsets(colors, rows, cols, values, offset_rows, offset_cols)
        return self._top(z, scores, offset_rows, offset_cols)

    def _global(self, z, rows, cols, values):
        import numpy

        _origin_x, _origin_y, colors, _flags = self.map.floors[z]
        counts = self.map.color_counts(z)
        # Kotwice: pola o najrzadszych kolorach dają najmniej kandydatów.
        # Kilka różnych kotwic chroni przed jednym błędnie odczytanym polem.
        # Kolejne kotwice dodajemy tylko, dopóki liczba kandydatów jest rozsądna,
        # bo pole w popularnym kolorze (trawa) dałoby setki tysięcy pozycji.
        order = numpy.argsort(counts[values], kind="stable")
        anchors, used, total = [], set(), 0
        for index in order:
            color = int(values[index])
            count = int(counts[color])
            if count == 0 or color in used:
                continue
            if anchors and total + count > 150_000:
                break
            anchors.append(index)
            used.add(color)
            total += count
            if len(anchors) == 3:
                break
        if not anchors:
            return []
        # Przesunięcia mogą być ujemne przy brzegu mapy; do usuwania duplikatów
        # kodujemy je jako jedną liczbę z zapasem SHIFT w obu osiach.
        shift = 1024
        stride = colors.shape[1] + 2 * shift
        keys = []
        for index in anchors:
            map_rows, map_cols = self.map.color_positions(z, int(values[index]))
            keys.append((map_rows - rows[index] + shift).astype(numpy.int64) * stride
                        + (map_cols - cols[index] + shift))
        keys = numpy.unique(numpy.concatenate(keys))
        offset_rows = (keys // stride - shift).astype(numpy.int32)
        offset_cols = (keys % stride - shift).astype(numpy.int32)
        # Szybkie sito na 16 polach odrzuca prawie wszystkich kandydatów,
        # zanim policzymy pełne dopasowanie.
        if len(offset_rows) > 2000 and len(values) > 32:
            probe = numpy.linspace(0, len(values) - 1, 16).astype(int)
            rough = _score_offsets(colors, rows[probe], cols[probe], values[probe],
                                   offset_rows, offset_cols)
            keep = rough >= 0.6
            offset_rows, offset_cols = offset_rows[keep], offset_cols[keep]
        scores = _score_offsets(colors, rows, cols, values, offset_rows, offset_cols)
        return self._top(z, scores, offset_rows, offset_cols)

    @staticmethod
    def _top(z, scores, offset_rows, offset_cols, keep=5):
        import numpy

        if len(scores) == 0:
            return []
        best = numpy.argsort(scores)[::-1][:keep]
        return [(float(scores[i]), z, int(offset_rows[i]), int(offset_cols[i])) for i in best]

    def _pick(self, candidates, center, known, started):
        if not candidates:
            return self._result(False, reason="Nie znaleziono pasującego miejsca na mapie.",
                                known=known, started=started)
        candidates.sort(reverse=True)
        score, z, offset_row, offset_col = candidates[0]
        # Drugi kandydat liczy się tylko, gdy wskazuje inne miejsce (nie sąsiednie pole).
        second = next(
            (item[0] for item in candidates[1:]
             if item[1] != z or abs(item[2] - offset_row) > 1 or abs(item[3] - offset_col) > 1),
            0.0,
        )
        origin_x, origin_y, _colors, _flags = self.map.floors[z]
        x = int(origin_x + offset_col + center[0])
        y = int(origin_y + offset_row + center[1])
        if score < self.min_score:
            reason = f"Najlepsze dopasowanie {score:.2f} jest poniżej progu {self.min_score:.2f}."
            return self._result(False, x, y, z, score, second, known, reason, started)
        if score - second < self.min_margin:
            reason = "Widok pasuje do kilku miejsc; poczekaj na bardziej charakterystyczny fragment."
            return self._result(False, x, y, z, score, second, known, reason, started)
        return self._result(True, x, y, z, score, second, known, None, started)

    @staticmethod
    def _result(ok, x=None, y=None, z=None, score=0.0, second=0.0, known=0,
                reason=None, started=None):
        elapsed = (time.perf_counter() - started) * 1000 if started else 0.0
        return MinimapMatch(ok, x, y, z, score, second, known, reason, elapsed)


class MinimapTracker:
    """Keep the detected scale and the last position between screenshots."""

    def __init__(self, otmm_map, offset=(0, 0)):
        self.locator = MinimapLocator(otmm_map)
        self.offset = offset
        self.scale = None
        self.phase = None
        self.last_position = None
        self.player_pixel = None
        self.view_size = None

    def reset(self):
        self.scale = None
        self.phase = None
        self.last_position = None

    def update(self, image_bgr):
        center_px = find_player_cross(image_bgr)
        index = palette_index_image(image_bgr)
        detected = detect_scale(index)
        if detected is not None:
            scale, phase_x, phase_y, _concentration = detected
            if self.scale is None or scale >= 2:
                self.scale = scale
                self.phase = (phase_x, phase_y)
        if self.scale is None:
            return MinimapMatch(
                False, None, None, None, 0.0, 0.0, 0,
                "Nie rozpoznano siatki pól na minimapie.", 0.0,
            )
        grid, center = extract_tile_grid(
            index, self.scale, *self.phase, offset=self.offset, center_px=center_px
        )
        result = self.locator.locate(grid, center, hint=self.last_position)
        if result.ok:
            self.last_position = (result.x, result.y, result.z)
            # Środek pola postaci na zrzucie; cavebot liczy od niego miejsca kliknięć.
            self.player_pixel = (
                self.phase[0] + (center[0] - self.offset[0]) * self.scale + self.scale // 2,
                self.phase[1] + (center[1] - self.offset[1]) * self.scale + self.scale // 2,
            )
            if center_px is not None and self.offset == (0, 0):
                # Krzyżyk jest rysowany dokładnie na środku pola postaci.
                self.player_pixel = (int(center_px[0]), int(center_px[1]))
            self.view_size = (image_bgr.shape[1], image_bgr.shape[0])
        return result
