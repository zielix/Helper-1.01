"""Testy logiki oglądania ciał (bez klikania i zrzutów)."""

import unittest
from unittest import mock

import numpy

from retronic_bot import corpse
from retronic_bot.creatures import PLAYER_TILE


class CorpseOffsetTest(unittest.TestCase):
    def test_world_position_wins_on_same_floor(self):
        # Postać zrobiła krok w prawo po zabiciu celu.
        self.assertEqual(corpse.corpse_offset((105, 200, 7), (101, 200, 7), (5, 0)), (4, 0))

    def test_fallback_on_other_floor_or_unknown_position(self):
        self.assertEqual(corpse.corpse_offset((105, 200, 7), (101, 200, 8), (5, 0)), (5, 0))
        self.assertEqual(corpse.corpse_offset((105, 200, 7), None, (5, 0)), (5, 0))
        self.assertEqual(corpse.corpse_offset(None, (101, 200, 7), [1, -1]), (1, -1))


class ClickOffsetsTest(unittest.TestCase):
    def test_world_tile_first_then_screen_tile(self):
        self.assertEqual(corpse.click_offsets((102, 100, 7), (100, 100, 7), (1, 1)), [(2, 0), (1, 1)])

    def test_same_tile_once_and_player_tile_never_as_retry(self):
        self.assertEqual(corpse.click_offsets((101, 100, 7), (100, 100, 7), (1, 0)), [(1, 0)])
        self.assertEqual(corpse.click_offsets((101, 100, 7), (100, 100, 7), (0, 0)), [(1, 0)])

    def test_tiles_outside_view_are_dropped(self):
        self.assertEqual(corpse.click_offsets((120, 100, 7), (100, 100, 7), (1, 0)), [(1, 0)])
        self.assertEqual(corpse.click_offsets((120, 100, 7), (100, 100, 7), (0, 0)), [])


class ScreenFirstTest(unittest.TestCase):
    def test_fresh_screen_tile_goes_first(self):
        # Zabicie właśnie wykryte: pole z mapy gry przed polem ze spóźnionej minimapy.
        self.assertEqual(corpse.click_offsets((102, 100, 7), (100, 100, 7), (1, 1), screen_first=True),
                         [(1, 1), (2, 0)])
        self.assertEqual(corpse.click_offsets((102, 100, 7), (100, 100, 7), (1, 1)), [(2, 0), (1, 1)])
        # (0, 0) to tylko zastępcza wartość — pola postaci nie klikamy jako pierwszego.
        self.assertEqual(corpse.click_offsets((102, 100, 7), (100, 100, 7), (0, 0), screen_first=True),
                         [(2, 0)])


class TileClickPointTest(unittest.TestCase):
    def test_player_tile_center(self):
        view = (100, 50, 100 + 15 * 64, 50 + 11 * 64)
        x, y = corpse.tile_click_point(view, 64, 0, 0)
        self.assertEqual(x, int(100 + (PLAYER_TILE[0] + 0.5) * 64))
        self.assertEqual(y, int(50 + (PLAYER_TILE[1] + 0.5) * 64))

    def test_point_is_clamped_to_game_view(self):
        view = (100, 50, 1060, 754)
        self.assertEqual(corpse.tile_click_point(view, 64, -50, -50), (101, 51))
        self.assertEqual(corpse.tile_click_point(view, 64, 50, 50), (1058, 752))


