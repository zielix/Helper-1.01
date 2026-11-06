"""Automatyczne znalezienie okna Battle na zrzucie całego klienta.

Każde małe okno klienta (Minimap, Skills, Battle…) ma taki sam nagłówek:
jasną linię na całą szerokość okna i przycisk zamykania po prawej. Bot
znajduje te przyciski (wzorzec z nagłówka minimapy, w każdej skali), odczyta
tytuł każdego nagłówka przez Tesseract OCR i wybiera okno „Battle”. Dół okna
wyznacza listwa zmiany rozmiaru (dwie jasne linie na całą szerokość).
"""

import csv
import subprocess
from pathlib import Path


CLOSE_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "window_close.png"
# Szarość linii ramek okien klienta (nagłówek i listwa na dole).
FRAME_GRAY = (44, 58)
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)


def _close_template():
    import cv2

    template = cv2.imread(str(CLOSE_TEMPLATE_PATH), cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise RuntimeError("Brak pliku wzorca assets/window_close.png.")
    return template


def find_window_headers(image_bgr, threshold=0.82, scale_hint=None, columns=None):
    """Return (scale, [(x, y, w, h) of close buttons]) for all mini-windows.

    columns — lista zakresów (x0, x1), w których szukać (np. panele po bokach
    mapy gry). Dopasowanie wzorca na całym kliencie trwa na wolniejszym
    komputerze ok. 0,4 s na skalę, a okna leżą tylko w panelach.
    """
    import cv2
    import numpy

    gray = cv2.cvtColor(image_bgr[:, :, :3], cv2.COLOR_BGR2GRAY)
    strips = [(max(0, x0), min(gray.shape[1], x1)) for x0, x1 in (columns or [(0, gray.shape[1])])]
    base = _close_template()
    best = None
    scales = (scale_hint,) if scale_hint is not None else SCALES
    for scale in scales:
        template = cv2.resize(base, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        found = []
        for x0, x1 in strips:
            if template.shape[0] > gray.shape[0] or template.shape[1] > x1 - x0:
                continue
            found.append((x0, cv2.matchTemplate(gray[:, x0:x1], template, cv2.TM_CCOEFF_NORMED)))
        if not found:
            continue
        peak = max(float(scores.max()) for _x0, scores in found)
        if best is None or peak > best[0]:
            best = (peak, scale, found, template.shape)
    if best is None or best[0] < threshold:
        return None, []
    _peak, scale, found, (height, width) = best
    buttons = []
    for x0, scores in found:
        ys, xs = numpy.nonzero(scores >= threshold)
        for i in numpy.argsort(scores[ys, xs])[::-1]:
            x, y = int(xs[i]) + x0, int(ys[i])
            if all(abs(x - bx) > width or abs(y - by) > height for bx, by, _w, _h in buttons):
                buttons.append((x, y, width, height))
    buttons.sort(key=lambda item: (item[0], item[1]))
    return scale, buttons


def _frame_run(gray, y, x):
    """Left and right end of the frame-colored line through (x, y), or None."""
    low, high = FRAME_GRAY
    row = gray[y]
    if not low <= row[x] <= high:
        return None
    left = x
    while left > 0 and low <= row[left - 1] <= high:
        left -= 1
    right = x
    while right + 1 < len(row) and low <= row[right + 1] <= high:
        right += 1
    return left, right + 1


def window_bounds(gray, button, scale):
    """Return (left, top, right, header_bottom, bottom) of the window of a close button."""
    import numpy

    x, y, width, height = button
    center_x = x + width // 2
    header_bottom = y + height

    # Krawędzie okna to pionowe ramki: jasna kolumna (szarość ok. 51) przez
    # cały nagłówek z ciemną kolumną po zewnętrznej stronie. Linie poziome
    # potrafią przechodzić w ramki sąsiednich paneli, więc nie wyznaczają szerokości.
    band = gray[y + max(1, height // 4):header_bottom]
    left = right = None
    if band.size:
        # Cechy wszystkich kolumn naraz (pętla po kolumnach w Pythonie była wolna).
        frame = ((band >= 46) & (band <= 56)).mean(axis=0) >= 0.8
        dark = (band <= 22).mean(axis=0) >= 0.8
        # Lewa krawędź: jasna kolumna z ciemną po lewej, najbliżej przycisku.
        lefts = numpy.nonzero(frame[1:] & dark[:-1])[0] + 1
        lefts = lefts[(lefts > 0) & (lefts <= x - 6 * width)]
        if lefts.size:
            left = int(lefts.max())
        # Prawa krawędź: jasna kolumna z ciemną po prawej, pierwsza za przyciskiem.
        rights = numpy.nonzero(frame[:-1] & dark[1:])[0]
        rights = rights[rights >= x + width]
        if rights.size:
            right = int(rights.min()) + 1
    if left is None or right is None:
        # Zapasowo: koniec jasnej linii na górze nagłówka.
        run = None
        for dy in range(-int(2 * scale) - 1, int(2 * scale) + 2):
            if 0 <= y + dy < gray.shape[0]:
                candidate = _frame_run(gray, y + dy, center_x)
                if candidate and (run is None or candidate[1] - candidate[0] > run[1] - run[0]):
                    run = candidate
        if run is None:
            return None
        left = run[0] if left is None else left
        right = run[1] if right is None else right
    if right - left < 6 * width:
        return None
    inner = gray[:, left + int(4 * scale):right - int(4 * scale)]
    bright = ((inner >= 46) & (inner <= 56)).mean(axis=1) >= 0.85
    dark = (inner <= 20).mean(axis=1) >= 0.85
    # Dół okna: listwa zmiany rozmiaru — ciemna linia, dwie jasne, ciemna
    # (w skali klienta). Paski HP/many mają podobną szarość, ale bez ciemnych linii.
    need = max(2, int(round(2 * scale)))
    bottom = gray.shape[0]
    for row in range(header_bottom + int(4 * scale), gray.shape[0] - need - 1):
        if dark[row - 1] and bright[row:row + need].all() and (
            dark[row + need] or dark[min(row + need + 1, gray.shape[0] - 1)]
        ):
            bottom = row - 1
            break
    return left, y, right, header_bottom, int(bottom)


# Tytuły odczytane przez OCR, według obrazu napisu (po progowaniu). Okna
# panelu (Skills, VIP, plecak, „Dead larva”) mają stałe napisy, więc po
# pierwszym odczycie nie trzeba uruchamiać Tesseract (ok. 1–2 s na okno).
_TITLE_CACHE = {}
_TITLE_CACHE_LIMIT = 256


def read_title(image_bgr, bounds, button, scale, tesseract):
    """OCR the title text of one mini-window header (cached by the title image)."""
    import cv2

    left, top, _right, header_bottom, _bottom = bounds
    x = button[0]
    crop = image_bgr[top:header_bottom, left:x, :3]
    if crop.size == 0:
        return ""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Klucz pamięci: sam napis (jasne piksele), niezależnie od tła nagłówka.
    key = (gray.shape, (gray > 105).tobytes())
    if key in _TITLE_CACHE:
        return _TITLE_CACHE[key]
    # Tytuł to jasny tekst na ciemnym tle; OCR woli ciemny tekst na białym.
    text_height = max(1, header_bottom - top)
    factor = max(1.0, 36 / text_height)
    big = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    binary = cv2.threshold(big, 105, 255, cv2.THRESH_BINARY_INV)[1]
    binary = cv2.copyMakeBorder(binary, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    ok, encoded = cv2.imencode(".png", binary)
    if not ok:
        return ""
    title = _ocr_title(encoded, tesseract)
    if len(_TITLE_CACHE) >= _TITLE_CACHE_LIMIT:
        _TITLE_CACHE.clear()
    _TITLE_CACHE[key] = title
    return title


def read_titles(image_bgr, frames, scale, tesseract):
    """Titles of many frames; uncached ones are read by Tesseract in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    if not frames:
        return []
    with ThreadPoolExecutor(max_workers=min(4, len(frames))) as pool:
        return list(pool.map(lambda frame: frame_title(image_bgr, frame, scale, tesseract), frames))


def _ocr_title(encoded, tesseract):
    result = subprocess.run(
        [tesseract, "stdin", "stdout", "--psm", "7", "tsv"],
        input=encoded.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=5, check=False,
    )
    words = [
        row["text"].strip()
        for row in csv.DictReader(result.stdout.decode("utf-8", "replace").splitlines(), delimiter="\t")
        if row.get("level") == "5" and row.get("text", "").strip()
    ]
    return " ".join(words)


def find_mini_windows(image_bgr, tesseract):
    """Return [(title, (left, top, right, bottom) of the window body)] on screen."""
    import cv2

    scale, buttons = find_window_headers(image_bgr)
    if not buttons:
        return []
    gray = cv2.cvtColor(image_bgr[:, :, :3], cv2.COLOR_BGR2GRAY)
    windows = []
    for button in buttons:
        bounds = window_bounds(gray, button, scale)
        if bounds is None:
            continue
        left, _top, right, header_bottom, bottom = bounds
        title = read_title(image_bgr, bounds, button, scale, tesseract)
        pad = max(1, int(round(2 * scale)))
        windows.append((title, (left + pad, header_bottom, right - pad, bottom)))
    return windows


def panel_columns(image_width, game_view, minimum=40):
    """Column ranges of the side panels left and right of the game view."""
    left, _top, right, _bottom = game_view
    return [(x0, x1) for x0, x1 in ((0, left), (right, image_width)) if x1 - x0 >= minimum]


def find_mini_window_frames(image_bgr, scale_hint=None, columns=None):
    """Return (scale, [frame]) of all mini-windows without title OCR.

    Ramka to słownik: body (prostokąt zawartości), close (środek przycisku X),
    button i bounds (do odczytu tytułu przez frame_title). columns ogranicza
    szukanie do pasków (panel_columns); bez skali sprawdza wszystkie SCALES.
    """
    import cv2

    scale, buttons = find_window_headers(image_bgr, scale_hint=scale_hint, columns=columns)
    if not buttons and scale_hint is not None:
        # Skala klienta się zmieniła (np. inne powiększenie): szukamy od nowa.
        scale, buttons = find_window_headers(image_bgr, columns=columns)
    if not buttons:
        return scale, []
    gray = cv2.cvtColor(image_bgr[:, :, :3], cv2.COLOR_BGR2GRAY)
    windows = []
    for button in buttons:
        bounds = window_bounds(gray, button, scale)
        if bounds is None:
            continue
        left, _top, right, header_bottom, bottom = bounds
        pad = max(1, int(round(2 * scale)))
        windows.append({
            "body": (left + pad, header_bottom, right - pad, bottom),
            "close": (button[0] + button[2] // 2, button[1] + button[3] // 2),
            "button": button,
            "bounds": bounds,
        })
    return scale, windows


def frame_title(image_bgr, frame, scale, tesseract):
    """OCR the title of one frame from find_mini_window_frames."""
    return read_title(image_bgr, frame["bounds"], frame["button"], scale, tesseract)


def find_mini_window_regions(image_bgr, scale_hint=None):
    """Return mini-window body rectangles without the slower title OCR pass."""
    scale, frames = find_mini_window_frames(image_bgr, scale_hint)
    return scale, [frame["body"] for frame in frames]


def find_battle_window(image_bgr, tesseract, title="battle"):
    """Body region of the Battle window, or (None, list of seen titles)."""
    windows = find_mini_windows(image_bgr, tesseract)
    for name, region in windows:
        letters = "".join(char for char in name.lower() if char.isalpha())
        if title in letters:
            return region, [item[0] for item in windows]
    return None, [item[0] for item in windows]
