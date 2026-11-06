"""Testy wczytywania .otmm i dopasowania siatki minimapy do mapy."""

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy

from retronic_bot.minimap import (
    BLOCK_SIZE, FLAG_SEEN, UNKNOWN, MinimapLocator, OtmmMap,
)


def write_otmm(path, blocks):
    """Zapisz bloki {(x, y, z): tablica 64×64×3} w formacie OTMM."""
    header = b"OTMM" + struct.pack("<H", 6)
    body = b""
    for (x, y, z), tiles in blocks.items():
        packed = zlib.compress(tiles.astype(numpy.uint8).tobytes())
        body += struct.pack("<HHBH", x, y, z, len(packed)) + packed
    body += struct.pack("<HHB", 0xFFFF, 0xFFFF, 0)
    Path(path).write_bytes(header + body)


def random_floor(seed, width=128, height=128, origin=(32000, 32000)):
    rng = numpy.random.default_rng(seed)
    colors = rng.integers(1, 216, size=(height, width), dtype=numpy.uint8)
    flags = numpy.full((height, width), FLAG_SEEN, dtype=numpy.uint8)
    return origin[0], origin[1], colors, flags


class PlayerCrossTest(unittest.TestCase):
    def test_even_cross_points_at_player_tile(self):
        from retronic_bot.minimap import find_player_cross

        # Skala 1 px na pole: pole postaci to piksel (20, 15), krzyżyk 10 × 10
        # jest wyśrodkowany na (20,5; 15,5), czyli zajmuje x 16–25, y 11–20.
        image = numpy.zeros((31, 41, 3), dtype=numpy.uint8)
        image[11:21, 19:23] = 255
        image[14:18, 16:26] = 255
        self.assertEqual(find_player_cross(image), (20, 15))


class OtmmLoadTest(unittest.TestCase):
    def test_load_assembles_blocks_and_drops_stray_ones(self):
        blocks = {}
        rng = numpy.random.default_rng(1)
        # 8 bloków obok siebie (gęsty obszar) i jeden zabłąkany daleko na x=0.
        for i in range(8):
            tiles = numpy.zeros((BLOCK_SIZE, BLOCK_SIZE, 3), dtype=numpy.uint8)
            tiles[:, :, 0] = FLAG_SEEN
            tiles[:, :, 1] = rng.integers(1, 216, size=(BLOCK_SIZE, BLOCK_SIZE))
            blocks[(32768 + i * BLOCK_SIZE, 32768, 7)] = tiles
        tiles[0, 0, 1] = 0  # czarne pole = nieodkryte
        tiles[1, 0, 0] = 0  # pole nieodkryte w flagach
        blocks[(0, 0, 7)] = tiles.copy()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.otmm"
            write_otmm(path, blocks)
            otmm = OtmmMap.load(path)
        origin_x, origin_y, colors, _flags = otmm.floors[7]
        self.assertEqual((origin_x, origin_y), (32768, 32768))
        self.assertEqual(colors.shape, (BLOCK_SIZE, 8 * BLOCK_SIZE))
        first = blocks[(32768, 32768, 7)]
        self.assertEqual(otmm.tile(32768 + 5, 32768 + 3, 7), (int(first[3, 5, 1]), FLAG_SEEN))
        last_x = 32768 + 7 * BLOCK_SIZE
        self.assertEqual(otmm.tile(last_x, 32768, 7)[0], UNKNOWN)
        self.assertEqual(otmm.tile(last_x, 32769, 7)[0], UNKNOWN)
        self.assertFalse(otmm.is_walkable(last_x, 32769, 7))
        self.assertIsNone(otmm.tile(0, 0, 7))
        self.assertIsNone(otmm.tile(32768, 32768, 6))

    def test_rejects_other_formats(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "zly.otmm"
            path.write_bytes(b"NOPE" + b"\0" * 10)
            with self.assertRaises(ValueError):
                OtmmMap.load(path)


class MinimapLocatorTest(unittest.TestCase):
    def setUp(self):
        self.floor = random_floor(seed=7)
        self.otmm = OtmmMap({7: self.floor, 8: random_floor(seed=8)})
        self.locator = MinimapLocator(self.otmm)

    def grid_at(self, x, y, size=15):
        origin_x, origin_y, colors, _flags = self.floor
        half = size // 2
        row, col = y - origin_y, x - origin_x
        grid = colors[row - half:row + half + 1, col - half:col + half + 1].copy()
        grid[half, half] = UNKNOWN  # krzyżyk postaci
        return grid, (half, half)

    def test_global_search_finds_position_and_floor(self):
        grid, center = self.grid_at(32050, 32060)
        result = self.locator.locate(grid, center)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual((result.x, result.y, result.z), (32050, 32060, 7))

    def test_local_search_follows_movement_from_hint(self):
        grid, center = self.grid_at(32053, 32058)
        result = self.locator.locate(grid, center, hint=(32050, 32060, 7))
        self.assertTrue(result.ok, result.reason)
        self.assertEqual((result.x, result.y, result.z), (32053, 32058, 7))

    def test_tolerates_some_misread_tiles(self):
        grid, center = self.grid_at(32040, 32070)
        grid[0, :5] = 3  # kilka błędnie odczytanych pól
        result = self.locator.locate(grid, center)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual((result.x, result.y), (32040, 32070))

    def test_too_few_known_tiles(self):
        grid = numpy.full((15, 15), UNKNOWN, dtype=numpy.uint8)
        result = self.locator.locate(grid, (7, 7))
        self.assertFalse(result.ok)

    def test_uniform_terrain_is_ambiguous(self):
        origin_x, origin_y, colors, flags = self.floor
        flat = numpy.full_like(colors, 42)
        locator = MinimapLocator(OtmmMap({7: (origin_x, origin_y, flat, flags)}))
        grid = numpy.full((15, 15), 42, dtype=numpy.uint8)
        result = locator.locate(grid, (7, 7))
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