class SummaryMessageTest(unittest.TestCase):
    def test_new_patterns_are_listed_with_remainder(self):
        names = [f"Nowy {i}" for i in range(5)]
        message = corpse.summary_message(names, [], 5, True)
        self.assertEqual(message, "Ciało otwarte. Nowe wzorce (5): Nowy 0, Nowy 1, Nowy 2 i 2 kolejnych"
                                  " — nadaj im nazwy w karcie Loot.")

    def test_known_items_and_meat(self):
        message = corpse.summary_message([], ["Gold Coin"], 2, False, "Zjadłem Meat.")
        self.assertEqual(message, "Ciało: rozpoznane przedmioty: Gold Coin. Zjadłem Meat.")

    def test_recognised_but_not_looted_items_are_named(self):
        # Tak wyglądał przypadek z monetami jako „Nowy przedmiot 0002” bez „Zabieraj”.
        message = corpse.summary_message([], [], 1, True, skipped=["Nowy przedmiot 0002"])
        self.assertEqual(message, "Ciało otwarte. Pomijam (bez „Zabieraj”): Nowy przedmiot 0002.")

    def test_unknown_icons(self):
        self.assertIn("widzę 3 ikon", corpse.summary_message([], [], 3, False))
        self.assertIn("żadnej nie rozpoznałem", corpse.summary_message([], [], 3, True))

    def test_empty_corpse(self):
        self.assertEqual(corpse.summary_message([], [], 0, True), "Otwarto ciało; jest puste.")

    def test_cell_changed(self):
        cell = numpy.full((34, 34, 3), 22, dtype=numpy.uint8)
        cell[8:26, 8:26] = (40, 90, 200)                 # mięso
        cell[26:32, 26:31] = 230                         # cyfra „3”
        eaten = numpy.full_like(cell, 22)                # ostatnie mięso zjedzone
        self.assertTrue(corpse.cell_changed(cell, eaten))
        fewer = cell.copy()
        fewer[27:31, 26:28] = 22                         # „3” → „2”: zmienia się tylko cyfra
        self.assertTrue(corpse.cell_changed(cell, fewer))
        noisy = cell.copy()
        noisy[0, 0] = 120                                # pojedynczy piksel to nie zmiana
        self.assertFalse(corpse.cell_changed(cell, noisy))
        self.assertTrue(corpse.cell_changed(cell, None))


class InspectCorpseTest(unittest.TestCase):
    def test_inactive_client_does_not_click(self):
        with mock.patch.object(corpse, "foreground_client_bounds", return_value=None), \
                mock.patch.object(corpse, "send_right_click") as click:
            result = corpse.inspect_corpse(1, None, (1, 0), None)
        self.assertEqual(result, {"message": "Nie otworzyłem ciała: okno gry nie jest aktywne.",
                                  "new_patterns": [], "looted": [], "debug": None, "timing": None,
                                  "retry": False})
        click.assert_not_called()

    def test_live_creature_on_corpse_tile_blocks_click(self):
        frame = numpy.zeros((800, 1200, 4), dtype=numpy.uint8)
        with mock.patch.object(corpse, "foreground_client_bounds", return_value=(0, 0, 1200, 800)), \
                mock.patch.object(corpse, "capture_region", return_value=frame), \
                mock.patch.object(corpse, "find_mini_window_frames", return_value=(1.0, [])), \
                mock.patch.object(corpse, "_tesseract", return_value=None), \
                mock.patch.object(corpse, "locate_creatures", return_value=([{"dx": 1, "dy": 0}], True)), \
                mock.patch.object(corpse, "send_right_click") as click:
            result = corpse.inspect_corpse(1, None, (1, 0), None, cached_view=(0, 0, 960, 704))
        self.assertIn("żywa postać", result["message"])
        click.assert_not_called()

    def test_corpse_outside_game_view_is_skipped(self):
        frame = numpy.zeros((800, 1200, 4), dtype=numpy.uint8)
        with mock.patch.object(corpse, "foreground_client_bounds", return_value=(0, 0, 1200, 800)), \
                mock.patch.object(corpse, "capture_region", return_value=frame), \
                mock.patch.object(corpse, "find_mini_window_frames", return_value=(1.0, [])), \
                mock.patch.object(corpse, "_tesseract", return_value=None), \
                mock.patch.object(corpse, "send_right_click") as click:
            result = corpse.inspect_corpse(1, (120, 100, 7), (0, 0), (100, 100, 7),
                                           cached_view=(0, 0, 960, 704))
        self.assertIn("poza widokiem", result["message"])
        click.assert_not_called()

    def test_exceptions_become_message(self):
        with mock.patch.object(corpse, "foreground_client_bounds", side_effect=RuntimeError("boom")):
            result = corpse.inspect_corpse(1, None, (1, 0), None)
        self.assertEqual(result["message"], "Sprawdzanie ciała nie powiodło się: boom")


