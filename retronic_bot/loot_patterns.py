"""Image catalogue for items observed in opened creature containers.

Sloty okna pojemnika nie mają stałego położenia (zależy od skali klienta,
ramki okna i paska przewijania), więc siatkę wyznaczamy z obrazu: krawędzie
slotów powtarzają się co jeden slot, a szukamy okresu i przesunięcia, przy
których krawędzie są najsilniejsze. Wzorzec przedmiotu to wnętrze slotu;
rozpoznając, szukamy go w całym slocie z kilkupikselowym luzem.
"""

import json
import time
from pathlib import Path

LOOT_PATTERN_DIR = Path(__file__).resolve().parent.parent / "loot_patterns"
LOOT_PATTERN_MANIFEST = LOOT_PATTERN_DIR / "patterns.json"
LOOT_DEBUG_DIR = Path(__file__).resolve().parent.parent / "loot_debug"
LOOT_DEBUG_KEEP = 20

# Slot w kliencie ma 32 px + ramka/odstęp (przy skali 1); szukamy okresu w tym zakresie.
SLOT_PERIOD_RANGE = (30, 38)
# Margines wycinanego wnętrza slotu (przy skali 1), żeby ramka nie trafiła do wzorca.
SLOT_MARGIN = 4
# Dopasowanie (TM_CCOEFF_NORMED w kolorze), od którego przedmiot uznajemy za znany.
MATCH_THRESHOLD = 0.85
# Liczba sztuk stosu (np. „10” przy złocie) leży w prawym dolnym rogu ikony; ten róg
# (ułamki wysokości i szerokości) pomijamy przy porównaniu, bo zmienia się z każdą sztuką.
COUNT_ZONE = (0.55, 0.3)
# Zapas wokół slotu przy szukaniu ikony (przy skali 1): siatka bywa przesunięta o kilka pikseli.
SEARCH_SLACK = 4


