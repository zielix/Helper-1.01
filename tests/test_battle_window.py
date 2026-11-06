"""Testy odczytu tytułów małych okien (pamięć wyników OCR)."""

import unittest
from unittest import mock

import cv2
import numpy

from retronic_bot import battle_window


def header(text, x_offset=0):
    """Nagłówek okna: ciemne tło z jasnym napisem; zwraca (obraz, bounds, button)."""
    image = numpy.full((40, 200, 3), 30, dtype=numpy.uint8)
    cv2.putText(image, text, (8 + x_offset, 15), cv2.FONT_HERSHEY_PLAIN, 0.9, (200, 200, 200), 1)
    return image, (0, 0, 200, 20, 40), (180, 2, 14, 14)


class TitleCacheTest(unittest.TestCase):
    def setUp(self):
        battle_window._TITLE_CACHE.clear()

    def test_same_title_is_read_once(self):
        image, bounds, button = header("Dead larva")
        with mock.patch.object(battle_window, "_ocr_title", return_value="Dead larva") as ocr:
            for _ in range(3):
                self.assertEqual(battle_window.read_title(image, bounds, button, 1.0, "t"), "Dead larva")
        self.assertEqual(ocr.call_count, 1)

    def test_different_titles_are_read_separately(self):
        first = header("Skills")
        second = header("VIP List")
        with mock.patch.object(battle_window, "_ocr_title", side_effect=["Skills", "VIP List"]) as ocr:
            self.assertEqual(battle_window.read_title(*first, 1.0, "t"), "Skills")
            self.assertEqual(battle_window.read_title(*second, 1.0, "t"), "VIP List")
        self.assertEqual(ocr.call_count, 2)

    def test_header_background_does_not_matter(self):
        image, bounds, button = header("Backpack")
        darker = image.copy()
        darker[image < 100] = 18   # inne tło nagłówka, ten sam napis
        with mock.patch.object(battle_window, "_ocr_title", return_value="Backpack") as ocr:
            battle_window.read_title(image, bounds, button, 1.0, "t")
            battle_window.read_title(darker, bounds, button, 1.0, "t")
        self.assertEqual(ocr.call_count, 1)

    def test_read_titles_keeps_order(self):
        frames = []
        images = {}
        for index, text in enumerate(("Skills", "Dead larva", "Backpack")):
            image, bounds, button = header(text)
            frames.append({"bounds": bounds, "button": button, "text": text})
            images[text] = image
        with mock.patch.object(battle_window, "frame_title",
                               side_effect=lambda _img, frame, _s, _t: frame["text"]):
            titles = battle_window.read_titles(None, frames, 1.0, "t")
        self.assertEqual(titles, ["Skills", "Dead larva", "Backpack"])
        self.assertEqual(battle_window.read_titles(None, [], 1.0, "t"), [])


if __name__ == "__main__":
    unittest.main()