def frame(close, body, title=None):
    return {"close": close, "body": body, "button": None, "bounds": None, "title": title}


class CorpseWindowTest(unittest.TestCase):
    def test_corpse_titles(self):
        for title in ("Dead larva", "dead rat", "Slain Rotworm", "Remains of a ghoul", "Dead Larva 2"):
            self.assertTrue(corpse.is_corpse_title(title), title)
        for title in ("Skills", "VIP List", "Backpack", "Battle", "Bag", ""):
            self.assertFalse(corpse.is_corpse_title(title), title)

    def test_open_timeout_grows_with_distance(self):
        self.assertEqual(corpse.open_timeout(1, 0), corpse.OPEN_TIMEOUT)
        self.assertAlmostEqual(corpse.open_timeout(4, -2), corpse.OPEN_TIMEOUT + 3 * corpse.WALK_TIME_PER_TILE)

    def test_corpse_body_height_is_limited(self):
        self.assertEqual(corpse.corpse_body((10, 20, 200, 2000), 2), (10, 20, 200, 20 + 2 * corpse.MAX_CORPSE_HEIGHT))
        self.assertEqual(corpse.corpse_body((10, 20, 200, 90), 1), (10, 20, 200, 90))

    def test_pick_by_title_among_moved_windows(self):
        skills = frame((300, 40), (10, 50, 300, 900))
        dead = frame((300, 400), (10, 410, 300, 480))
        self.assertIs(corpse.pick_corpse_window([skills, dead], ["Skills", "Dead larva"]), dead)
        self.assertIsNone(corpse.pick_corpse_window([skills], ["Skills"]))

    def test_without_ocr_the_smallest_new_window_wins(self):
        skills = frame((300, 40), (10, 50, 300, 900))
        dead = frame((300, 400), (10, 410, 300, 480))
        self.assertIs(corpse.pick_corpse_window([skills, dead], None), dead)
        self.assertIsNone(corpse.pick_corpse_window([], None))


