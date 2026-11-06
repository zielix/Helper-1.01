"""Capture, compare, and recognize a configured Battle-list area."""

import csv
import subprocess


def capture_region(target_pid, region, grayscale=True, label=None):
    """Capture a client-relative region; return None unless the game is foreground."""
    from .mouse import foreground_client_bounds

    bounds = foreground_client_bounds(target_pid)
    if bounds is None:
        return None
    origin_x, origin_y, client_width, client_height = bounds
    left, top, right, bottom = region
    if left < 0 or top < 0 or right > client_width or bottom > client_height:
        label = label or ("Battle" if grayscale else "many")
        raise RuntimeError(f"Zaznaczony obszar {label} znajduje się poza oknem gry.")
    width, height = right - left, bottom - top
    minimum_width, minimum_height = (20, 20) if grayscale else (8, 6)
    if width < minimum_width or height < minimum_height:
        if label:
            raise RuntimeError(f"Zaznacz większy obszar {label} (minimum {minimum_width} × {minimum_height} pikseli).")
        if grayscale:
            raise RuntimeError("Zaznacz większy obszar listy Battle.")
        raise RuntimeError("Zaznacz większy obszar tekstu many (minimum 8 × 6 pikseli).")

    try:
        import cv2
        import mss
        import numpy
    except ImportError as exc:
        raise RuntimeError(
            "Przechwytywanie obrazu wymaga pakietów mss, opencv-python i numpy. "
            "Zainstaluj je poleceniem: py -3.14 -m pip install mss opencv-python numpy"
        ) from exc

    box = {
        "left": origin_x + left,
        "top": origin_y + top,
        "width": width,
        "height": height,
    }
    with mss.mss() as capture:
        pixels = numpy.asarray(capture.grab(box))
    if grayscale:
        return cv2.cvtColor(pixels, cv2.COLOR_BGRA2GRAY)
    return pixels


def differs_from_empty(frame, empty_frame, threshold=0.002):
    """Return whether enough pixels differ from the empty-list reference image."""
    import cv2
    import numpy

    difference = cv2.absdiff(frame, empty_frame)
    _, changed = cv2.threshold(difference, 32, 255, cv2.THRESH_BINARY)
    return numpy.count_nonzero(changed) / changed.size >= threshold


