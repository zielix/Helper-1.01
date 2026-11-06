"""Testy wyboru celu i decyzji o zmianie celu."""

import unittest

from retronic_bot import targeting


def row(name, hp=100, y=10, allowed=True, attacked=False):
    return {"key": targeting.normalize_name(name), "name": name, "hp": hp, "y": y,
            "allowed": allowed, "attacked": attacked}


def creature(dx, dy, hp=100, steps=0, player_like=False):
    return {"dx": dx, "dy": dy, "hp": hp, "steps": steps, "player_like": player_like}


_ORDER = ["rat", "larva", "cave rat"]


def PRIORITY(key):
    # Jak BotWindow.monster_priority: potwór spoza listy ma najniższy priorytet.
    return _ORDER.index(key) if key in _ORDER else len(_ORDER)


class SmallHelpersTest(unittest.TestCase):
    def test_normalize_name(self):
        self.assertEqual(targeting.normalize_name("  Cave   RAT "), "cave rat")
        self.assertIsNone(targeting.normalize_name(None))
        self.assertIsNone(targeting.normalize_name(""))

    def test_engage_wait_grows(self):
        self.assertEqual([targeting.engage_wait(n) for n in (1, 2, 3, 4)], [2.0, 3.0, 4.5, 6.75])

    def test_creature_at(self):
        near, far = creature(1, 0), creature(4, 4)
        self.assertIs(targeting.creature_at([far, near], (1, 1)), near)
        self.assertIsNone(targeting.creature_at([], (0, 0)))


class RankBattleRowsTest(unittest.TestCase):
    def test_no_allowed_rows(self):
        self.assertEqual(targeting.rank_candidates([row("Dog", allowed=False)], None, False, PRIORITY), ([], 0))

    def test_without_map_priority_then_hp_then_row(self):
        rows = [row("Larva", hp=90, y=10), row("Rat", hp=100, y=30), row("Rat", hp=40, y=50)]
        ranked, skipped = targeting.rank_candidates(rows, None, False, PRIORITY)
        self.assertEqual(skipped, 0)
        self.assertEqual([(c["key"], c["hp"]) for c in ranked], [("rat", 40), ("rat", 100), ("larva", 90)])
        self.assertTrue(all(c["via"] == "battle" for c in ranked))

    def test_priority_beats_distance_when_map_is_known(self):
        rows = [row("Rat", hp=100), row("Larva", hp=50), row("Dog", allowed=False, hp=70)]
        creatures = [creature(5, 0, hp=100, steps=6), creature(1, 0, hp=50, steps=1), creature(0, 2, hp=70)]
        ranked, _ = targeting.rank_candidates(rows, creatures, True, PRIORITY)
        self.assertEqual([c["key"] for c in ranked], ["rat", "larva"])
        self.assertEqual([c["steps"] for c in ranked], [6, 1])

    def test_same_priority_nearest_first(self):
        rows = [row("Rat", hp=100, y=10), row("Rat", hp=50, y=30), row("Dog", allowed=False, hp=70)]
        creatures = [creature(5, 0, hp=100, steps=6), creature(1, 0, hp=50, steps=1), creature(0, 2, hp=70)]
        ranked, _ = targeting.rank_candidates(rows, creatures, True, PRIORITY)
        self.assertEqual([c["steps"] for c in ranked], [1, 6])

    def test_unreachable_rows_are_skipped(self):
        rows = [row("Rat", hp=100), row("Larva", hp=50), row("Dog", allowed=False, hp=70)]
        creatures = [creature(5, 0, hp=100, steps=None), creature(1, 0, hp=50, steps=2), creature(0, 2, hp=70)]
        ranked, skipped = targeting.rank_candidates(rows, creatures, True, PRIORITY)
        self.assertEqual([c["key"] for c in ranked], ["larva"])
        self.assertEqual(skipped, 1)

    def test_everything_unreachable(self):
        rows = [row("Rat", hp=100), row("Dog", allowed=False, hp=10)]
        creatures = [creature(5, 0, hp=100, steps=None), creature(1, 0, hp=10, steps=None)]
        self.assertEqual(targeting.rank_candidates(rows, creatures, True, PRIORITY), ([], 1))

    def test_identical_bars_take_nearest_reachable(self):
        rows = [row("Rat", hp=100), row("Dog", allowed=False, hp=100)]
        creatures = [creature(3, 0, steps=None), creature(2, 0, steps=4), creature(1, 0, steps=2)]
        ranked, _ = targeting.rank_candidates(rows, creatures, True, PRIORITY)
        self.assertEqual(ranked[0]["steps"], 2)

    def test_suppressed_and_attacked_rows_are_left_out(self):
        attacked = row("Larva", attacked=True)
        rows = [row("Rat"), attacked, row("Cave Rat")]
        ranked, _ = targeting.rank_candidates(rows, None, False, PRIORITY, suppressed={"rat"})
        self.assertEqual([c["key"] for c in ranked], ["cave rat"])