class InspectFlowTest(unittest.TestCase):
    """Przebieg _inspect na atrapach: okno ciała przesuwa okno Skills, a stare ciało jest otwarte."""

    def test_closes_old_corpse_then_finds_new_one_by_title(self):
        image = numpy.zeros((900, 1300, 4), dtype=numpy.uint8)
        old_corpse = frame((1290, 600), (1100, 610, 1290, 680), "Dead rat")
        skills = frame((1290, 40), (1100, 50, 1290, 200), "Skills")
        backpack = frame((1290, 300), (1100, 310, 1290, 450), "Backpack")
        moved_skills = frame((1290, 140), (1100, 150, 1290, 300), "Skills")
        new_corpse = frame((1290, 40), (1100, 50, 1290, 110), "Dead larva")
        frames = iter([
            (1.0, [skills, backpack, old_corpse]),   # przed kliknięciem
            (1.0, [skills, backpack]),               # po zamknięciu starego ciała
            (1.0, [new_corpse, moved_skills, backpack]),  # po kliknięciu
            (1.0, [new_corpse, moved_skills, backpack]),  # po ułożeniu się okien
        ])
        clicks = []
        with mock.patch.object(corpse, "foreground_client_bounds", return_value=(0, 0, 1300, 900)), \
                mock.patch.object(corpse, "capture_region", return_value=image), \
                mock.patch.object(corpse, "_tesseract", return_value="tesseract.exe"), \
                mock.patch.object(corpse, "find_mini_window_frames", side_effect=lambda *a, **k: next(frames)), \
                mock.patch.object(corpse, "read_titles",
                                  side_effect=lambda _i, frames, _s, _t: [f["title"] for f in frames]), \
                mock.patch.object(corpse, "locate_creatures", return_value=([], True)), \
                mock.patch.object(corpse, "send_right_click", side_effect=lambda *a: clicks.append(("R",) + a[1:]) or True), \
                mock.patch.object(corpse, "send_left_click", side_effect=lambda *a: clicks.append(("L",) + a[1:]) or True), \
                mock.patch.object(corpse, "find_slot_items", return_value=[]) as slots, \
                mock.patch.object(corpse, "load_patterns", return_value={}), \
                mock.patch.object(corpse, "save_debug_image", return_value=None), \
                mock.patch.object(corpse.time, "sleep"):
            result = corpse.inspect_corpse(1, (101, 100, 7), (0, 0), (100, 100, 7),
                                           cached_view=(0, 0, 960, 704))
        self.assertEqual(result["message"], "Otwarto ciało; jest puste.")
        self.assertIn("tytuły", result["timing"])
        self.assertEqual(clicks[0], ("L", 1290, 600))      # zamknięcie starego ciała
        self.assertEqual(clicks[1][0], "R")                 # otwarcie nowego
        self.assertEqual(clicks[-1], ("L", 1290, 40))       # zamknięcie nowego ciała
        self.assertEqual(slots.call_args.args[1], (1100, 50, 1290, 110))

    def run_meat(self, eaten_after):
        """Ciało z Meat (bez „Zabieraj”); slot znika po kliknięciu numer eaten_after (None — nigdy).

        Zwraca (komunikat, liczba kliknięć w mięso, wywołania save_debug_image).
        """
        image = numpy.zeros((900, 1300, 4), dtype=numpy.uint8)
        box = (1102, 52, 1136, 86)
        meat_cell = numpy.full((34, 34, 3), 150, dtype=numpy.uint8)
        image[52:86, 1102:1136, :3] = meat_cell
        eaten_image = image.copy()
        eaten_image[52:86, 1102:1136, :3] = 20
        skills = frame((1290, 300), (1100, 310, 1290, 450), "Skills")
        dead = frame((1290, 40), (1100, 50, 1290, 110), "Dead larva")
        frames = iter([(1.0, [skills]), (1.0, [dead, skills]), (1.0, [dead, skills])])
        checks = [eaten_image if eaten_after is not None and n >= eaten_after else image
                  for n in range(1, corpse.MEAT_ATTEMPTS + 1)]
        captures = iter([image, image, image] + checks)
        item = {"pattern": "m", "box": box, "center": (1119, 69), "cell": meat_cell, "crop": meat_cell}
        clicks = []
        with mock.patch.object(corpse, "foreground_client_bounds", return_value=(0, 0, 1300, 900)), \
                mock.patch.object(corpse, "capture_region", side_effect=lambda *a, **k: next(captures)), \
                mock.patch.object(corpse, "_tesseract", return_value="tesseract.exe"), \
                mock.patch.object(corpse, "find_mini_window_frames", side_effect=lambda *a, **k: next(frames)), \
                mock.patch.object(corpse, "read_titles",
                                  side_effect=lambda _i, fr, _s, _t: [f["title"] for f in fr]), \
                mock.patch.object(corpse, "locate_creatures", return_value=([], True)), \
                mock.patch.object(corpse, "send_right_click", side_effect=lambda *a: clicks.append(a[1:]) or True), \
                mock.patch.object(corpse, "send_left_click", return_value=True), \
                mock.patch.object(corpse, "find_slot_items", return_value=[item]), \
                mock.patch.object(corpse, "load_patterns",
                                  return_value={"m": {"name": "Meat", "enabled": False, "image": meat_cell}}), \
                mock.patch.object(corpse, "identify_items", side_effect=lambda items, _p: items), \
                mock.patch.object(corpse, "save_debug_image", return_value=None) as debug, \
                mock.patch.object(corpse.time, "sleep"):
            result = corpse.inspect_corpse(1, (101, 100, 7), (0, 0), (100, 100, 7),
                                           cached_view=(0, 0, 960, 704), use_meat=True)
        meat_clicks = clicks[1:]   # pierwszy prawy klik otwiera ciało
        self.assertTrue(all(click == (1119, 69) for click in meat_clicks))
        return result["message"], len(meat_clicks), debug.call_args_list

    def test_meat_is_eaten_even_without_loot_flag(self):
        message, clicks, debug = self.run_meat(eaten_after=1)
        self.assertIn("Zjadłem Meat.", message)
        self.assertEqual(clicks, 1)
        # Obraz „meat” z krzyżykiem w miejscu kliknięcia.
        self.assertEqual(debug[-1].kwargs, {"label": "meat", "marks": [(1119, 69)]})

    def test_second_click_after_pause_eats_meat(self):
        # Serwer odrzucił pierwsze użycie (za szybko po otwarciu ciała).
        message, clicks, _debug = self.run_meat(eaten_after=2)
        self.assertIn("Zjadłem Meat.", message)
        self.assertEqual(clicks, 2)

    def test_meat_left_after_all_attempts(self):
        message, clicks, _debug = self.run_meat(eaten_after=None)
        self.assertIn("Meat zostało w ciele po 2 kliknięciach", message)
        self.assertEqual(clicks, corpse.MEAT_ATTEMPTS)

    def test_window_that_never_appears(self):
        image = numpy.zeros((900, 1300, 4), dtype=numpy.uint8)
        skills = frame((1290, 40), (1100, 50, 1290, 200), "Skills")
        ticks = iter(range(1000))
        with mock.patch.object(corpse, "foreground_client_bounds", return_value=(0, 0, 1300, 900)), \
                mock.patch.object(corpse, "capture_region", return_value=image), \
                mock.patch.object(corpse, "_tesseract", return_value=None), \
                mock.patch.object(corpse, "find_mini_window_frames", return_value=(1.0, [skills])), \
                mock.patch.object(corpse, "locate_creatures", return_value=([], True)), \
                mock.patch.object(corpse, "send_right_click", return_value=True) as click, \
                mock.patch.object(corpse, "save_debug_image", return_value="miss.png") as debug, \
                mock.patch.object(corpse.time, "monotonic", side_effect=lambda: next(ticks) * 0.2), \
                mock.patch.object(corpse.time, "sleep"):
            result = corpse.inspect_corpse(1, (101, 100, 7), (0, 0), (100, 100, 7),
                                           cached_view=(0, 0, 960, 704))
        self.assertEqual(result["message"],
                         "Kliknąłem pole ciała (+1, +0), ale nie pojawiło się okno ciała.")
        click.assert_called_once()   # pola postaci (0, 0) nie klikamy
        self.assertEqual(result["debug"], "miss.png")
        self.assertEqual(debug.call_args.kwargs["label"], "miss")
        self.assertTrue(result["retry"])   # ciało wraca do kolejki na ponowną próbę po walce

    def test_second_click_on_screen_tile_when_minimap_lags(self):
        # Minimapa spóźniona o krok: ze świata wychodzi (+2, 0), a cel leżał na (+1, +1).
        image = numpy.zeros((900, 1300, 4), dtype=numpy.uint8)
        skills = frame((1290, 300), (1100, 310, 1290, 450), "Skills")
        dead = frame((1290, 40), (1100, 50, 1290, 110), "Dead larva")
        clicks, clock = [], {"now": 0.0}

        def sleep(seconds):
            clock["now"] += seconds

        def frames(*_a, **_k):
            return (1.0, [dead, skills]) if len(clicks) >= 2 else (1.0, [skills])

        with mock.patch.object(corpse, "foreground_client_bounds", return_value=(0, 0, 1300, 900)), \
                mock.patch.object(corpse, "capture_region", return_value=image), \
                mock.patch.object(corpse, "_tesseract", return_value="tesseract.exe"), \
                mock.patch.object(corpse, "find_mini_window_frames", side_effect=frames), \
                mock.patch.object(corpse, "read_titles",
                                  side_effect=lambda _i, fr, _s, _t: [f["title"] for f in fr]), \
                mock.patch.object(corpse, "locate_creatures", return_value=([], True)), \
                mock.patch.object(corpse, "send_right_click", side_effect=lambda *a: clicks.append(a[1:]) or True), \
                mock.patch.object(corpse, "send_left_click", return_value=True), \
                mock.patch.object(corpse, "find_slot_items", return_value=[]), \
                mock.patch.object(corpse, "load_patterns", return_value={}), \
                mock.patch.object(corpse, "save_debug_image", return_value=None), \
                mock.patch.object(corpse.time, "monotonic", side_effect=lambda: clock["now"]), \
                mock.patch.object(corpse.time, "sleep", side_effect=sleep):
            result = corpse.inspect_corpse(1, (102, 100, 7), (1, 1), (100, 100, 7),
                                           cached_view=(0, 0, 960, 704))
        self.assertEqual(result["message"], "Otwarto ciało; jest puste.")
        view, tile = (0, 0, 960, 704), corpse.tile_size((0, 0, 960, 704))
        self.assertEqual(clicks, [corpse.tile_click_point(view, tile, 2, 0),
                                  corpse.tile_click_point(view, tile, 1, 1)])

    def test_waits_while_walking_to_a_distant_corpse(self):
        # Ciało 4 pola dalej; postać idzie do niego 5 s, okno pojawia się dopiero potem.
        image = numpy.zeros((900, 1300, 4), dtype=numpy.uint8)
        skills = frame((1290, 300), (1100, 310, 1290, 450), "Skills")
        dead = frame((1290, 40), (1100, 50, 1290, 110), "Dead larva")
        clock = {"now": 0.0}

        def sleep(seconds):
            clock["now"] += seconds

        def frames(*_a, **_k):
            return (1.0, [dead, skills]) if clock["now"] >= 5.5 else (1.0, [skills])

        def player_now():
            # Krok co 1,2 s przez pierwsze 5 s, potem postać stoi przy ciele.
            return (100 + min(4, int(clock["now"] / 1.2)), 100, 7)

        with mock.patch.object(corpse, "foreground_client_bounds", return_value=(0, 0, 1300, 900)), \
                mock.patch.object(corpse, "capture_region", return_value=image), \
                mock.patch.object(corpse, "_tesseract", return_value="tesseract.exe"), \
                mock.patch.object(corpse, "find_mini_window_frames", side_effect=frames), \
                mock.patch.object(corpse, "read_titles",
                                  side_effect=lambda _i, fr, _s, _t: [f["title"] for f in fr]), \
                mock.patch.object(corpse, "locate_creatures", return_value=([], True)), \
                mock.patch.object(corpse, "send_right_click", return_value=True), \
                mock.patch.object(corpse, "send_left_click", return_value=True), \
                mock.patch.object(corpse, "find_slot_items", return_value=[]), \
                mock.patch.object(corpse, "load_patterns", return_value={}), \
                mock.patch.object(corpse, "save_debug_image", return_value=None), \
                mock.patch.object(corpse.time, "monotonic", side_effect=lambda: clock["now"]), \
                mock.patch.object(corpse.time, "sleep", side_effect=sleep):
            result = corpse.inspect_corpse(1, (104, 100, 7), (0, 0), (100, 100, 7),
                                           cached_view=(0, 0, 960, 704), player_now=player_now)
        self.assertEqual(result["message"], "Otwarto ciało; jest puste.")


