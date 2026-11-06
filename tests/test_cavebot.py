"""Testy wyznaczania drogi, chodzenia po waypointach i zapisu profili."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy

from retronic_bot import cavebot, human
from retronic_bot.minimap import FLAG_NOT_PATHABLE, FLAG_NOT_WALKABLE, FLAG_SEEN, OtmmMap


def make_map(width=20, height=20, z=7, origin=(1000, 2000)):
    """Mapa jednego piętra, w całości odkryta i przechodnia."""
    colors = numpy.full((height, width), 10, dtype=numpy.uint8)
    flags = numpy.full((height, width), FLAG_SEEN, dtype=numpy.uint8)
    return OtmmMap({z: (origin[0], origin[1], colors, flags)})


def set_flags(otmm_map, x, y, z, value):
    origin_x, origin_y, _colors, flags = otmm_map.floors[z]
    flags[y - origin_y, x - origin_x] = value


class FindPathTest(unittest.TestCase):
    def test_straight_path_on_open_floor(self):
        otmm = make_map()
        path = cavebot.find_path(otmm, (1000, 2000, 7), (1005, 2000, 7))
        self.assertEqual(path[0], (1000, 2000))
        self.assertEqual(path[-1], (1005, 2000))
        self.assertEqual(len(path), 6)

    def test_other_floor_or_missing_floor_has_no_path(self):
        otmm = make_map()
        self.assertIsNone(cavebot.find_path(otmm, (1000, 2000, 7), (1005, 2000, 8)))
        self.assertIsNone(cavebot.find_path(otmm, (1000, 2000, 6), (1005, 2000, 6)))

    def test_path_goes_around_wall(self):
        otmm = make_map()
        # Ściana w kolumnie x=1003 z jedną przerwą na y=2010.
        for y in range(2000, 2020):
            if y != 2010:
                set_flags(otmm, 1003, y, 7, FLAG_SEEN | FLAG_NOT_WALKABLE)
        path = cavebot.find_path(otmm, (1000, 2000, 7), (1006, 2000, 7))
        self.assertIsNotNone(path)
        self.assertIn((1003, 2010), path)
        for x, y in path:
            if x == 1003:
                self.assertEqual(y, 2010)

    def test_unseen_and_not_pathable_tiles_block(self):
        otmm = make_map(width=5, height=1)
        set_flags(otmm, 1002, 2000, 7, 0)  # nieodkryte
        self.assertIsNone(cavebot.find_path(otmm, (1000, 2000, 7), (1004, 2000, 7)))
        set_flags(otmm, 1002, 2000, 7, FLAG_SEEN | FLAG_NOT_PATHABLE)
        self.assertIsNone(cavebot.find_path(otmm, (1000, 2000, 7), (1004, 2000, 7)))

    def test_goal_is_allowed_even_when_not_pathable(self):
        # Schody i dziury mają flagę „nie do autowalku”, a bot ma na nie wejść.
        otmm = make_map(width=5, height=1)
        set_flags(otmm, 1004, 2000, 7, FLAG_SEEN | FLAG_NOT_PATHABLE)
        path = cavebot.find_path(otmm, (1000, 2000, 7), (1004, 2000, 7))
        self.assertEqual(path[-1], (1004, 2000))


class CavebotWalkerTest(unittest.TestCase):
    def setUp(self):
        human.set_enabled(False)
        self.otmm = make_map()

    def walker(self, *waypoints):
        return cavebot.CavebotWalker(self.otmm, [
            {"x": x, "y": y, "z": z, "type": kind} for x, y, z, kind in waypoints
        ])

    def test_empty_route_waits(self):
        result = cavebot.CavebotWalker(self.otmm, []).step((1000, 2000, 7), 0.0, lambda dx, dy: True)
        self.assertEqual(result[0], "wait")

    def test_clicks_farthest_visible_tile(self):
        walker = self.walker((1010, 2000, 7, "walk"))
        visible = lambda dx, dy: abs(dx) <= 4 and abs(dy) <= 4
        kind, dx, dy, _message = walker.step((1000, 2000, 7), 0.0, visible)
        self.assertEqual(kind, "click")
        self.assertEqual((dx, dy), (4, 0))

    def test_walk_waypoint_reached_within_one_tile(self):
        walker = self.walker((1001, 2000, 7, "walk"), (1010, 2000, 7, "walk"))
        result = walker.step((1000, 2000, 7), 0.0, lambda dx, dy: True)
        self.assertEqual(result[0], "wait")
        self.assertEqual(walker.index, 1)

    def test_stand_waypoint_needs_exact_tile(self):
        walker = self.walker((1001, 2000, 7, "stand"), (1010, 2000, 7, "walk"))
        result = walker.step((1000, 2000, 7), 0.0, lambda dx, dy: True)
        self.assertEqual(result[0], "click")
        self.assertEqual(walker.index, 0)

    def test_ladder_action_is_retried_then_skipped(self):
        walker = self.walker((1000, 2000, 7, "ladder"), (1010, 2000, 7, "walk"))
        position = (1000, 2000, 7)
        self.assertEqual(walker.step(position, 0.0, lambda dx, dy: True)[:2], ("action", "ladder"))
        self.assertEqual(walker.step(position, 1.0, lambda dx, dy: True)[0], "wait")
        self.assertEqual(walker.step(position, 5.0, lambda dx, dy: True)[0], "action")
        self.assertEqual(walker.step(position, 10.0, lambda dx, dy: True)[0], "action")
        result = walker.step(position, 15.0, lambda dx, dy: True)
        self.assertEqual(result[0], "wait")
        self.assertEqual(walker.index, 1)

    def test_floor_change_jumps_to_waypoint_on_new_floor(self):
        self.otmm.floors[8] = self.otmm.floors[7]
        walker = self.walker((1000, 2000, 7, "ladder"), (1005, 2005, 8, "walk"))
        result = walker.step((1000, 2000, 8), 0.0, lambda dx, dy: True)
        self.assertEqual(result[0], "wait")
        self.assertEqual(walker.index, 1)

    def test_unreachable_waypoint_is_skipped(self):
        for y in range(2000, 2020):
            set_flags(self.otmm, 1005, y, 7, FLAG_SEEN | FLAG_NOT_WALKABLE)
        walker = self.walker((1010, 2000, 7, "walk"), (1001, 2001, 7, "walk"))
        result = walker.step((1000, 2000, 7), 0.0, lambda dx, dy: True)
        self.assertEqual(result[0], "wait")
        self.assertEqual(walker.index, 1)

    def test_waypoint_without_progress_is_skipped_after_20_s(self):
        walker = self.walker((1010, 2000, 7, "walk"), (1001, 2001, 7, "walk"))
        position = (1000, 2000, 7)
        self.assertEqual(walker.step(position, 0.0, lambda dx, dy: True)[0], "click")
        walker.step(position, 21.0, lambda dx, dy: True)
        self.assertEqual(walker.index, 1)


class ProfileTest(unittest.TestCase):
    def test_load_profile_drops_invalid_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cavebot.json"
            path.write_text(json.dumps({
                "waypoints": [
                    {"x": 1, "y": 2, "z": 7, "type": "rope"},
                    {"x": 1, "y": 2, "z": 7, "type": "teleport"},
                    {"x": "zła", "y": 2, "z": 7},
                    {"y": 2, "z": 7},
                ],
                "monsters": ["Rat", "  ", "Larva"],
                "ignored": ["RAT"],
                "monster_modes": {"Larva": "stand", "Rat": "fly"},
                "player_center": [10, 20],
                "rope_slot": [1, 2, 3],
            }), encoding="utf-8")
            profile = cavebot.load_profile(path)
        self.assertEqual(profile["waypoints"], [
            {"x": 1, "y": 2, "z": 7, "type": "rope"},
            {"x": 1, "y": 2, "z": 7, "type": "walk"},
        ])
        self.assertEqual(profile["monsters"], ["Rat", "Larva"])
        self.assertEqual(profile["ignored"], ["rat"])
        self.assertEqual(profile["monster_modes"], {"larva": "stand"})
        self.assertEqual(profile["player_center"], [10, 20])
        self.assertIsNone(profile["rope_slot"])

    def test_loot_immediately_defaults_on_and_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cavebot.json"
            path.write_text("{}", encoding="utf-8")
            self.assertTrue(cavebot.load_profile(path)["loot_immediately"])
            path.write_text(json.dumps({"loot_immediately": False}), encoding="utf-8")
            self.assertFalse(cavebot.load_profile(path)["loot_immediately"])
        self.assertIn("loot_immediately", cavebot.PROFILE_KEYS)

    def test_missing_or_broken_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cavebot.json"
            self.assertEqual(cavebot.load_profile(path)["waypoints"], [])
            path.write_text("{nie json", encoding="utf-8")
            self.assertTrue(cavebot.load_profile(path)["pause_on_battle"])

    def test_named_profile_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            original = cavebot.PROFILES_DIR
            cavebot.PROFILES_DIR = Path(folder)
            try:
                profile = cavebot.load_profile(Path(folder) / "brak.json")
                profile["waypoints"] = [{"x": 5, "y": 6, "z": 7, "type": "stand"}]
                profile["monsters"] = ["Larva"]
                safe = cavebot.save_named_profile('Cała/trasa:"larvy"', profile)
                self.assertEqual(safe, "Całatrasalarvy")
                self.assertEqual(cavebot.list_profiles(), ["Całatrasalarvy"])
                loaded = cavebot.load_named_profile(safe)
                self.assertEqual(loaded["waypoints"], profile["waypoints"])
                self.assertEqual(loaded["monsters"], ["Larva"])
                self.assertNotIn("human", loaded)
                cavebot.delete_named_profile(safe)
                self.assertEqual(cavebot.list_profiles(), [])
                with self.assertRaises(ValueError):
                    cavebot.save_named_profile(' /:* ', profile)
            finally:
                cavebot.PROFILES_DIR = original


if __name__ == "__main__":
    unittest.main()
