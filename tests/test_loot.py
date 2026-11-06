"""Testy siatki slotów, rozpoznawania ikon i przenoszenia lootu (na syntetycznych obrazach)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy

from retronic_bot import corpse, loot_patterns


SLOT = 32
GAP = 2


def container(scale=1, columns=4, rows=2, origin=(5, 7), items=None, scrollbar=True, seed=3):
    """Okno pojemnika: tło z szumem, sloty z ramką, opcjonalny pasek przewijania.

    items: {(kolumna, wiersz): rysujący(cell_bgr)}. Zwraca (obraz, lista pudełek slotów).
    """
    rng = numpy.random.default_rng(seed)
    slot, gap = SLOT * scale, GAP * scale
    width = origin[0] + columns * (slot + gap) + (14 * scale if scrollbar else 6) + 3
    height = origin[1] + rows * (slot + gap) + 5
    image = rng.integers(32, 40, size=(height, width, 3)).astype(numpy.uint8)
    boxes = []
    for row in range(rows):
        for column in range(columns):
            x = origin[0] + column * (slot + gap)
            y = origin[1] + row * (slot + gap)
            image[y:y + slot, x:x + slot] = 68                     # ramka slotu
            image[y + scale:y + slot - scale, x + scale:x + slot - scale] = 22  # ciemne wnętrze
            boxes.append((x, y, x + slot, y + slot))
            draw = (items or {}).get((column, row))
            if draw is not None:
                draw(image[y:y + slot, x:x + slot], scale)
    if scrollbar:
        x = width - 3 - 14 * scale
        image[:, x:x + 14 * scale] = 50
        image[2:2 + 12 * scale, x + 2:x + 12 * scale] = 90
    return image, boxes


def coin(cell, scale):
    center = (cell.shape[1] // 2 + 3 * scale, cell.shape[0] // 2 + 4 * scale)
    cv2.circle(cell, center, 6 * scale, (20, 190, 230), -1)
    cv2.circle(cell, center, 3 * scale, (10, 120, 160), -1)


def gold_stack(count):
    """Stos monet z liczbą sztuk w prawym dolnym rogu (biała cyfra z czarnym obrysem)."""
    def draw(cell, scale):
        for dx, dy in ((-6, -2), (2, -6), (-2, 4)):
            center = (cell.shape[1] // 2 + dx * scale, cell.shape[0] // 2 + dy * scale)
            cv2.circle(cell, center, 4 * scale, (20, 190, 230), -1)
            cv2.circle(cell, center, 2 * scale, (10, 120, 160), -1)
        text = str(count)
        origin = (cell.shape[1] - 2 * scale - 7 * scale * len(text), cell.shape[0] - 3 * scale)
        cv2.putText(cell, text, origin, cv2.FONT_HERSHEY_PLAIN, 0.9 * scale, (0, 0, 0), 3 * scale)
        cv2.putText(cell, text, origin, cv2.FONT_HERSHEY_PLAIN, 0.9 * scale, (235, 235, 235), scale)
    return draw


def meat(cell, scale):
    cv2.ellipse(cell, (cell.shape[1] // 2, cell.shape[0] // 2), (9 * scale, 6 * scale), 30, 0, 360,
                (40, 90, 200), -1)
    cv2.line(cell, (6 * scale, 26 * scale), (12 * scale, 20 * scale), (230, 230, 230), 2 * scale)


def sword(cell, scale):
    cv2.line(cell, (6 * scale, 26 * scale), (26 * scale, 6 * scale), (200, 200, 210), 3 * scale)
    cv2.line(cell, (8 * scale, 18 * scale), (14 * scale, 24 * scale), (60, 110, 150), 2 * scale)


class SlotGridTest(unittest.TestCase):
    def assert_grid(self, found, expected, tolerance):
        self.assertEqual(len(found), len(expected), found)
        for (fl, ft, _fr, _fb), (el, et, _er, _eb) in zip(found, expected):
            self.assertLessEqual(abs(fl - el), tolerance)
            self.assertLessEqual(abs(ft - et), tolerance)

    def test_grid_at_scale_1_and_2_with_offset_and_scrollbar(self):
        for scale in (1, 2):
            for origin in ((3, 4), (9, 2), (5, 11)):
                with self.subTest(scale=scale, origin=origin):
                    image, boxes = container(scale=scale, origin=(origin[0] * scale, origin[1] * scale))
                    found = loot_patterns.detect_slot_grid(image, scale)
                    self.assert_grid(found, boxes, tolerance=GAP * scale)

    def test_single_row_corpse(self):
        image, boxes = container(columns=4, rows=1, items={(1, 0): coin})
        self.assert_grid(loot_patterns.detect_slot_grid(image, 1), boxes, tolerance=GAP)

    def test_items_found_in_their_slots(self):
        for scale in (1, 2):
            with self.subTest(scale=scale):
                image, boxes = container(scale=scale, items={(1, 0): coin, (3, 1): meat})
                region = (100, 50, 100 + image.shape[1], 50 + image.shape[0])
                client = numpy.zeros((400, 600, 3), dtype=numpy.uint8)
                client[50:region[3], 100:region[2]] = image
                items = loot_patterns.find_slot_items(client, region, scale)
                self.assertEqual(len(items), 2)
                expected = [boxes[1], boxes[7]]
                for item, box in zip(items, expected):
                    center = (100 + (box[0] + box[2]) // 2, 50 + (box[1] + box[3]) // 2)
                    self.assertLessEqual(abs(item["center"][0] - center[0]), GAP * scale)
                    self.assertLessEqual(abs(item["center"][1] - center[1]), GAP * scale)

    def test_empty_container_has_no_items(self):
        image, _boxes = container()
        self.assertEqual(loot_patterns.find_slot_items(image, (0, 0, image.shape[1], image.shape[0])), [])


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        folder = Path(self.folder.name)
        self.patches = [
            mock.patch.object(loot_patterns, "LOOT_PATTERN_DIR", folder),
            mock.patch.object(loot_patterns, "LOOT_PATTERN_MANIFEST", folder / "patterns.json"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.folder.cleanup()

    def items(self, layout, origin=(5, 7), seed=3):
        image, _ = container(items=layout, origin=origin, seed=seed)
        return loot_patterns.find_slot_items(image, (0, 0, image.shape[1], image.shape[0]))

    def test_learn_then_recognise_despite_shifted_grid(self):
        first = self.items({(0, 0): coin, (1, 0): sword, (2, 0): coin})
        patterns = {}
        loot_patterns.identify_items(first, patterns)
        new = loot_patterns.learn_unknown(first, patterns)
        # Dwie takie same monety dają jeden wzorzec.
        self.assertEqual(len(new), 2)
        saved = loot_patterns.load_patterns()
        self.assertEqual(len(saved), 2)
        self.assertTrue(all(not pattern["enabled"] for pattern in saved.values()))
        # Inne ciało: przedmioty w innych slotach, siatka przesunięta.
        second = self.items({(2, 1): sword, (3, 0): coin}, origin=(8, 3), seed=9)
        loot_patterns.identify_items(second, saved)
        coin_id = first[0]["pattern"]
        sword_id = first[1]["pattern"]
        self.assertEqual({item["pattern"] for item in second}, {coin_id, sword_id})
        self.assertEqual(loot_patterns.learn_unknown(second, saved), [])

    def test_stack_count_does_not_matter(self):
        # Wzorzec zapisany przy „7 gold” rozpoznaje też „10 gold” (inna liczba w rogu).
        known = self.items({(0, 0): gold_stack(7)})
        patterns = {"gold": {"name": "Gold", "enabled": True, "image": known[0]["crop"]}}
        other = self.items({(2, 0): gold_stack(10)}, origin=(8, 3), seed=9)
        # Bez pomijania rogu z liczbą ikony różnią się za bardzo.
        plain = cv2.matchTemplate(other[0]["search"], known[0]["crop"], cv2.TM_CCOEFF_NORMED).max()
        self.assertLess(plain, loot_patterns.MATCH_THRESHOLD)
        loot_patterns.identify_items(other, patterns)
        self.assertEqual(other[0]["pattern"], "gold")
        # …ale mięso nadal nie jest złotem.
        meat_item = self.items({(1, 1): meat})
        loot_patterns.identify_items(meat_item, patterns)
        self.assertIsNone(meat_item[0]["pattern"])

    def test_meat_is_not_confused_with_coin(self):
        known = self.items({(0, 0): coin})
        patterns = {"coin": {"name": "Gold Coin", "enabled": True, "image": known[0]["crop"]}}
        other = self.items({(1, 1): meat})
        loot_patterns.identify_items(other, patterns)
        self.assertIsNone(other[0]["pattern"])

    def test_update_pattern(self):
        found = self.items({(0, 0): coin})
        patterns = {}
        loot_patterns.learn_unknown(found, patterns)
        pattern_id = found[0]["pattern"]
        loot_patterns.update_pattern(pattern_id, "  Gold   Coin ", True)
        saved = loot_patterns.load_patterns()[pattern_id]
        self.assertEqual((saved["name"], saved["enabled"]), ("Gold Coin", True))

    def test_debug_image_is_written_and_old_ones_pruned(self):
        image, _ = container(items={(0, 0): coin})
        debug = Path(self.folder.name) / "debug"
        with mock.patch.object(loot_patterns, "LOOT_DEBUG_DIR", debug), \
                mock.patch.object(loot_patterns, "LOOT_DEBUG_KEEP", 2):
            for index in range(4):
                (debug.mkdir(exist_ok=True), (debug / f"0000_{index}.png").write_bytes(b""))
            path = loot_patterns.save_debug_image(
                image, (0, 0, image.shape[1], image.shape[0]), 1, self.items({(0, 0): coin})
            )
        self.assertTrue(path.exists())
        self.assertEqual(len(list(debug.glob("*.png"))), 2)

    def test_debug_image_marks_click(self):
        image, boxes = container(items={(0, 0): coin})
        debug = Path(self.folder.name) / "debug"
        center = ((boxes[0][0] + boxes[0][2]) // 2, (boxes[0][1] + boxes[0][3]) // 2)
        with mock.patch.object(loot_patterns, "LOOT_DEBUG_DIR", debug):
            path = loot_patterns.save_debug_image(
                image, (0, 0, image.shape[1], image.shape[0]), 1, [], label="meat", marks=[center]
            )
        saved = cv2.imread(str(path))
        # Obraz jest powiększony 2× i przesunięty o margines 6 px (tu przycięty do 0).
        x, y = center[0] * 2, center[1] * 2
        self.assertEqual(tuple(int(v) for v in saved[y, x]), (0, 0, 255))
        self.assertTrue(path.name.endswith("_meat.png"))


class LootRulesTest(unittest.TestCase):
    PATTERNS = {
        "gold": {"name": "Gold Coin", "enabled": True},
        "meat": {"name": "Meat", "enabled": True},
        "bone": {"name": "Bone", "enabled": False},
    }

    def test_lootable(self):
        items = [{"pattern": "bone"}, {"pattern": "meat"}, {"pattern": None}, {"pattern": "gold"}]
        self.assertEqual([i["pattern"] for i in corpse.lootable(items, self.PATTERNS, True)], ["gold"])
        self.assertEqual([i["pattern"] for i in corpse.lootable(items, self.PATTERNS, False)], ["meat", "gold"])

    def test_loot_slot_problem(self):
        corpse_region = (500, 300, 640, 380)
        backpack = (500, 100, 640, 250)
        windows = [backpack, corpse_region]
        self.assertIsNone(corpse.loot_slot_problem((520, 120), corpse_region, windows))
        self.assertIn("nie ustawiono", corpse.loot_slot_problem(None, corpse_region, windows))
        self.assertIn("zasłonięty", corpse.loot_slot_problem((520, 320), corpse_region, windows))
        self.assertIn("nie leży", corpse.loot_slot_problem((20, 20), corpse_region, windows))

    def test_summary_with_loot(self):
        message = corpse.summary_message([], ["Gold Coin"], 1, False, "Zjadłem Meat.", ["Gold Coin"], None)
        self.assertEqual(message, "Ciało: zabrano Gold Coin. Zjadłem Meat.")
        message = corpse.summary_message([], ["Sword"], 1, False, None, [], "„Sword” nie przenosi się")
        self.assertEqual(message, "Ciało: rozpoznane przedmioty: Sword. Loot: „Sword” nie przenosi się.")


class MoveLootTest(unittest.TestCase):
    """_move_loot na atrapach: każdy zrzut to lista wzorców widocznych w ciele."""

    PATTERNS = {
        "gold": {"name": "Gold Coin", "enabled": True},
        "sword": {"name": "Sword", "enabled": True},
        "bone": {"name": "Bone", "enabled": False},
    }

    def run_loot(self, frames, stop_after=None):
        frames = iter(frames)
        drags = []
        calls = {"stop": 0}

        def fake_items(image, _region, _scale):
            return [{"pattern": pattern, "box": (index, 0, index + 1, 1), "center": (10 * index, 5)}
                    for index, pattern in enumerate(image)]

        def should_stop():
            calls["stop"] += 1
            return stop_after is not None and calls["stop"] > stop_after

        with mock.patch.object(corpse, "capture_region", side_effect=lambda *a, **k: next(frames)), \
                mock.patch.object(corpse, "find_slot_items", side_effect=fake_items), \
                mock.patch.object(corpse, "identify_items", side_effect=lambda items, _p: items), \
                mock.patch.object(corpse, "drag_item", side_effect=lambda *a, **k: drags.append(a[1:3]) or True), \
                mock.patch.object(corpse.time, "sleep"):
            looted, note = corpse._move_loot(1, (0, 0, 800, 600), (0, 0, 10, 10), 1.0,
                                             self.PATTERNS, (700, 100), True, should_stop)
        return looted, note, drags

    def test_moves_enabled_items_until_corpse_is_clean(self):
        frames = [["bone", "gold", "sword"], ["bone", "sword"], ["bone"]]
        looted, note, drags = self.run_loot(frames)
        self.assertEqual(looted, ["Gold Coin", "Sword"])
        self.assertIsNone(note)
        self.assertEqual(drags, [(10, 5), (10, 5)])

    def test_full_backpack_stops_with_message(self):
        frames = [["gold"], ["gold"], ["gold"]]
        looted, note, drags = self.run_loot(frames)
        self.assertEqual(looted, [])
        self.assertIn("nie przenosi się", note)
        self.assertEqual(len(drags), 2)

    def test_two_stacks_of_the_same_item(self):
        frames = [["gold", "gold"], ["gold"], []]
        looted, note, _drags = self.run_loot(frames)
        self.assertEqual(looted, ["Gold Coin", "Gold Coin"])
        self.assertIsNone(note)

    def test_stop_interrupts(self):
        frames = [["gold", "sword"], ["sword"], []]
        looted, note, drags = self.run_loot(frames, stop_after=1)
        self.assertEqual(note, "przerwano (STOP)")
        self.assertEqual(len(drags), 1)

    def test_inactive_window(self):
        looted, note, _drags = self.run_loot([None])
        self.assertEqual((looted, note), ([], "okno gry przestało być aktywne"))


if __name__ == "__main__":
    unittest.main()