class SearchTest(unittest.TestCase):
    def test_search_offsets_nearby_floor_within_reach(self):
        # Ciało wyliczone na (+1, 0); szukamy na wszystkich polach w zasięgu ręki postaci.
        floor = lambda world: world != (101, 99, 7)          # (+1, -1) to schody
        # Najbliższe wyliczonemu najpierw, własne pole postaci na końcu remisu;
        # samego pola ciała (już kliknięte) i schodów nie ma.
        self.assertEqual(corpse.search_offsets((1, 0), (100, 100, 7), floor),
                         [(1, 1), (0, 0), (0, -1), (0, 1), (-1, 0), (-1, -1), (-1, 1)])
        self.assertEqual(corpse.search_offsets((1, 0), (100, 100, 7), None), [])
        self.assertEqual(corpse.search_offsets((1, 0), None, floor), [])
        # Ciało wyliczone daleko (np. zabite z dystansu): pola przy postaci nic nie dadzą.
        self.assertEqual(corpse.search_offsets((5, 0), (100, 100, 7), floor), [])

    def test_open_ground_uses_map_flags(self):
        from retronic_bot.minimap import FLAG_NOT_PATHABLE, FLAG_SEEN

        class Map:
            def tile(self, x, y, z):
                return {(1, 1, 7): (0, FLAG_SEEN), (2, 1, 7): (0, FLAG_SEEN | FLAG_NOT_PATHABLE)}.get((x, y, z))

        self.assertTrue(corpse.open_ground(Map(), (1, 1, 7)))
        self.assertFalse(corpse.open_ground(Map(), (2, 1, 7)))   # schody, drabina, dziura
        self.assertFalse(corpse.open_ground(Map(), (3, 1, 7)))   # nieodkryte
        self.assertFalse(corpse.open_ground(None, (1, 1, 7)))

    def run_clicks(self, corpse_world, fallback, positions, open_at, open_tile=None):
        """Okno ciała pojawia się po kliknięciu numer open_at (None — nigdy); zwraca (wynik, kliknięte pola)."""
        image = numpy.zeros((900, 1300, 4), dtype=numpy.uint8)
        skills = frame((1290, 300), (1100, 310, 1290, 450), "Skills")
        dead = frame((1290, 40), (1100, 50, 1290, 110), "Dead larva")
        view, clicks, clock = (0, 0, 960, 704), [], {"now": 0.0}
        tile = corpse.tile_size(view)

        def sleep(seconds):
            clock["now"] += seconds

        def frames(*_a, **_k):
            return (1.0, [dead, skills]) if open_at is not None and len(clicks) >= open_at else (1.0, [skills])

        def player_now():
            return positions[min(len(clicks), len(positions) - 1)]

        with mock.patch.object(corpse, "foreground_client_bounds", return_value=(0, 0, 1300, 900)),                 mock.patch.object(corpse, "capture_region", return_value=image),                 mock.patch.object(corpse, "_tesseract", return_value="tesseract.exe"),                 mock.patch.object(corpse, "find_mini_window_frames", side_effect=frames),                 mock.patch.object(corpse, "read_titles",
                                  side_effect=lambda _i, fr, _s, _t: [f["title"] for f in fr]),                 mock.patch.object(corpse, "locate_creatures", return_value=([], True)),                 mock.patch.object(corpse, "send_right_click", side_effect=lambda *a: clicks.append(a[1:]) or True),                 mock.patch.object(corpse, "send_left_click", return_value=True),                 mock.patch.object(corpse, "find_slot_items", return_value=[]),                 mock.patch.object(corpse, "load_patterns", return_value={}),                 mock.patch.object(corpse, "save_debug_image", return_value=None),                 mock.patch.object(corpse.time, "monotonic", side_effect=lambda: clock["now"]),                 mock.patch.object(corpse.time, "sleep", side_effect=sleep):
            result = corpse.inspect_corpse(1, corpse_world, fallback, positions[0], cached_view=view,
                                           player_now=player_now, open_tile=open_tile)
        points = {corpse.tile_click_point(view, tile, dx, dy): (dx, dy)
                  for dx in range(-7, 8) for dy in range(-5, 6)}
        return result, [points[click] for click in clicks]

    def test_stale_screen_tile_is_dropped_after_walking(self):
        # Po pierwszym kliku postać podeszła o 2 pola: (+3, +1) z mapy gry liczono od starej
        # pozycji (dawniej bot klikał je względem nowej — dwa pola obok ciała), a pole
        # ciała ze świata już kliknięto.
        result, clicked = self.run_clicks((103, 100, 7), (3, 1), [(100, 100, 7), (102, 100, 7)], None)
        self.assertEqual(clicked, [(3, 0)])
        self.assertTrue(result["retry"])

    def test_searches_tiles_around_the_player(self):
        floor = lambda _world: True
        result, clicked = self.run_clicks((101, 100, 7), None, [(100, 100, 7)], 3, open_tile=floor)
        self.assertEqual(result["message"], "Otwarto ciało; jest puste.")
        self.assertEqual(clicked[0], (1, 0))
        self.assertEqual(len(clicked), 3)
        self.assertTrue(all(max(abs(dx - 1), abs(dy)) <= 1 for dx, dy in clicked))

    def test_corpse_on_the_far_side_of_the_player_is_found(self):
        # Z obliczeń (+1, 0), a ciało leżało na (-1, -1) (tak było w logu 2 XI).
        floor = lambda _world: True
        result, clicked = self.run_clicks((101, 100, 7), None, [(100, 100, 7)], None, open_tile=floor)
        self.assertIn((-1, -1), clicked)
        self.assertEqual(len(clicked), 9)          # pole ciała + 8 pól wokół postaci
        # Pola w zasięgu ręki klikamy co 0,6 s: całe szukanie trwa kilka sekund, nie kilkanaście.
        self.assertLessEqual(float(result["timing"].rsplit("razem ", 1)[1].rstrip("s")), 7.5)
        self.assertTrue(result["retry"])

    def test_without_map_only_the_computed_tile(self):
        result, clicked = self.run_clicks((101, 100, 7), None, [(100, 100, 7)], None)
        self.assertEqual(clicked, [(1, 0)])
        self.assertTrue(result["retry"])