class RankScreenTest(unittest.TestCase):
    def setUp(self):
        self.rows = [row("Rat", hp=100, y=10), row("Rat", hp=60, y=30)]
        self.creatures = [creature(3, 0, hp=100, steps=3), creature(1, 1, hp=60, steps=1)]

    def test_single_kind_matching_map_uses_screen(self):
        ranked, skipped = targeting.rank_candidates(self.rows, self.creatures, True, PRIORITY)
        self.assertEqual(skipped, 0)
        self.assertEqual([c["via"] for c in ranked], ["screen", "screen"])
        self.assertEqual([c["steps"] for c in ranked], [1, 3])
        self.assertEqual(ranked[0]["name"], "Rat")

    def test_attacked_creature_is_excluded(self):
        ranked, _ = targeting.rank_candidates(self.rows, self.creatures, True, PRIORITY, attacked_offset=(1, 1))
        self.assertEqual([(c["creature"]["dx"], c["creature"]["dy"]) for c in ranked], [(3, 0)])

    def test_unreachable_creatures_are_counted(self):
        self.creatures[0]["steps"] = None
        ranked, skipped = targeting.rank_candidates(self.rows, self.creatures, True, PRIORITY)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(skipped, 1)

    def test_falls_back_to_battle_when_screen_is_unsafe(self):
        cases = {
            "wyłączony po nieudanych kliknięciach": dict(allow_screen=False),
            "inny stwór w Battle": dict(rows=self.rows + [row("Dog", allowed=False)]),
            "dwa rodzaje potworów": dict(rows=[row("Rat"), row("Larva", hp=60)]),
            "liczba stworów się nie zgadza": dict(creatures=self.creatures[:1]),
            "postać podobna do gracza": dict(creatures=[self.creatures[0], creature(1, 1, hp=60, player_like=True)]),
            "typ zablokowany": dict(suppressed={"rat"}),
        }
        for label, override in cases.items():
            with self.subTest(label):
                args = dict(rows=self.rows, creatures=self.creatures, allow_screen=True, suppressed=())
                args.update(override)
                ranked, _ = targeting.rank_candidates(
                    args["rows"], args["creatures"], True, PRIORITY,
                    suppressed=args["suppressed"], allow_screen=args["allow_screen"],
                )
                self.assertTrue(all(c["via"] == "battle" for c in ranked), ranked)


class RetargetDecisionTest(unittest.TestCase):
    def test_track_health_restarts_on_damage_and_new_target(self):
        record, stalled = targeting.track_health(None, 10, 80, 100.0, 12)
        self.assertEqual((record["since"], stalled), (100.0, 0.0))
        same, stalled = targeting.track_health(record, 14, 82, 105.0, 12)
        self.assertIs(same, record)
        self.assertEqual(stalled, 5.0)
        damaged, stalled = targeting.track_health(record, 10, 70, 106.0, 12)
        self.assertIsNot(damaged, record)
        self.assertEqual(stalled, 0.0)
        moved, _ = targeting.track_health(record, 40, 80, 106.0, 12)
        self.assertIsNot(moved, record)
        healed, _ = targeting.track_health(record, 10, 90, 106.0, 12)
        self.assertIsNot(healed, record)

    def test_unreachable_since(self):
        screen = {"reach_known": True, "creatures": [creature(2, 0, steps=None), creature(-1, 0, steps=1)]}
        self.assertEqual(targeting.unreachable_since(screen, (2, 0), None, 50.0), 50.0)
        self.assertEqual(targeting.unreachable_since(screen, (2, 0), 45.0, 50.0), 45.0)
        self.assertIsNone(targeting.unreachable_since(screen, (-1, 0), 45.0, 50.0))
        self.assertIsNone(targeting.unreachable_since(screen, None, 45.0, 50.0))
        self.assertIsNone(targeting.unreachable_since(dict(screen, reach_known=False), (2, 0), 45.0, 50.0))
        self.assertIsNone(targeting.unreachable_since(None, (2, 0), 45.0, 50.0))

    def test_retarget_reason(self):
        self.assertIsNone(targeting.retarget_reason(None, 6.9, 100.0))
        self.assertIsNone(targeting.retarget_reason(98.6, 0.0, 100.0))
        self.assertIn("nieosiągalny", targeting.retarget_reason(98.5, 20.0, 100.0))
        self.assertEqual(targeting.retarget_reason(None, 7.2, 100.0), "nie traci HP od 7 s")

    def test_target_died(self):
        # Mapa gry pokazuje pole celu: puste = zabity, nawet przy 100% w ostatnim odczycie
        # (tak ginęły larwy w logu: „Atak potwierdzony (HP 100%)”, 2 s później koniec).
        self.assertTrue(targeting.target_died(100, True, False))
        self.assertTrue(targeting.target_died(None, True, False))
        self.assertFalse(targeting.target_died(35, True, True))    # stwór nadal stoi na polu
        # Ubyło potworów o tej nazwie w Battle: zginął, choć na jego pole wszedł następny.
        self.assertTrue(targeting.target_died(35, False, True))
        # Bez mapy: zniknął z Battle albo miał mało HP.
        self.assertTrue(targeting.target_died(90, False, None))
        self.assertTrue(targeting.target_died(60, True, None))
        self.assertFalse(targeting.target_died(85, True, None))

    def test_attack_status(self):
        self.assertEqual(targeting.attack_status("Rat", 50, 1.0), "Atakuję „Rat” · HP 50%")
        self.assertEqual(targeting.attack_status("Rat", None, 3.4), "Atakuję „Rat” · bez obrażeń od 3 s")

    def test_corpse_offset_from_screen(self):
        self.assertIsNone(targeting.corpse_offset_from_screen(None, 50))
        screen = {"square": [2, -1], "creatures": []}
        self.assertEqual(targeting.corpse_offset_from_screen(screen, 50), (2, -1))
        screen = {"square": None, "creatures": [creature(1, 0, hp=52), creature(3, 3, hp=90)]}
        self.assertEqual(targeting.corpse_offset_from_screen(screen, 50), (1, 0))
        screen["creatures"].append(creature(0, 1, hp=49))
        self.assertIsNone(targeting.corpse_offset_from_screen(screen, 50))
        self.assertIsNone(targeting.corpse_offset_from_screen(screen, None))


if __name__ == "__main__":
    unittest.main()
