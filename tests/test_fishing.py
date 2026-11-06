"""Testy wędkowania: pola wody z mapy, kolor wody na zrzucie i łączenie stosów ryb."""

import random
import unittest

import numpy

from retronic_bot import fishing
from retronic_bot.minimap import FLAG_SEEN, OtmmMap

TILE = 32
VIEW = (100, 50, 100 + 15 * TILE, 50 + 11 * TILE)


def make_map(origin=(1000, 2000), z=7):
    colors = numpy.full((30, 30), 24, dtype=numpy.uint8)  # trawa
    flags = numpy.full((30, 30), FLAG_SEEN, dtype=numpy.uint8)
    return OtmmMap({z: (origin[0], origin[1], colors, flags)})


def set_color(otmm_map, x, y, z, color):
    origin_x, origin_y, colors, _flags = otmm_map.floors[z]
    colors[y - origin_y, x - origin_x] = color


def screen(water=()):
    """Zielony zrzut klienta z niebieskimi polami wody (offsety od postaci)."""
    image = numpy.zeros((500, 700, 3), dtype=numpy.uint8)
    image[:, :] = (40, 160, 40)
    for dx, dy in water:
        x, y = fishing.tile_center(VIEW, dx, dy)
        image[y - TILE // 2:y + TILE // 2, x - TILE // 2:x + TILE // 2] = (200, 40, 50)
    return image


def flood(otmm_map, x0, y0, x1, y1, z=7):
    """Prostokąt wody od (x0, y0) do (x1, y1) włącznie."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            set_color(otmm_map, x, y, z, fishing.WATER_COLOR)


class WaterTilesTest(unittest.TestCase):
    def test_only_tiles_surrounded_by_water(self):
        otmm = make_map()
        flood(otmm, 1011, 2009, 1014, 2011)  # jezioro 4 × 3 na prawo od postaci
        tiles = fishing.water_tiles(otmm, (1010, 2010, 7))
        # Brzeg (pola obok trawy) odpada; zostaje środek jeziora.
        self.assertEqual(sorted(tiles), [(2, 0), (3, 0)])

    def test_diagonal_land_makes_shore(self):
        otmm = make_map()
        flood(otmm, 1011, 2007, 1015, 2013)
        set_color(otmm, 1012, 2009, 7, 24)  # trawa po skosie od (1013, 2010)
        tiles = fishing.water_tiles(otmm, (1010, 2010, 7))
        self.assertNotIn((3, 0), tiles)
        self.assertIn((4, 0), tiles)

    def test_single_water_tile_is_shore(self):
        otmm = make_map()
        set_color(otmm, 1012, 2010, 7, fishing.WATER_COLOR)
        self.assertEqual(fishing.water_tiles(otmm, (1010, 2010, 7)), [])

    def test_range_and_own_tile_are_skipped(self):
        otmm = make_map()
        flood(otmm, 1000, 2000, 1029, 2029)  # postać na wodzie (np. na statku)
        tiles = fishing.water_tiles(otmm, (1010, 2010, 7), max_distance=1)
        self.assertEqual(len(tiles), 8)
        self.assertNotIn((0, 0), tiles)

    def test_tiles_outside_view_or_other_floor(self):
        otmm = make_map()
        flood(otmm, 1008, 2015, 1012, 2018)  # od dy=+5: tylko dalsze rzędy nie są brzegiem
        self.assertEqual(fishing.water_tiles(otmm, (1010, 2010, 7), max_distance=7), [])
        self.assertEqual(fishing.water_tiles(otmm, (1010, 2010, 6)), [])


class ScreenTest(unittest.TestCase):
    def test_tile_center(self):
        self.assertEqual(fishing.tile_center(VIEW, 0, 0), (100 + 7 * TILE + 16, 50 + 5 * TILE + 16))
        self.assertEqual(fishing.tile_center(VIEW, -7, -5), (116, 66))

    def test_blue_tiles_look_like_water(self):
        image = screen(water=[(3, 1)])
        self.assertTrue(fishing.looks_like_water(image, VIEW, 3, 1))
        self.assertFalse(fishing.looks_like_water(image, VIEW, 2, 1))
        # Samotne pole wody to brzeg.
        self.assertEqual(fishing.visible_water(image, VIEW), [])

    def test_visible_water_skips_shore_and_view_edge(self):
        lake = [(dx, dy) for dy in range(-1, 3) for dx in range(2, 8)]  # dx=7 to skraj widoku
        image = screen(water=lake)
        self.assertEqual(fishing.visible_water(image, VIEW),
                         [(dx, dy) for dx in range(3, 7) for dy in (0, 1)])

    def test_pick_tile_avoids_recent(self):
        rng = random.Random(1)
        for _ in range(20):
            self.assertEqual(fishing.pick_tile([(1, 0), (2, 0)], recent=[(1, 0)], rng=rng), (2, 0))
        self.assertEqual(fishing.pick_tile([(1, 0)], recent=[(1, 0)], rng=rng), (1, 0))
        self.assertIsNone(fishing.pick_tile([]))


def fish_icon(count_color):
    icon = numpy.zeros((26, 26, 3), dtype=numpy.uint8)
    icon[:, :] = (60, 60, 60)
    icon[4:12, 3:22] = (30, 140, 200)
    icon[6:9, 18:24] = (250, 250, 250)
    icon[2:6, 8:12] = (10, 10, 90)
    icon[18:25, 14:25] = count_color  # liczba sztuk w prawym dolnym rogu
    return icon


class FishSlotsTest(unittest.TestCase):
    def test_finds_every_slot_regardless_of_count(self):
        image = numpy.zeros((300, 400, 3), dtype=numpy.uint8)
        image[:, :] = (25, 25, 25)
        centers = [(213, 113), (253, 113), (213, 153)]
        for (x, y), color in zip(centers, [(255, 255, 255), (0, 0, 0), (120, 120, 0)]):
            image[y - 13:y + 13, x - 13:x + 13] = fish_icon(color)
        template = fish_icon((255, 255, 255))
        self.assertEqual(fishing.find_fish_slots(image, template), centers)
        # Ryba na mapie gry (exclude) nie jest slotem plecaka.
        self.assertEqual(fishing.find_fish_slots(image, template, exclude=[(240, 100, 270, 130)]),
                         [(213, 113), (213, 153)])

    def test_reading_order(self):
        points = [(50, 41), (10, 80), (10, 40), (90, 39)]
        self.assertEqual(fishing.reading_order(points, 30), [(10, 40), (50, 41), (90, 39), (10, 80)])

    def test_stack_move_skips_full_stacks(self):
        slots = [(1, 1), (2, 1), (3, 1)]
        self.assertEqual(fishing.stack_move(slots, lambda slot: False), ((1, 1), (2, 1)))
        self.assertEqual(fishing.stack_move(slots, lambda slot: slot == (2, 1)), ((1, 1), (3, 1)))
        self.assertIsNone(fishing.stack_move(slots, lambda slot: slot != (1, 1)))
        self.assertIsNone(fishing.stack_move(slots[:1], lambda slot: False))


if __name__ == "__main__":
    unittest.main()