class OpenWaitTest(unittest.TestCase):
    def test_minimum_without_position(self):
        wait = corpse.OpenWait(2.0, 0.0, None)
        self.assertFalse(wait.expired(1.9, None))
        self.assertTrue(wait.expired(2.0, None))

    def test_keeps_waiting_while_player_moves(self):
        wait = corpse.OpenWait(2.0, 0.0, (100, 100, 7))
        self.assertFalse(wait.expired(2.5, (101, 100, 7)))    # po minimum, ale postać właśnie zrobiła krok
        self.assertFalse(wait.expired(3.5, (101, 100, 7)))    # stoi dopiero 1 s
        self.assertTrue(wait.expired(2.5 + corpse.STILL_TIME, (101, 100, 7)))

    def test_standing_player_stops_after_minimum(self):
        wait = corpse.OpenWait(2.0, 0.0, (100, 100, 7))
        self.assertFalse(wait.expired(1.0, (100, 100, 7)))
        self.assertTrue(wait.expired(2.0, (100, 100, 7)))

    def test_hard_limit(self):
        wait = corpse.OpenWait(2.0, 0.0, (100, 100, 7))
        for step in range(1, 30):
            now = step * 0.5
            if wait.expired(now, (100 + step, 100, 7)):   # postać cały czas idzie
                break
        self.assertEqual(now, corpse.MAX_OPEN_WAIT)


