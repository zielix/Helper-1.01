"""Wyszukiwanie amunicji (kamienie, spiry) na ziemi wokół postaci."""

import hashlib
import json
from pathlib import Path

from .battle import capture_region


PICKUP_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "pickup_templates"
PICKUP_TEMPLATE_MANIFEST = PICKUP_TEMPLATE_DIR / "templates.json"


def load_pickup_templates():
    """Return {name: BGR image} for the saved ground-item crops."""
    if not PICKUP_TEMPLATE_MANIFEST.exists():
        return {}
    try:
        import cv2

        entries = json.loads(PICKUP_TEMPLATE_MANIFEST.read_text(encoding="utf-8"))
        result = {}
        for name, filename in entries.items():
            image = cv2.imread(
                str(PICKUP_TEMPLATE_DIR / Path(filename).name), cv2.IMREAD_COLOR
            )
            if image is not None and name.strip():
                result[" ".join(name.split())] = image
        return result
    except (OSError, ValueError, ImportError):
        return {}


def save_pickup_template(target_pid, name, top_left, bottom_right):
    """Capture the marked item crop and store it; return the BGR image or None."""
    left, top = top_left
    right, bottom = bottom_right
    if right <= left or bottom <= top:
        raise RuntimeError("Rogi są w złej kolejności; zaznacz przedmiot ponownie.")
    if right - left < 8 or bottom - top < 8:
        raise RuntimeError("Zaznacz większy fragment przedmiotu (co najmniej 8 × 8 px).")
    pixels = capture_region(
        target_pid, (left, top, right, bottom), grayscale=False, label="przedmiotu"
    )
    if pixels is None:
        return None

    import cv2

    template = cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR)
    PICKUP_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    filename = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:20] + ".png"
    if not cv2.imwrite(str(PICKUP_TEMPLATE_DIR / filename), template):
        raise RuntimeError("Nie udało się zapisać obrazu wzorca.")
    metadata = {}
    if PICKUP_TEMPLATE_MANIFEST.exists():
        try:
            metadata = json.loads(PICKUP_TEMPLATE_MANIFEST.read_text(encoding="utf-8"))
        except ValueError:
            metadata = {}
    metadata[name] = filename
    PICKUP_TEMPLATE_MANIFEST.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return template


def remove_pickup_template(name):
    """Delete one saved template from the manifest and disk."""
    if not PICKUP_TEMPLATE_MANIFEST.exists():
        return
    metadata = json.loads(PICKUP_TEMPLATE_MANIFEST.read_text(encoding="utf-8"))
    filename = metadata.pop(name, None)
    PICKUP_TEMPLATE_MANIFEST.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if filename:
        (PICKUP_TEMPLATE_DIR / Path(filename).name).unlink(missing_ok=True)


def find_ground_items(target_pid, region, templates, threshold=0.8):
    """Search the area for saved item crops.

    Return (score, name, client_x, client_y) sorted best first, or None when
    the client is not the foreground window. Coordinates are client-relative
    centers of the matched item, ready for dragging.
    """
    frame = capture_region(target_pid, region, grayscale=False, label="zbierania")
    if frame is None:
        return None

    import cv2

    image = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    left, top = region[0], region[1]
    detections = []
    for name, template in templates.items():
        if template is None or template.size == 0:
            continue
        template_height, template_width = template.shape[:2]
        if template_height > image.shape[0] or template_width > image.shape[1]:
            continue
        scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED).copy()
        # Kilka przedmiotów może leżeć obok siebie; po każdym trafieniu
        # wygaszamy jego otoczenie i szukamy kolejnego.
        for _ in range(9):
            _minimum, maximum, _min_location, location = cv2.minMaxLoc(scores)
            if maximum < threshold:
                break
            x, y = location
            detections.append((
                float(maximum), name,
                left + x + template_width // 2, top + y + template_height // 2,
            ))
            x1 = max(0, x - template_width)
            x2 = min(scores.shape[1], x + template_width)
            y1 = max(0, y - template_height)
            y2 = min(scores.shape[0], y + template_height)
            scores[y1:y2, x1:x2] = -1.0
    detections.sort(key=lambda item: item[0], reverse=True)
    return detections
