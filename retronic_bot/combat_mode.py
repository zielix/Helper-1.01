"""Tryb walki klienta (Stand / Chase) z przycisków w oknie Inventory.

W oknie Inventory klient ma przyciski trybów walki; w prawej kolumnie są
„Stand while fighting” (stojąca postać) i „Chase opponent” (strzałki ↔).
Wybrany tryb ma kolorową ikonę, niewybrany szarą, więc bot znajduje oba
przyciski wzorcem (w każdej skali) i odczytuje stan po nasyceniu kolorów.
"""

from pathlib import Path


ASSETS = Path(__file__).resolve().parent / "assets"
MODES = {"chase": "Goń", "stand": "Stój"}
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)


def _template(name):
    import cv2

    image = cv2.imread(str(ASSETS / f"combat_{name}.png"), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"Brak wzorca assets/combat_{name}.png.")
    return image


def find_combat_buttons(image_bgr, threshold=0.6):
    """Return {"stand": (x, y, w, h), "chase": (x, y, w, h)} in image coordinates, or None.

    Przycisk Stand leży tuż nad Chase w tej samej kolumnie; ten układ odróżnia
    je od przypadkowo podobnych fragmentów ekranu.
    """
    import cv2

    gray = cv2.cvtColor(image_bgr[:, :, :3], cv2.COLOR_BGR2GRAY)
    stand_base, chase_base = _template("stand"), _template("chase")
    best = None
    for scale in SCALES:
        stand = cv2.resize(stand_base, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        chase = cv2.resize(chase_base, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        if chase.shape[0] > gray.shape[0] or chase.shape[1] > gray.shape[1]:
            continue
        chase_scores = cv2.matchTemplate(gray, chase, cv2.TM_CCOEFF_NORMED)
        _low, chase_peak, _low_at, (cx, cy) = cv2.minMaxLoc(chase_scores)
        if chase_peak < threshold:
            continue
        # Stand szukamy tylko bezpośrednio nad znalezionym Chase.
        top = max(0, cy - int(32 * scale))
        bottom = max(top + stand.shape[0] + 1, cy - int(8 * scale) + stand.shape[0])
        left = max(0, cx - int(4 * scale))
        right = min(gray.shape[1], cx + chase.shape[1] + int(4 * scale))
        window = gray[top:bottom, left:right]
        if window.shape[0] < stand.shape[0] or window.shape[1] < stand.shape[1]:
            continue
        stand_scores = cv2.matchTemplate(window, stand, cv2.TM_CCOEFF_NORMED)
        _low, stand_peak, _low_at, (sx, sy) = cv2.minMaxLoc(stand_scores)
        if stand_peak < threshold:
            continue
        score = chase_peak + stand_peak
        if best is None or score > best[0]:
            height, width = chase.shape
            best = (score, {
                "stand": (left + sx, top + sy, width, height),
                "chase": (cx, cy, width, height),
            })
    return best[1] if best else None


def button_active(image_bgr, box):
    """True when the icon in box is colored (selected), False when it is grey."""
    import numpy

    x, y, width, height = box
    pixels = image_bgr[y:y + height, x:x + width, :3].astype(numpy.int16)
    if pixels.size == 0:
        return False
    saturation = pixels.max(axis=2) - pixels.min(axis=2)
    return float((saturation >= 35).mean()) >= 0.12


def current_mode(image_bgr, buttons):
    """'chase', 'stand' or None when neither (or both) looks selected."""
    chase = button_active(image_bgr, buttons["chase"])
    stand = button_active(image_bgr, buttons["stand"])
    if chase and not stand:
        return "chase"
    if stand and not chase:
        return "stand"
    return None