def _read_manifest():
    try:
        data = json.loads(LOOT_PATTERN_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_manifest(manifest):
    LOOT_PATTERN_DIR.mkdir(parents=True, exist_ok=True)
    LOOT_PATTERN_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_patterns():
    """Return saved entries as {id: {name, enabled, image}}.

    `enabled` znaczy „zabieraj z ciała”; wzorzec o nazwie Meat bot je.
    """
    import cv2

    result = {}
    for pattern_id, entry in _read_manifest().items():
        if not isinstance(entry, dict):
            continue
        filename = Path(str(entry.get("file", ""))).name
        if not filename:
            continue
        image = cv2.imread(str(LOOT_PATTERN_DIR / filename), cv2.IMREAD_COLOR)
        if image is None:
            continue
        result[str(pattern_id)] = {
            "name": str(entry.get("name", pattern_id)),
            "enabled": bool(entry.get("enabled", True)),
            "image": image,
        }
    return result


def update_pattern(pattern_id, name, enabled):
    manifest = _read_manifest()
    entry = manifest.get(pattern_id)
    if not isinstance(entry, dict):
        raise KeyError("Nie znaleziono wzorca przedmiotu.")
    entry["name"] = " ".join(name.split()) or str(pattern_id)
    entry["enabled"] = bool(enabled)
    _write_manifest(manifest)


def remove_pattern(pattern_id):
    """Delete a pattern from the catalogue together with its image."""
    manifest = _read_manifest()
    entry = manifest.pop(pattern_id, None)
    if not isinstance(entry, dict):
        raise KeyError("Nie znaleziono wzorca przedmiotu.")
    filename = Path(str(entry.get("file", ""))).name
    if filename:
        (LOOT_PATTERN_DIR / filename).unlink(missing_ok=True)
    _write_manifest(manifest)


def is_meat(pattern):
    return pattern["name"].strip().casefold() == "meat"


# --- siatka slotów -------------------------------------------------------------


def _fold(profile, period):
    """Profile folded to one period: typical edge strength at each offset.

    Przy co najmniej trzech pełnych okresach bierzemy medianę: krawędzie
    slotów powtarzają się w każdej komórce, a wyraźny obrys przedmiotu
    (np. stos złota z liczbą „10”) tylko w niektórych — przy sumie potrafił
    przesunąć całą siatkę o kilka pikseli i ikona wypadała ze slotu.
    Inaczej suma (a nie średnia), która nie faworyzuje okresów, przy których
    ostatnia niepełna komórka ma mniej wartości; profil krótszy niż okres też działa.
    """
    import numpy

    full = len(profile) // period
    if full >= 3:
        return numpy.median(numpy.asarray(profile[:full * period], dtype=float).reshape(full, period), axis=0)
    padded = numpy.zeros(-(-len(profile) // period) * period)
    padded[:len(profile)] = profile
    return padded.reshape(-1, period).sum(axis=0) * period / max(len(profile), period)


def _best_period(profiles, low, high, edges_per_slot=4):
    """Return the slot grid period shared by both axes (slots are square).

    Przy prawdziwym okresie wszystkie krawędzie slotu (zewnętrzna i wewnętrzna
    z obu stron) nakładają się we wszystkich komórkach, więc suma kilku
    najsilniejszych wartości złożonego profilu jest największa. Sam
    najsilniejszy punkt nie wystarcza: przy dwóch rzędach górna i dolna
    krawędź jednego rzędu też „powtarzają się” co rozmiar slotu. Oś krótsza
    niż dwa sloty (np. jeden rząd) nie rozróżnia okresów i nie psuje wyniku.
    """
    import numpy

    best = None
    longest = max(len(profile) for profile in profiles)
    for period in range(low, high + 1):
        if 2 * period > longest + 1:
            break
        score = sum(float(numpy.sort(_fold(profile, period))[-edges_per_slot:].sum())
                    for profile in profiles)
        if best is None or score > best[0]:
            best = (score, period)
    return None if best is None else best[1]


def _slot_span(profile, period):
    """Return (first slot start, slot size) along one axis.

    Profil krawędzi składamy do długości jednego okresu. Slot ma mocne
    krawędzie po obu stronach ramki (zewnętrzną i wewnętrzną), a jego brzegi
    to para mocnych krawędzi najdalej od siebie — dalej niż wewnętrzne
    krawędzie ramki, ale bliżej niż pełny okres (resztę zajmuje odstęp).
    Krawędź o indeksie i leży między pikselami i oraz i+1.
    """
    fold = _fold(profile, period)
    threshold = 0.5 * float(fold.max())
    peaks = [i for i in range(period)
             if fold[i] >= threshold and fold[i] >= fold[i - 1] and fold[i] >= fold[(i + 1) % period]]
    best = None
    for start in peaks:
        for end in peaks:
            size = (end - start) % period
            if size < 0.75 * period:
                continue
            key = (size, fold[start] + fold[end])
            if best is None or key > best[0]:
                best = (key, start)
    if best is None:
        return (int(fold.argmax()) + 1) % period, period
    (size, _strength), start = best
    return (start + 1) % period, size


def detect_slot_grid(area_bgr, scale=1.0):
    """Return slot boxes [(left, top, right, bottom)] inside the container body.

    Najpierw okres siatki (slot + odstęp) z powtarzających się krawędzi,
    potem położenie i rozmiar samego slotu w okresie (_slot_span).
    """
    import cv2
    import numpy

    if area_bgr is None or area_bgr.size == 0:
        return []
    gray = cv2.cvtColor(area_bgr[:, :, :3], cv2.COLOR_BGR2GRAY).astype(numpy.int16)
    if gray.shape[0] < 8 or gray.shape[1] < 8:
        return []
    scale = max(1.0, float(scale or 1.0))
    low = int(SLOT_PERIOD_RANGE[0] * scale)
    high = int(round(SLOT_PERIOD_RANGE[1] * scale))
    edges_x = numpy.abs(numpy.diff(gray, axis=1)).mean(axis=0)
    edges_y = numpy.abs(numpy.diff(gray, axis=0)).mean(axis=1)
    period = _best_period((edges_x, edges_y), low, high)
    if period is None:
        return []
    start_x, size_x = _slot_span(edges_x, period)
    start_y, size_y = _slot_span(edges_y, period)
    height, width = gray.shape
    lefts = range(start_x, width - size_x + 1, period)
    tops = range(start_y, height - size_y + 1, period)
    return [(left, top, left + size_x, top + size_y) for top in tops for left in lefts]


def _slot_interior(cell, scale):
    margin = max(1, round(SLOT_MARGIN * max(1.0, float(scale or 1.0))))
    return cell[margin:cell.shape[0] - margin, margin:cell.shape[1] - margin]


def _looks_empty(interior):
    """Empty slots are flat dark squares: low contrast, no colour, few edges."""
    import cv2
    import numpy

    if interior.shape[0] < 8 or interior.shape[1] < 8:
        return True
    gray = cv2.cvtColor(interior, cv2.COLOR_BGR2GRAY)
    saturation = cv2.cvtColor(interior, cv2.COLOR_BGR2HSV)[:, :, 1]
    edge_fraction = numpy.count_nonzero(cv2.Canny(gray, 35, 100)) / gray.size
    colored_fraction = numpy.count_nonzero(saturation > 35) / saturation.size
    return float(gray.std()) < 14 and colored_fraction < 0.025 and edge_fraction < 0.06


def find_slot_items(image_bgr, region, scale=1.0):
    """Non-empty slots of a container window.

    Zwraca listę słowników: box (współrzędne klienta), center (punkt do
    przeciągania), cell (cały slot) i crop (wnętrze slotu = wzorzec).
    """
    left, top, right, bottom = region
    area = image_bgr[top:bottom, left:right, :3]
    items = []
    for box in detect_slot_grid(area, scale):
        cell = area[box[1]:box[3], box[0]:box[2]]
        interior = _slot_interior(cell, scale)
        if _looks_empty(interior):
            continue
        absolute = (left + box[0], top + box[1], left + box[2], top + box[3])
        slack = max(1, round(SEARCH_SLACK * max(1.0, float(scale or 1.0))))
        search = area[max(0, box[1] - slack):box[3] + slack, max(0, box[0] - slack):box[2] + slack]
        items.append({
            "box": absolute,
            "center": ((absolute[0] + absolute[2]) // 2, (absolute[1] + absolute[3]) // 2),
            "cell": cell.copy(),
            "search": search.copy(),
            "crop": interior.copy(),
        })
    return items


# --- rozpoznawanie i nauka ------------------------------------------------------


def count_mask(template):
    """Template mask without the bottom-right corner where the stack count is drawn."""
    import numpy

    height, width = template.shape[:2]
    mask = numpy.full((height, width), 255, dtype=numpy.uint8)
    mask[int(height * COUNT_ZONE[0]):, int(width * COUNT_ZONE[1]):] = 0
    return mask


def match_score(cell, template):
    """Best colour match of a saved icon anywhere inside one slot (−1 when it cannot fit).

    Porównujemy całą ikonę, a potem ikonę bez rogu z liczbą sztuk: stos
    „10 gold” to ten sam obrazek co „7 gold”, tylko z inną liczbą, i bez
    tego rogu pasuje do zapisanego wzorca.
    """
    import cv2
    import numpy

    if cell is None or template is None or cell.size == 0 or template.size == 0:
        return -1.0
    if template.shape[0] > cell.shape[0] or template.shape[1] > cell.shape[1]:
        # Wzorzec z innej skali klienta: dopasuj rozmiar do wnętrza slotu.
        side = min(cell.shape[0], cell.shape[1]) - 2
        if side < 8:
            return -1.0
        template = cv2.resize(template, (side, side), interpolation=cv2.INTER_AREA)
    image, template = cell[:, :, :3], template[:, :, :3]
    best = float(cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED).max())
    if best < MATCH_THRESHOLD:
        mask = cv2.merge([count_mask(template)] * 3)
        masked = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED, mask=mask)
        # Gładkie okno bez kontrastu daje dzielenie przez zero.
        masked = numpy.nan_to_num(masked, nan=-1.0, posinf=-1.0, neginf=-1.0)
        best = max(best, float(masked.max()))
    return best


def identify(item, patterns):
    """Return (pattern_id, score) of the best matching saved icon, or (None, score)."""
    best_id, best_score = None, -1.0
    for pattern_id, pattern in patterns.items():
        score = match_score(item.get("search", item["cell"]), pattern["image"])
        if score > best_score:
            best_id, best_score = pattern_id, score
    if best_score >= MATCH_THRESHOLD:
        return best_id, best_score
    return None, best_score


def identify_items(items, patterns):
    """Set item["pattern"] (id or None) and item["score"] for every slot item."""
    for item in items:
        item["pattern"], item["score"] = identify(item, patterns)
    return items


def learn_unknown(items, patterns):
    """Save icons of unidentified items as new, not-looted patterns; return their names.

    Nowe wzorce są wyłączone (bot ich nie zabiera), dopóki nie zaznaczysz ich
    w katalogu. Dwa takie same nieznane przedmioty w jednym ciele dają jeden wzorzec.
    """
    import cv2

    manifest = _read_manifest()
    next_number = len(manifest) + 1
    new_names = []
    for item in items:
        if item.get("pattern") is not None:
            continue
        pattern_id, _score = identify(item, patterns)
        if pattern_id is not None:
            item["pattern"] = pattern_id
            continue
        while f"item_{next_number:04d}" in manifest:
            next_number += 1
        pattern_id = f"item_{next_number:04d}"
        filename = f"{pattern_id}.png"
        LOOT_PATTERN_DIR.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(LOOT_PATTERN_DIR / filename), item["crop"]):
            continue
        name = f"Nowy przedmiot {next_number:04d}"
        manifest[pattern_id] = {"file": filename, "name": name, "enabled": False}
        patterns[pattern_id] = {"name": name, "enabled": False, "image": item["crop"].copy()}
        item["pattern"] = pattern_id
        new_names.append(name)
        next_number += 1
    if new_names:
        _write_manifest(manifest)
    return new_names


# --- obraz diagnostyczny --------------------------------------------------------


def save_debug_image(image_bgr, region, scale, items, label="corpse", marks=(), grid=True):
    """Save the container window with detected slots drawn on it; return the path or None.

    Zielone ramki: rozpoznany wzorzec, żółte: nieznany przedmiot, szare: pusty slot,
    czerwone krzyżyki: miejsca kliknięć (marks, współrzędne klienta).
    Folder trzyma najwyżej LOOT_DEBUG_KEEP ostatnich obrazów.
    """
    import cv2

    try:
        left, top, right, bottom = region
        pad = 6
        y0, x0 = max(0, top - pad), max(0, left - pad)
        canvas = image_bgr[y0:bottom + pad, x0:right + pad, :3].copy()
        area = image_bgr[top:bottom, left:right, :3]
        for box in (detect_slot_grid(area, scale) if grid else ()):
            cv2.rectangle(canvas, (left - x0 + box[0], top - y0 + box[1]),
                          (left - x0 + box[2] - 1, top - y0 + box[3] - 1), (128, 128, 128), 1)
        for item in items:
            color = (0, 200, 0) if item.get("pattern") else (0, 220, 255)
            box = item["box"]
            cv2.rectangle(canvas, (box[0] - x0, box[1] - y0), (box[2] - x0 - 1, box[3] - y0 - 1), color, 1)
        for x, y in marks:
            cv2.drawMarker(canvas, (int(x) - x0, int(y) - y0), (0, 0, 255), cv2.MARKER_CROSS, 9, 1)
        canvas = cv2.resize(canvas, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        LOOT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOOT_DEBUG_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{label}.png"
        cv2.imwrite(str(path), canvas)
        for old in sorted(LOOT_DEBUG_DIR.glob("*.png"))[:-LOOT_DEBUG_KEEP]:
            old.unlink(missing_ok=True)
        return path
    except Exception:
        # Diagnostyka nigdy nie przerywa lootowania.
        return None
