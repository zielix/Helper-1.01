"""Tryb Human: ruchy i reakcje bota rozłożone w czasie jak u człowieka.

Bez trybu Human bot przenosi kursor w jednej klatce, klika natychmiast po
wykryciu zdarzenia i zawsze w ten sam piksel. Z trybem Human ruch nie jest
idealnie płynny (to też wyglądałoby na bota): kursor wykonuje niedokładny rzut
w okolice celu i jedną–dwie poprawki, z drżeniem i nierównym tempem, czasem
z przestrzeleniem lub zawahaniem. Przycisk jest wciskany na losowy czas,
reakcje mają nieregularne opóźnienie, a kliknięcia trafiają w losowy punkt pola.
"""

import math
import random
import time


_state = {"enabled": False}

# Zakresy opóźnień reakcji w sekundach (losowane przy każdym zdarzeniu).
REACTION = {
    "attack": (0.25, 0.85),     # zauważenie potwora na liście Battle
    "retarget": (0.35, 1.1),    # wybór kolejnego celu po śmierci poprzedniego
    "walk": (0.15, 0.55),       # kolejne kliknięcie w minimapę w trakcie trasy
    "waypoint": (0.3, 1.4),     # chwila po dojściu do waypointu
}


def enabled():
    return _state["enabled"]


def set_enabled(value):
    _state["enabled"] = bool(value)


def reaction(kind):
    """Delay before reacting to an event; 0 when Human mode is off."""
    if not _state["enabled"]:
        return 0.0
    low, high = REACTION[kind]
    # Rozkład z dłuższym ogonem: zwykle szybko, czasem wyraźnie wolniej,
    # a co jakiś czas „zagapienie się” dwa–trzy razy dłuższe niż zwykle.
    delay = low + (high - low) * random.betavariate(2.0, 3.5)
    if random.random() < 0.06:
        delay *= random.uniform(2.0, 3.0)
    return delay


def jitter(value, spread):
    """Shift a pixel coordinate inside ±spread (only in Human mode)."""
    if not _state["enabled"] or spread < 1:
        return value
    return value + int(round(random.triangular(-spread, spread, 0)))


def maybe_break(chance=0.004, low=2.0, high=7.0):
    """Occasionally return a short break length in seconds, otherwise 0."""
    if _state["enabled"] and random.random() < chance:
        return random.uniform(low, high)
    return 0.0


def _segment(start, end, duration):
    """One sub-movement: a slightly bent, unevenly timed stroke with tremor.

    Zwraca listę (x, y, czas_do_następnego_punktu). Prędkość nie jest stała
    ani symetryczna: ręka szybko rusza, nierówno hamuje, punkty mają drżenie.
    """
    sx, sy = start
    ex, ey = end
    distance = math.hypot(ex - sx, ey - sy)
    if distance < 1.5:
        return [[int(ex), int(ey), duration]]
    bend = max(-0.15, min(0.15, random.gauss(0, 0.06))) * distance
    nx, ny = -(ey - sy) / distance, (ex - sx) / distance
    cx = sx + (ex - sx) * random.uniform(0.3, 0.6) + nx * bend
    cy = sy + (ey - sy) * random.uniform(0.3, 0.6) + ny * bend
    steps = max(3, min(28, int(distance / random.uniform(9, 18))))
    tremor = min(2.0, 0.4 + distance / 400)
    points = []
    for i in range(1, steps + 1):
        t = i / steps
        # Asymetryczne tempo: szybki start, długie i nierówne dohamowanie.
        t = 1 - (1 - t) ** random.uniform(1.6, 2.6)
        x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t * t * ex
        y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t * t * ey
        if i < steps:
            x += random.gauss(0, tremor)
            y += random.gauss(0, tremor)
        points.append([int(round(x)), int(round(y)), duration / steps * random.uniform(0.6, 1.4)])
    points[-1][0], points[-1][1] = int(ex), int(ey)
    return points


def cursor_path(start, end):
    """Points (x, y, delay) of a human-like move: a rough throw plus corrections.

    Człowiek nie prowadzi kursora jedną idealną krzywą: najpierw szybki,
    niedokładny rzut w okolice celu, potem jedna–dwie małe poprawki, czasem
    przestrzelenie albo chwila zawahania w połowie drogi.
    """
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    if distance < 2:
        return [(end[0], end[1], 0.0)]
    # Czas ruchu rośnie z odległością jak w prawie Fittsa, z rozrzutem.
    total = (0.05 + 0.065 * math.log2(1 + distance / 12)) * random.uniform(0.8, 1.25)
    # Rzut kończy się kilka procent obok celu (czasem za celem).
    miss = min(25.0, distance * random.uniform(0.02, 0.06))
    angle = random.uniform(0, 2 * math.pi)
    overshoot = random.random() < 0.3
    along = 1.0 + (random.uniform(0.01, 0.04) if overshoot else -random.uniform(0.0, 0.04))
    throw = (
        start[0] + (end[0] - start[0]) * along + math.cos(angle) * miss * 0.5,
        start[1] + (end[1] - start[1]) * along + math.sin(angle) * miss * 0.5,
    )
    points = _segment(start, throw, total * 0.72)
    if distance > 120 and random.random() < 0.12:
        # Zawahanie: ręka na chwilę staje w trakcie ruchu.
        middle = len(points) // 2
        points[middle][2] += random.uniform(0.06, 0.18)
    position = (points[-1][0], points[-1][1])
    corrections = 1 if math.hypot(end[0] - position[0], end[1] - position[1]) < 6 else 2
    for index in range(corrections):
        last = index == corrections - 1
        if last:
            target = end
        else:
            target = (end[0] + random.gauss(0, 2), end[1] + random.gauss(0, 2))
        points[-1][2] += random.uniform(0.015, 0.06)  # chwila na ocenę, gdzie jest kursor
        points += _segment(position, target, total * random.uniform(0.1, 0.18))
        position = target
    points[-1][0], points[-1][1] = int(end[0]), int(end[1])
    return [tuple(point) for point in points]


def glide(set_cursor, start, end):
    """Move the cursor along cursor_path with its uneven, human-like timing."""
    for x, y, delay in cursor_path(start, end):
        set_cursor(int(x), int(y))
        if delay > 0:
            time.sleep(delay)


def hover():
    time.sleep(random.uniform(0.03, 0.11))


def press_time():
    return random.uniform(0.045, 0.12)