class CorpseQueueTest(unittest.TestCase):
    def test_nearest_first_same_floor_and_expiry(self):
        queue = corpse.CorpseQueue(max_age=60)
        self.assertTrue(queue.add((105, 100, 7), 0.0, "Larva"))
        self.assertFalse(queue.add((105, 100, 7), 1.0, "Larva"))   # to samo pole
        queue.add((101, 101, 7), 2.0, "Larva")
        queue.add((100, 100, 8), 3.0, "Rat")
        player = (100, 100, 7)
        self.assertEqual(len(queue.pending(player, 10.0)), 2)
        self.assertEqual(queue.pop_nearest(player, 10.0)["world"], (101, 101, 7))
        self.assertEqual(queue.pop_nearest(player, 10.0)["world"], (105, 100, 7))
        self.assertIsNone(queue.pop_nearest(player, 10.0))
        self.assertEqual(len(queue), 1)                            # ciało na innym piętrze czeka
        self.assertIsNone(queue.pop_nearest(None, 10.0))
        self.assertEqual(queue.pending((100, 100, 8), 70.0), [])   # przeterminowane
        self.assertEqual(len(queue), 0)

    def test_retry_count_is_kept(self):
        queue = corpse.CorpseQueue()
        queue.add((101, 100, 7), 0.0, "Larva", tries=1)
        self.assertEqual(queue.pop_nearest((100, 100, 7), 1.0)["tries"], 1)


if __name__ == "__main__":
    unittest.main()
