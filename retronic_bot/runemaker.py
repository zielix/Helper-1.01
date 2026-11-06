"""Mana z okna Health Info i rozpoznawanie przedmiotów w slotach (Runemaker).

Okno Health Info ma czerwony pasek życia i niebieski pasek many z napisem
„aktualna / maksymalna”. Procent many bot liczy z napisu (OCR), a gdy ten
jest nieczytelny — z szerokości niebieskiego wypełnienia względem pełnej
szerokości paska (pasek życia jest zwykle pełny, więc wyznacza ją od razu).
"""

import json
import re
import subprocess
from pathlib import Path


SETTINGS_PATH = Path(__file__).resolve().parent.parent / "automation.json"
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "item_templates"


def load_settings():
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def save_settings(data):
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_template(name, image):
    import cv2

    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMPLATE_DIR / f"{name}.png"
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Nie udało się zapisać wzorca {path.name}.")


def load_template(name):
    import cv2

    return cv2.imread(str(TEMPLATE_DIR / f"{name}.png"), cv2.IMREAD_COLOR)


def _bar_rows(image_bgr, channel):
    """Rows of one colored bar: [(row, fill width)], fill counted from the left edge."""
    import numpy

    pixels = image_bgr[:, :, :3].astype(numpy.int16)
    main = pixels[:, :, channel]
    others = numpy.delete(pixels, channel, axis=2).max(axis=2)
    mask = (main >= 110) & (main - others >= 60)
    rows = []
    for row in numpy.nonzero(mask.sum(axis=1) >= 4)[0]:
        columns = numpy.nonzero(mask[row])[0]
        rows.append((int(row), int(columns[-1] - columns[0] + 1), int(columns[0])))
    return rows


def _ocr_pair(image_bgr):
    """OCR 'current / maximum' from a bar crop; (current, maximum) or None."""
    import cv2
    import numpy
    from .mana import find_tesseract

    pixels = image_bgr[:, :, :3].astype(numpy.int16)
    # Napis jest biały z czarnym obrysem na kolorowym pasku.
    white = (pixels.min(axis=2) >= 190).astype(numpy.uint8) * 255
    if white.sum() == 0:
        return None
    factor = max(3.0, 36 / max(1, white.shape[0]))
    image = cv2.resize(255 - white, None, fx=factor, fy=factor, interpolation=cv2.INTER_NEAREST)
    image = cv2.copyMakeBorder(image, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=255)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        return None
    result = subprocess.run(
        [find_tesseract(), "stdin", "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789/"],
        input=encoded.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3, check=False,
    )
    match = re.search(r"(\d+)\s*/\s*(\d+)", result.stdout.decode("utf-8", errors="replace"))
    if not match:
        return None
    current, maximum = int(match.group(1)), int(match.group(2))
    if maximum <= 0 or current > maximum:
        return None
    return current, maximum


def read_vitals(window_bgr, full_width=0, use_ocr=True):
    """Return {"mana_pct", "mana", "hp_pct", "bar_width"} from a Health Info crop, or None.

    full_width — największa widziana dotąd szerokość wypełnienia paska; bot
    przekazuje ją między odczytami, bo pusta część paska nie ma koloru.
    """
    red = _bar_rows(window_bgr, 2)
    blue = _bar_rows(window_bgr, 0)
    if not blue:
        return None
    # Wiersz bez napisu ma najdłuższe ciągłe wypełnienie; bierzemy maksimum.
    blue_width = max(width for _row, width, _left in blue)
    red_width = max((width for _row, width, _left in red), default=0)
    bar_width = max(full_width, blue_width, red_width)
    result = {"bar_width": bar_width, "mana": None,
              "mana_pct": 100.0 * blue_width / bar_width,
              "hp_pct": 100.0 * red_width / bar_width if red else None}
    if use_ocr:
        top, bottom = blue[0][0], blue[-1][0] + 1
        left = min(start for _row, _width, start in blue)
        crop = window_bgr[top:bottom, left:left + bar_width]
        pair = _ocr_pair(crop)
        if pair:
            result["mana"] = pair
            result["mana_pct"] = 100.0 * pair[0] / pair[1]
    return result


def slot_crop(image_bgr, point, half):
    x, y = point
    return image_bgr[max(0, y - half):y + half, max(0, x - half):x + half]


def similarity(a, b):
    """1.0 for identical crops, lower for different contents (normalized mean abs diff)."""
    import numpy

    if a is None or b is None or a.shape != b.shape or a.size == 0:
        return 0.0
    diff = numpy.abs(a[:, :, :3].astype(numpy.int16) - b[:, :, :3].astype(numpy.int16)).mean()
    return float(max(0.0, 1.0 - diff / 40.0))


def contains(crop, template, threshold=0.8):
    """True when template (an item image) is visible inside crop."""
    import cv2

    if crop is None or template is None:
        return False
    if crop.shape[0] < template.shape[0] or crop.shape[1] < template.shape[1]:
        return False
    scores = cv2.matchTemplate(crop[:, :, :3], template[:, :, :3], cv2.TM_CCOEFF_NORMED)
    return float(scores.max()) >= threshold


def find_item(image_bgr, template, threshold=0.8, regions=None, exclude=()):
    """Best match of an item image on the client screen: (x, y, score) of its center, or None.

    regions — prostokąty (left, top, right, bottom), w których szukać (np.
    panele po bokach mapy gry); exclude — pomijane prostokąty (slot ręki).
    Najpierw szukamy w obrazie pomniejszonym o połowę, potem dokładnie wokół
    najlepszych miejsc — przy skali 200% to kilkanaście razy szybciej.
    """
    import cv2

    if template is None:
        return None
    height, width = template.shape[:2]
    full_h, full_w = image_bgr.shape[:2]
    regions = regions or [(0, 0, full_w, full_h)]
    small_template = cv2.resize(template[:, :, :3], None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    best = None
    for left, top, right, bottom in regions:
        left, top = max(0, int(left)), max(0, int(top))
        right, bottom = min(full_w, int(right)), min(full_h, int(bottom))
        if right - left < width or bottom - top < height:
            continue
        area = image_bgr[top:bottom, left:right, :3]
        small = cv2.resize(area, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        if small.shape[0] < small_template.shape[0] or small.shape[1] < small_template.shape[1]:
            continue
        coarse = cv2.matchTemplate(small, small_template, cv2.TM_CCOEFF_NORMED)
        for _ in range(4):
            _low, score, _low_at, (cx, cy) = cv2.minMaxLoc(coarse)
            if score < threshold - 0.25:
                break
            coarse[max(0, cy - 4):cy + 5, max(0, cx - 4):cx + 5] = -1.0
            # Dokładne dopasowanie w pełnej rozdzielczości wokół kandydata.
            x0, y0 = max(0, cx * 2 - 6), max(0, cy * 2 - 6)
            window = area[y0:y0 + height + 12, x0:x0 + width + 12]
            if window.shape[0] < height or window.shape[1] < width:
                continue
            fine = cv2.matchTemplate(window, template[:, :, :3], cv2.TM_CCOEFF_NORMED)
            _low, value, _low_at, (fx, fy) = cv2.minMaxLoc(fine)
            x, y = left + x0 + fx + width // 2, top + y0 + fy + height // 2
            if any(ex_l <= x < ex_r and ex_t <= y < ex_b for ex_l, ex_t, ex_r, ex_b in exclude):
                continue
            if value >= threshold and (best is None or value > best[2]):
                best = (int(x), int(y), float(value))
    return best