def find_battle_templates(target_pid, region, row_height, templates, threshold=0.72):
    """Search the full Battle area for saved name crops.

    Return row index, name, text-center x/y, and match score. Detection uses
    actual match coordinates rather than slicing the image into assumed rows.
    """
    frame = capture_region(target_pid, region, grayscale=False)
    if frame is None:
        return None

    import cv2
    import numpy

    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
    detections = []
    for name, template in templates.items():
        if template is None or template.size == 0:
            continue
        template_height, template_width = template.shape[:2]
        if template_height > gray.shape[0] or template_width > gray.shape[1]:
            continue
        max_matches = max(1, gray.shape[0] // max(1, template_height // 2))
        for candidate in (template, cv2.bitwise_not(template)):
            scores = cv2.matchTemplate(gray, candidate, cv2.TM_CCOEFF_NORMED)
            scores = scores.copy()
            for _ in range(max_matches):
                _minimum, maximum, _min_location, location = cv2.minMaxLoc(scores)
                if maximum < threshold:
                    break
                x, y = location
                center_x = x + template_width // 2
                center_y = y + template_height // 2
                detections.append((maximum, name, center_x, center_y, template_height))
                # Suppress this text and near-identical overlapping matches,
                # while leaving the next Battle row available for detection.
                x1 = max(0, x - template_width // 2)
                x2 = min(scores.shape[1], x + template_width + template_width // 2)
                y1 = max(0, y - template_height // 2)
                y2 = min(scores.shape[0], y + template_height + template_height // 2)
                scores[y1:y2, x1:x2] = -1.0

    # A normal and an inverted template can both match the same row. Keep the
    # strongest candidate at each text baseline, but retain separate rows.
    detections.sort(key=lambda item: item[0], reverse=True)
    unique = []
    for score, name, x, y, height in detections:
        if any(abs(y - existing[3]) < max(4, min(height, existing[4]) // 2)
               for existing in unique):
            continue
        unique.append((score, name, x, y, height))
    unique.sort(key=lambda item: item[3])
    return [
        (max(0, int(y // row_height)), name, x, y, float(score))
        for score, name, x, y, _height in unique
    ]


def read_battle_names(target_pid, region, row_height):
    """Read names by row, returning row index, name, text-center x/y."""
    frame = capture_region(target_pid, region, grayscale=False)
    if frame is None:
        return None

    import cv2
    import numpy
    from .mana import find_tesseract

    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
    enlarged = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if numpy.count_nonzero(binary) < binary.size // 2:
        binary = cv2.bitwise_not(binary)
    success, encoded = cv2.imencode(".png", binary)
    if not success:
        raise RuntimeError("Nie udało się przygotować obrazu Battle do OCR.")

    result = subprocess.run(
        [find_tesseract(), "stdin", "stdout", "--psm", "6", "tsv"],
        input=encoded.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=3, check=False,
    )
    if result.returncode != 0:
        details = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(details or "Tesseract OCR nie odczytał listy Battle.")
    grouped = {}
    reader = csv.DictReader(
        result.stdout.decode("utf-8", errors="replace").splitlines(), delimiter="\t"
    )
    for word in reader:
        if word.get("level") != "5" or not word.get("text", "").strip():
            continue
        try:
            confidence = float(word["conf"])
            top = int(word["top"])
            height = int(word["height"])
            width = int(word["width"])
            left = int(word["left"])
        except (KeyError, TypeError, ValueError):
            continue
        if confidence < 0 or height <= 0:
            continue
        source_y = (top + height / 2) / 3
        if source_y < 0 or source_y >= frame.shape[0]:
            continue
        row_index = int(source_y // row_height)
        grouped.setdefault(row_index, []).append(
            (left, left + width, word["text"].strip(), top, height)
        )

    return [
        (
            row_index,
            " ".join(text for _left, _right, text, _top, _height in sorted(words)),
            (min(left for left, _right, _text, _top, _height in words)
             + max(right for _left, right, _text, _top, _height in words)) // 6,
            int(sum((top + height / 2) / 3 for _left, _right, _text, top, height in words) / len(words)),
        )
        for row_index, words in sorted(grouped.items())
    ]


def attack_marker_pixels(frame):
    """Count pure-red pixels: the client frames and colors the attacked creature red.

    Czerwone paski życia (191, 10, 10) są ciemniejsze niż czysta czerwień
    ramki celu (255, 0, 0), więc nie są liczone.
    """
    import numpy

    pixels = frame[:, :, :3].astype(numpy.int16)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    return int(((red >= 225) & (green <= 70) & (blue <= 70)).sum())


def _text_mask(frame):
    """Light, unsaturated pixels — the color of creature names in Battle."""
    import numpy

    pixels = frame[:, :, :3].astype(numpy.int16)
    low = pixels.min(axis=2)
    high = pixels.max(axis=2)
    return (low >= 120) & (high - low <= 55)


def _health_bars(frame):
    """Return [(top, bottom, left, right)] of health bars (long saturated strips)."""
    import numpy

    pixels = frame[:, :, :3].astype(numpy.int16)
    high = pixels.max(axis=2)
    low = pixels.min(axis=2)
    colored = (high >= 90) & (high - low >= 80)
    width = frame.shape[1]
    rows = numpy.nonzero(colored.sum(axis=1) >= max(8, width // 5))[0]
    bars = []
    if len(rows) == 0:
        return bars
    start = previous = rows[0]
    for row in list(rows[1:]) + [None]:
        if row is not None and row - previous <= 1:
            previous = row
            continue
        columns = numpy.nonzero(colored[start:previous + 1].any(axis=0))[0]
        bars.append((int(start), int(previous), int(columns[0]), int(columns[-1])))
        if row is not None:
            start = previous = row
    return bars


def extract_battle_name(frame, click_x, click_y):
    """Return (left, top, right, bottom) of the name in the clicked Battle row, or None.

    Wiersz Battle to: obrazek postaci, nazwa i pod nią pasek życia, który
    zaczyna się tam, gdzie nazwa. Pasek jest kotwicą: bierzemy najbliższy pasek
    na wysokości kliknięcia lub pod nim i wycinamy jasny tekst tuż nad nim, w
    jego zakresie poziomym. Obrazek postaci (także z białą ramką podświetlenia
    pod kursorem) leży na lewo od paska, więc nie trafia do wzorca.
    """
    import numpy

    bars = _health_bars(frame)
    if not bars:
        return None
    below = [bar for bar in bars if bar[1] >= click_y - 2]
    bar_top, bar_bottom, bar_left, bar_right = min(below or bars[-1:], key=lambda bar: bar[0])
    index = bars.index((bar_top, bar_bottom, bar_left, bar_right))
    ceiling = bars[index - 1][1] + 1 if index > 0 else 0
    bar_height = bar_bottom - bar_top + 1
    margin = max(2, bar_height)
    left = max(0, bar_left - margin)
    right = min(frame.shape[1], bar_right + 1)
    mask = _text_mask(frame[ceiling:bar_top, left:right])
    rows = numpy.nonzero(mask.any(axis=1))[0]
    if len(rows) == 0:
        return None
    # Pasmo tekstu bezpośrednio nad paskiem (od dołu do pierwszej przerwy).
    bottom = rows[-1]
    top = bottom
    for row in rows[::-1]:
        if top - row > 2:
            break
        top = row
    if bottom - top < 3:
        return None
    columns = numpy.nonzero(mask[top:bottom + 1].any(axis=0))[0]
    pad = 1
    return (
        int(left + max(0, columns[0] - pad)),
        int(ceiling + max(0, top - pad)),
        int(min(frame.shape[1], left + columns[-1] + pad + 1)),
        int(ceiling + bottom + pad + 1),
    )


def read_name_crop(crop):
    """OCR one cropped creature name; empty string when unreadable."""
    import cv2
    import numpy
    from .mana import find_tesseract

    # Powiększenie w odcieniach szarości (litery ok. 40 px) i próg Otsu dają
    # ciemny tekst na białym tle, który Tesseract czyta najpewniej.
    gray = cv2.cvtColor(crop[:, :, :3], cv2.COLOR_BGR2GRAY)
    factor = max(4.0, 40 / max(1, gray.shape[0]))
    image = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    image = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    image = cv2.copyMakeBorder(image, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        return ""
    result = subprocess.run(
        [find_tesseract(), "stdin", "stdout", "--psm", "7"],
        input=encoded.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=5, check=False,
    )
    text = result.stdout.decode("utf-8", errors="replace")
    words = ["".join(char for char in word if char.isalpha() or char in "'-") for word in text.split()]
    return " ".join(word.capitalize() for word in words if word)


def parse_battle_rows(frame):
    """Return Battle rows from one capture, top to bottom.

    Każdy wiersz: {"y": środek paska życia, "top": górna granica wiersza
    (pod paskiem poprzedniego), "hp": 0–100, "attacked": czerwona ramka celu}.
    Wiersz wyznacza pasek życia (czarna ramka i wypełnienie), więc odczyt
    działa także dla potworów z prawie pustym paskiem.
    """
    import numpy
    from .creatures import find_health_bars

    pixels = frame[:, :, :3]
    red = (pixels[:, :, 2] >= 225) & (pixels[:, :, 1] <= 70) & (pixels[:, :, 0] <= 70)
    bars = sorted(find_health_bars(frame), key=lambda bar: bar["y"])
    rows = []
    previous = 0
    for bar in bars:
        bottom = int(bar["y"]) + 4
        rows.append({
            "y": int(bar["y"]),
            "top": previous,
            "hp": bar["hp"],
            "attacked": False,
            "name": None,
            "text_x": None,
            "text_y": None,
        })
        previous = bottom
    # Czerwona ramka obrazka i nazwa celu wystają poza pasmo wiersza, więc
    # atakowany jest jeden wiersz: ten, w którego paśmie leży środek czerwieni.
    red_y = numpy.nonzero(red)[0]
    if rows and len(red_y) >= 6:
        center = float(numpy.median(red_y))
        inside = [row for row in rows if row["top"] <= center <= row["y"] + 4]
        target = inside[0] if inside else min(rows, key=lambda row: abs(row["y"] - center))
        target["attacked"] = True
    return rows


def assign_row_names(rows, recognized):
    """Attach names from template/OCR hits (row, name, text_x, text_y) to parsed rows."""
    for _row_index, name, text_x, text_y in recognized or []:
        for row in rows:
            if row["top"] <= text_y <= row["y"]:
                if row["name"] is None:
                    row.update(name=name, text_x=text_x, text_y=text_y)
                break
    return rows
