"""Prosty interfejs graficzny bota."""

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import math
import os
import random
import threading
import time
from collections import Counter, deque
from pathlib import Path

from . import human
from .battle_window import (
    find_battle_window,
    find_mini_windows,
)
from .combat_mode import MODES as COMBAT_MODES, current_mode, find_combat_buttons
from .cavebot import (
    ACTION_TYPES,
    PROFILE_KEYS,
    WAYPOINT_TYPES,
    CavebotWalker,
    delete_named_profile,
    list_profiles,
    load_named_profile,
    load_profile,
    save_named_profile,
    save_profile,
    waypoint_text,
)
from .battle import (
    assign_row_names,
    attack_marker_pixels,
    capture_region,
    parse_battle_rows,
    extract_battle_name,
    read_name_crop,
    differs_from_empty,
    find_battle_templates,
    read_battle_names,
)
from .config import STATUS_PROCESS_ACCESS
from .corpse import CORPSE_TRIES, CorpseQueue, inspect_corpse, open_ground
from . import targeting
from . import fishing
from .creatures import (
    attack_square,
    find_game_view,
    locate_creatures,
    reach_steps,
    square_offset,
    tile_size,
)
from .controller import LightHackController
from .keyboard import foreground_process_id, send_spell, tap_arrow
from .mana import find_tesseract
from .memory import CloseHandle, GetExitCodeProcess
from .minimap import (
    UNKNOWN,
    MinimapTracker,
    OtmmMap,
    find_minimap_region,
    find_otmm_file,
)
from .mouse import (
    drag_item,
    drift_cursor,
    foreground_client_bounds,
    foreground_client_position,
    left_button_down,
    right_button_down,
    send_left_click,
    send_right_click,
    shift_key_down,
)
from .pickup import (
    find_ground_items,
    load_pickup_templates,
    remove_pickup_template,
    save_pickup_template,
)
from .loot_patterns import LOOT_DEBUG_DIR, load_patterns, remove_pattern, update_pattern
from .process import find_process
from .runemaker import (
    contains as image_contains,
    find_item,
    load_settings as load_automation_settings,
    load_template as load_item_template,
    read_vitals,
    save_settings as save_automation_settings,
    save_template as save_item_template,
    similarity,
    slot_crop,
)


APP_NAME = "Asystent"
APP_VERSION = "v0.1"

# Przybliżenia widoku mapy w bocie (piksele na pole przy skali 100%).
MAP_ZOOM_LEVELS = (1, 2, 3, 4, 6, 8)

# Powiększenie interfejsu Windows (1.0 = 100%, 2.0 = 200%); ustawia je main().
UI_SCALE = 1.0


def enable_dpi_awareness():
    """Turn on per-monitor DPI awareness before any window or screenshot exists.

    Bez tego okno startuje rozmyte, a po pierwszym zrzucie ekranu (mss włącza
    świadomość DPI) nagle kurczy się o powiększenie ekranu. Współrzędne myszy
    i zrzutów są wtedy od początku w fizycznych pikselach.
    """
    global UI_SCALE
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            return
    try:
        UI_SCALE = max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96)
    except (AttributeError, OSError):
        UI_SCALE = 1.0


# Co ile ms sprawdzamy czerwony kwadrat atakowanego potwora (szybkie wykrycie zabicia).
TARGET_WATCH_MS = 150


def px(value):
    """Scale a pixel distance (or a tuple of them) by the Windows UI zoom."""
    if isinstance(value, tuple):
        return tuple(px(item) for item in value)
    return int(round(value * UI_SCALE))


def _map_palette():
    import numpy

    codes = numpy.arange(256)
    palette = numpy.stack(
        [(codes // 36) % 6 * 51, (codes // 6) % 6 * 51, codes % 6 * 51], axis=1
    ).astype(numpy.uint8)
    palette[216:] = 0
    return palette


try:
    MAP_PALETTE_RGB = _map_palette()
except ImportError:
    MAP_PALETTE_RGB = None


# Ciemny motyw w stylu botów działających w kliencie (np. XyroBot).
THEME = {
    "bg": "#15131f",
    "panel": "#1e1b2b",
    "row": "#252236",
    "row_active": "#2f2b45",
    "border": "#34304a",
    "text": "#e6e3f0",
    "muted": "#9a96ad",
    "accent": "#8b6cf0",
    "on": "#3fbf7f",
    "on_bg": "#163a2a",
    "off": "#e05a5a",
    "off_bg": "#3a1a22",
}


def apply_theme(root):
    t = THEME
    root.configure(background=t["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        ".", background=t["bg"], foreground=t["text"], fieldbackground=t["row"],
        bordercolor=t["border"], darkcolor=t["panel"], lightcolor=t["panel"],
        troughcolor=t["panel"], focuscolor=t["accent"], selectbackground=t["accent"],
        selectforeground="white", insertcolor=t["text"], font=("Segoe UI", 10),
    )
    style.configure("TNotebook", background=t["bg"], borderwidth=0, tabmargins=(8, 8, 8, 0))
    style.configure("TNotebook.Tab", background=t["panel"], foreground=t["muted"],
                    padding=px((14, 6)), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", t["row"])],
              foreground=[("selected", t["text"])])
    style.configure("TButton", background=t["row"], foreground=t["text"], padding=px((8, 6)),
                    borderwidth=1)
    style.map("TButton", background=[("active", t["row_active"]), ("disabled", t["panel"])],
              foreground=[("disabled", t["muted"])])
    style.configure("TLabelframe", background=t["bg"], bordercolor=t["border"])
    style.configure("TLabelframe.Label", background=t["bg"], foreground=t["muted"])
    style.configure("TEntry", fieldbackground=t["row"], foreground=t["text"], padding=px(4))
    style.configure("TCombobox", fieldbackground=t["row"], background=t["row"],
                    foreground=t["text"], arrowcolor=t["text"])
    style.map("TCombobox", fieldbackground=[("readonly", t["row"])],
              foreground=[("readonly", t["text"])])
    root.option_add("*TCombobox*Listbox.background", t["row"])
    root.option_add("*TCombobox*Listbox.foreground", t["text"])
    style.configure("TCheckbutton", background=t["bg"], foreground=t["text"],
                    indicatorbackground=t["row"], indicatorforeground=t["accent"],
                    indicatorsize=px(14))
    style.map("TCheckbutton", background=[("active", t["bg"])])
    style.configure("Vertical.TScrollbar", background=t["panel"], troughcolor=t["bg"],
                    arrowcolor=t["muted"], bordercolor=t["bg"])
    style.configure("Muted.TLabel", foreground=t["muted"])
    style.configure("Section.TLabel", foreground=t["muted"], font=("Segoe UI", 9, "bold"))
    style.configure("Row.TFrame", background=t["row"])
    style.configure("Row.TLabel", background=t["row"], font=("Segoe UI", 10, "bold"))
    style.configure("Row.TButton", anchor="w", background=t["row"], padding=px((10, 7)),
                    font=("Segoe UI", 10, "bold"))
    for name, color, back in (("On", t["on"], t["on_bg"]), ("Off", t["off"], t["off_bg"])):
        style.configure(f"{name}.TButton", foreground=color, background=back,
                        bordercolor=color, padding=px((6, 3)), font=("Segoe UI", 9, "bold"))
        style.map(f"{name}.TButton", background=[("active", back)])
    style.configure("Bar.TFrame", background=t["panel"])
    style.configure("Card.TFrame", background=t["bg"])
    style.configure("Group.TFrame", background=t["bg"], bordercolor="#463f66", relief="solid",
                    borderwidth=1)
    style.configure("GroupTitle.TLabel", foreground="#b9a8ff", font=("Segoe UI", 10, "bold"))
    style.configure("CardTitle.TLabel", foreground=t["text"], font=("Segoe UI", 10, "bold"))
    style.configure("Tooltip.TLabel", background=t["row_active"], foreground=t["text"],
                    font=("Segoe UI", 9))
    style.configure("Info.TLabel", foreground=t["accent"], font=("Segoe UI", 10, "bold"))
    style.configure("BarOn.TLabel", background=t["panel"], foreground=t["on"],
                    font=("Segoe UI", 10, "bold"))
    style.configure("BarCaption.TLabel", background=t["panel"], foreground=t["muted"],
                    font=("Segoe UI", 8, "bold"))
    style.configure("BarValue.TLabel", background=t["panel"], foreground=t["text"],
                    font=("Segoe UI", 10, "bold"))
    style.configure("Stop.TButton", background=t["off_bg"], foreground=t["off"],
                    bordercolor=t["off"], font=("Segoe UI", 10, "bold"), padding=(14, 8))
    style.map("Stop.TButton", background=[("active", "#55202c")])


class _NoSwitch:
    """Zastępuje przełącznik tam, gdzie monitor Battle włącza się automatycznie."""

    def set_on(self, _on):
        pass


class PillButton(ttk.Button):
    """Przełącznik On/Off jak w botach działających w kliencie."""

    def __init__(self, parent, command, on=False):
        super().__init__(parent, command=command, width=5)
        self.set_on(on)

    def set_on(self, on):
        self.configure(text="On" if on else "Off", style="On.TButton" if on else "Off.TButton")


class BotWindow:
    def __init__(self, root):
        self.root = root
        self.controller = LightHackController()
        self.spell_after_id = None
        self.spell_handle = None
        self.spell_pid = None
        self.spell_text = ""
        self.spell_interval_min = 0
        self.spell_interval_max = 0
        self.food_position = None
        self.food_capture_after_id = None
        self.food_after_id = None
        self.food_handle = None
        self.food_pid = None
        self.food_interval_min = 0
        self.food_interval_max = 0
        self.food_right_was_down = False
        self.automation = load_automation_settings()
        self.rune_after_id = None
        self.rune_handle = None
        self.rune_pid = None
        self.rune_running = False          # Runemaker
        self.trainer_running = False       # Mana trainer
        self.runes_created = 0
        self.rune_cycle = None
        self.rune_failures = 0
        self.rune_no_blanks_until = 0.0
        self.rune_blank_template = load_item_template("blank_rune")
        self.mana_trainer_next_at = 0.0
        self.vitals = None
        self.vitals_window = None
        self.vitals_detect_state = None
        self.vitals_bar_width = 0
        self.vitals_ocr_at = 0.0
        self.vitals_misses = 0
        self.rune_screen_view = None
        self.point_capture_callback = None
        self.rune_battle_paused = False
        self.rune_battle_options = {
            "alarm": tk.BooleanVar(value=True),
            "move_left": tk.BooleanVar(value=True),
            "left_steps": tk.StringVar(value="2"),
            "return_right": tk.BooleanVar(value=True),
            "right_steps": tk.StringVar(value="2"),
            "pause_bot": tk.BooleanVar(value=False),
        }
        self.rune_battle_move_after_id = None
        self.battle_handle = None
        self.battle_pid = None
        self.battle_capture_after_id = None
        self.battle_capture_corner = None
        self.battle_capture_profile = None
        self.battle_left_was_down = False
        self.battle_profiles = {
            "exp": {"top_left": None, "bottom_right": None, "region": None},
            "runes": {"top_left": None, "bottom_right": None, "region": None},
        }
        self.battle_monitors = {
            key: {"after_id": None, "baseline": None, "present": False,
                  "candidate": None, "candidate_count": 0, "status": None,
                  "button": None}
            for key in self.battle_profiles
        }
        self.battle_profile_status = {}
        self.battle_capture_buttons = {}
        self.battle_attack_enabled = False
        self.battle_target_lock = None
        self.battle_target_lock_count = 0
        self.battle_target_absence_count = 0
        self.battle_target_count_candidate = None
        self.battle_target_count_candidate_hits = 0
        self.battle_next_target_scan_at = 0.0
        self.battle_template_dir = Path(__file__).resolve().parent.parent / "battle_templates"
        self.battle_template_manifest = self.battle_template_dir / "templates.json"
        self.battle_attack_log = self.battle_template_dir.parent / "battle_attack.log"
        self._last_battle_attack_log_message = None
        self.battle_templates = self.load_battle_templates()
        self.battle_active_templates = {}
        self.battle_ocr_fallback_names = set()
        self.battle_template_name_var = tk.StringVar()
        self.battle_template_capture_corner = None
        self.battle_template_capture_after_id = None
        self.battle_template_left_was_down = False
        self.battle_template_points = {"top_left": None, "bottom_right": None}
        self.minimap_settings_path = Path(__file__).resolve().parent.parent / "minimap_settings.json"
        self.minimap_settings = self.load_minimap_settings()
        self.minimap_map = None
        self.minimap_map_source = None
        self.minimap_map_checked = 0.0
        self.minimap_tracker = None
        self.minimap_handle = None
        self.minimap_pid = None
        self.minimap_after_id = None
        self.minimap_region = None
        self.minimap_failures = 0
        self.minimap_position = None
        self.map_view = None
        self.map_photo = None
        self.map_pan = None
        self.map_drag_start = None
        self.map_dragged = False
        self.map_width = px(420)
        self.map_height = px(330)
        self.map_resize_after_id = None
        self.cavebot_profile = load_profile()
        human.set_enabled(self.cavebot_profile["human"])
        self.cavebot_walker = None
        self.loot_inspection_running = False
        # Ciało otwierane w wątku roboczym (pole, nazwa, czas zabicia, próby) — do ponowienia.
        self.loot_current = None
        # STOP / F12 przerywa lootowanie w wątku roboczym między przeciągnięciami.
        self.loot_cancel = threading.Event()
        self.loot_last_targets = []
        self.target_corpse_offset = None
        self.target_corpse_world = None
        self.battle_detect_state = None
        self.battle_detect_callbacks = []
        self.battle_pending_target = None
        self.battle_attacking = False
        self.battle_marker_misses = 0
        self.battle_last_click_at = None
        self.battle_unconfirmed_clicks = 0
        self.reset_targeting_state()
        self.events = deque(maxlen=200)
        self.combat_buttons = None
        self.combat_detect_state = None
        self.combat_detect_retry_at = 0.0
        self.combat_checked_at = 0.0
        self.point_capture = None
        self.point_left_was_down = False
        self.f12_was_down = False
        self.learn_monster_active = False
        self.learn_left_was_down = False
        self.target_preview_photo = None
        self.pickup_handle = None
        self.pickup_pid = None
        self.pickup_after_id = None
        self.pickup_capture_after_id = None
        self.pickup_capture_target = None
        self.pickup_capture_buttons = {}
        self.pickup_left_was_down = False
        self.pickup_hand_position = (tuple(self.automation["trainer_hand"])
                                     if self.automation.get("trainer_hand") else None)
        self.pickup_view = None
        self.pickup_view_checked_at = -100.0
        self.pickup_area_points = {"top_left": None, "bottom_right": None}
        self.pickup_area = None
        self.pickup_template_points = {"top_left": None, "bottom_right": None}
        self.pickup_templates = load_pickup_templates()
        self.loot_patterns = load_patterns()
        self.loot_pattern_ids = []
        self.loot_pattern_selected = None
        self.pickup_interval_min = 0
        self.pickup_interval_max = 0
        self.pickup_threshold = 0.8
        self.pickup_count = 0
        self.pickup_last_attempt = None
        self.pickup_attempt_count = 0
        self.pickup_ignored_spots = {}
        self.fishing_after_id = None
        self.fishing_template = load_item_template("fish")
        self.fishing_view = None
        self.fishing_view_at = -100.0
        self.fishing_recent = deque(maxlen=4)
        self.fishing_casts = 0
        self.fishing_casts_since_stack = 0
        self.fishing_merges = 0
        self.fishing_full_crops = []
        self.fishing_verify = None

        apply_theme(root)
        root.title(f"{APP_NAME} {APP_VERSION}")
        height = min(px(940), root.winfo_screenheight() - px(80))
        width = min(px(1240), root.winfo_screenwidth() - px(40))
        root.geometry(f"{width}x{height}")
        root.minsize(px(1000), px(600))

        # Opcje ciał i lootu są częścią profilu cavebota, ale ustawia się je w karcie „Loot”.
        self.cavebot_inspect_corpses_var = tk.BooleanVar(value=self.cavebot_profile["inspect_corpses"])
        self.cavebot_learn_loot_var = tk.BooleanVar(value=self.cavebot_profile["learn_loot"])
        self.cavebot_use_meat_var = tk.BooleanVar(value=self.cavebot_profile["use_meat"])
        self.cavebot_loot_var = tk.BooleanVar(value=self.cavebot_profile["loot_items"])
        self.cavebot_loot_now_var = tk.BooleanVar(value=self.cavebot_profile["loot_immediately"])
        self.loot_history = deque(maxlen=12)
        self.loot_session_counts = Counter()
        self.loot_preview_photo = None

        notebook = ttk.Notebook(root)
        self.notebook = notebook
        self.tab_canvases = {}
        notebook.bind_all("<MouseWheel>", self.scroll_selected_tab, add="+")
        self.build_status_bar(root)
        notebook.pack(fill="both", expand=True)
        frame = self.add_scrollable_tab(notebook, "Panel")
        rune_frame = self.add_scrollable_tab(notebook, "Runemaker")
        cavebot_frame = self.add_scrollable_tab(notebook, "Cavebot")
        loot_frame = self.add_scrollable_tab(notebook, "Loot")
        pickup_frame = self.add_scrollable_tab(notebook, "Trainer")

        self.build_panel_tab(frame)
        self.build_runes_tab(rune_frame)
        self.build_cavebot_tab(cavebot_frame)
        self.build_loot_tab(loot_frame)
        self.build_pickup_tab(pickup_frame)
        # Pozycja z minimapy jest potrzebna mapie i cavebotowi, więc działa zawsze.
        self.start_minimap()
        self.update_status_bar()
        self.poll_hotkeys()
        self.add_event(f"{APP_NAME} {APP_VERSION} uruchomiony. F12 zatrzymuje wszystkie funkcje.")

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def add_scrollable_tab(self, notebook, title):
        """Create a tab whose complete contents remain reachable by scrolling."""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text=title)
        canvas = tk.Canvas(tab, highlightthickness=0, borderwidth=0, background=THEME["bg"])
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = ttk.Frame(canvas, padding=px(22))
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            lambda _event, c=canvas: c.configure(scrollregion=c.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event, c=canvas, item=window_id: c.itemconfigure(item, width=event.width),
        )
        self.tab_canvases[str(tab)] = canvas
        return content

    def scroll_selected_tab(self, event):
        """Route the Windows mouse wheel to the currently selected tab."""
        selected = self.notebook.select()
        canvas = self.tab_canvases.get(selected)
        if canvas is not None:
            canvas.yview_scroll(int(-event.delta / 120), "units")
            return "break"

    def toggle_light_hack(self):
        self.toggle_button.state(["disabled"])
        self.root.update_idletasks()
        try:
            if self.controller.enabled:
                result = self.controller.disable()
                self.toggle_button.set_on(False)
                if result == "process_closed":
                    self.status.set("Status: wyłączony; klient został zamknięty")
                else:
                    self.status.set("Status: wyłączony; przywrócono oryginalny kod")
            else:
                pid = self.controller.enable()
                self.toggle_button.set_on(True)
                self.status.set(f"Status: włączony (PID {pid})")
        except Exception as exc:
            messagebox.showerror("Nie udało się zmienić ustawienia", str(exc), parent=self.root)
        finally:
            self.toggle_button.state(["!disabled"])

    def on_close(self):
        self.cancel_battle_capture()
        self.cancel_battle_template_capture()
        for profile_key in self.battle_profiles:
            self.stop_battle_monitor(profile_key, update_status=False, resume_automations=False)
        self.stop_spell()
        self.stop_food()
        self.stop_pickup("Zbieranie amunicji: wyłączone")
        self.stop_fishing("Wędkowanie: wyłączone")
        self.stop_cavebot("Cavebot: wyłączony")
        self.stop_minimap("Śledzenie pozycji: wyłączone")
        self.stop_rune_making("Runemaker: wyłączony")
        self.stop_mana_trainer("Mana trainer: wyłączony")
        try:
            self.controller.close()
        except Exception as exc:
            messagebox.showerror(
                "Nie można bezpiecznie zamknąć", str(exc), parent=self.root
            )
            return
        self.root.destroy()

    def toggle_spell(self):
        if self.spell_after_id is not None:
            self.stop_spell()
            self.spell_status.set("Automat zaklęcia: wyłączony")
            return

        spell = self.spell_var.get().strip()
        if not spell:
            messagebox.showerror("Brak zaklęcia", "Wpisz treść zaklęcia.", parent=self.root)
            return
        if any(ord(char) < 32 or ord(char) > 0xFFFF for char in spell):
            messagebox.showerror(
                "Nieprawidłowe zaklęcie",
                "Zaklęcie nie może zawierać nowych linii ani znaków spoza obsługiwanego zakresu.",
                parent=self.root,
            )
            return
        try:
            interval_min = float(self.interval_min_var.get().replace(",", "."))
            interval_max = float(self.interval_max_var.get().replace(",", "."))
            if not math.isfinite(interval_min) or not math.isfinite(interval_max):
                raise ValueError("Wpisz poprawne wartości czasu.")
            if interval_min < 1 or interval_max < 1:
                raise ValueError("Obie wartości muszą wynosić co najmniej 1 sekundę.")
            if interval_min > interval_max:
                raise ValueError("Wartość „od” nie może być większa niż wartość „do”.")
        except ValueError as exc:
            messagebox.showerror(
                "Nieprawidłowy interwał",
                str(exc) if str(exc) else "Wpisz poprawny zakres czasu w sekundach.",
                parent=self.root,
            )
            return

        try:
            pid, handle, _base, _path = find_process(STATUS_PROCESS_ACCESS)
        except Exception as exc:
            messagebox.showerror("Błąd klienta", str(exc), parent=self.root)
            return
        if not handle:
            messagebox.showerror(
                "Nie znaleziono klienta",
                "Uruchom klienta RetronicDX przed włączeniem automatu.",
                parent=self.root,
            )
            return

        self.spell_handle = handle
        self.spell_pid = pid
        self.spell_text = spell
        self.spell_interval_min = interval_min
        self.spell_interval_max = interval_max
        self.spell_button.set_on(True)
        self.spell_status.set(
            "Automat włączony. Wróć do okna gry; odstęp jest losowany "
            "z ustawionego zakresu."
        )
        self.schedule_spell_tick()

    def cast_spell_tick(self):
        self.spell_after_id = None
        if self.spell_handle is None:
            return
        if self.other_bot_functions_paused():
            self.spell_after_id = self.root.after(250, self.cast_spell_tick)
            return
        exit_code = wt.DWORD()
        if not GetExitCodeProcess(self.spell_handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            self.stop_spell()
            self.spell_status.set("Automat zaklęcia: klient został zamknięty")
            return

        try:
            sent = send_spell(self.spell_text, self.spell_pid)
            self.schedule_spell_tick()
            if sent:
                self.spell_status.set(
                    f"Zaklęcie wysłano; następny losowy odstęp: {self.next_spell_delay:g} s."
                )
            else:
                self.spell_status.set(
                    f"Oczekuję na aktywne okno gry; kolejna próba za {self.next_spell_delay:g} s."
                )
        except Exception as exc:
            self.stop_spell()
            self.spell_status.set("Automat zaklęcia: zatrzymany z powodu błędu")
            messagebox.showerror("Błąd wysyłania zaklęcia", str(exc), parent=self.root)
            return

    def schedule_spell_tick(self):
        self.next_spell_delay = random.uniform(
            self.spell_interval_min, self.spell_interval_max
        )
        self.spell_after_id = self.root.after(
            max(1, int(self.next_spell_delay * 1000)), self.cast_spell_tick
        )

    def stop_spell(self):
        if self.spell_after_id is not None:
            self.root.after_cancel(self.spell_after_id)
            self.spell_after_id = None
        if self.spell_handle is not None:
            CloseHandle(self.spell_handle)
            self.spell_handle = None
        self.spell_pid = None
        self.spell_button.set_on(False)

    def toggle_food_capture(self):
        if self.food_capture_after_id is not None:
            self.root.after_cancel(self.food_capture_after_id)
            self.food_capture_after_id = None
            self.food_position_button.configure(text="Ustaw pozycję jedzenia")
            if self.food_handle is not None and self.food_position is None:
                CloseHandle(self.food_handle)
                self.food_handle = None
                self.food_pid = None
            self.food_status.set("Ustawianie pozycji anulowane.")
            return
        if self.food_after_id is not None:
            messagebox.showinfo(
                "Wyłącz automat", "Najpierw wyłącz automatyczne jedzenie.", parent=self.root
            )
            return

        if self.food_handle is None:
            try:
                pid, handle, _base, _path = find_process(STATUS_PROCESS_ACCESS)
            except Exception as exc:
                messagebox.showerror("Błąd klienta", str(exc), parent=self.root)
                return
            if not handle:
                messagebox.showerror(
                    "Nie znaleziono klienta",
                    "Uruchom klienta RetronicDX przed ustawieniem pozycji.",
                    parent=self.root,
                )
                return
            self.food_pid = pid
            self.food_handle = handle

        self.food_right_was_down = right_button_down()
        self.food_position_button.configure(text="Anuluj ustawianie pozycji")
        self.food_status.set(
            "Wróć do gry i kliknij prawym przyciskiem jedzenie. Kliknięcie użyje "
            "przedmiotu i zapisze jego pozycję."
        )
        self.poll_food_position()

    def poll_food_position(self):
        self.food_capture_after_id = None
        if self.food_handle is None:
            return
        exit_code = wt.DWORD()
        if not GetExitCodeProcess(self.food_handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            self.stop_food()
            self.food_status.set("Klient został zamknięty; pozycję trzeba ustawić ponownie.")
            return

        is_down = right_button_down()
        if is_down and not self.food_right_was_down:
            position = foreground_client_position(self.food_pid)
            if position is not None:
                self.food_position = position
                self.food_position_button.configure(text="Ustaw pozycję ponownie")
                self.food_status.set(
                    f"Pozycja zapisana: X={position[0]}, Y={position[1]} względem okna gry."
                )
                return
        self.food_right_was_down = is_down
        self.food_capture_after_id = self.root.after(15, self.poll_food_position)

    def toggle_food(self):
        if self.food_after_id is not None:
            self.stop_food()
            self.food_status.set("Automatyczne jedzenie: wyłączone")
            return
        if self.food_position is None:
            messagebox.showerror(
                "Brak pozycji", "Najpierw ustaw pozycję jedzenia w oknie gry.", parent=self.root
            )
            return
        try:
            interval_min = float(self.food_interval_min_var.get().replace(",", "."))
            interval_max = float(self.food_interval_max_var.get().replace(",", "."))
            if not math.isfinite(interval_min) or not math.isfinite(interval_max):
                raise ValueError("Wpisz poprawne wartości czasu.")
            if interval_min < 1 or interval_max < 1:
                raise ValueError("Obie wartości muszą wynosić co najmniej 1 sekundę.")
            if interval_min > interval_max:
                raise ValueError("Wartość „od” nie może być większa niż wartość „do”.")
        except ValueError as exc:
            messagebox.showerror("Nieprawidłowy zakres", str(exc), parent=self.root)
            return

        if self.food_handle is None:
            try:
                pid, handle, _base, _path = find_process(STATUS_PROCESS_ACCESS)
            except Exception as exc:
                messagebox.showerror("Błąd klienta", str(exc), parent=self.root)
                return
            if not handle:
                messagebox.showerror(
                    "Nie znaleziono klienta", "Uruchom klienta RetronicDX.", parent=self.root
                )
                return
            self.food_pid = pid
            self.food_handle = handle

        self.food_interval_min = interval_min
        self.food_interval_max = interval_max
        self.food_button.set_on(True)
        self.schedule_food_click()

    def schedule_food_click(self):
        self.next_food_delay = random.uniform(
            self.food_interval_min, self.food_interval_max
        )
        self.food_status.set(
            f"Automat włączony; następny losowy odstęp: {self.next_food_delay:g} s."
        )
        self.food_after_id = self.root.after(
            max(1, int(self.next_food_delay * 1000)), self.food_click_tick
        )

    def food_click_tick(self):
        self.food_after_id = None
        if self.food_handle is None or self.food_position is None:
            return
        if self.other_bot_functions_paused():
            self.food_after_id = self.root.after(250, self.food_click_tick)
            return
        exit_code = wt.DWORD()
        if not GetExitCodeProcess(self.food_handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            self.stop_food()
            self.food_status.set("Automatyczne jedzenie: klient został zamknięty")
            return

        try:
            clicked = send_right_click(
                self.food_pid, self.food_position[0], self.food_position[1]
            )
            self.schedule_food_click()
            if not clicked:
                self.food_status.set(
                    f"Oczekuję na aktywne okno gry; kolejna próba za {self.next_food_delay:g} s."
                )
        except Exception as exc:
            self.stop_food()
            self.food_status.set("Automatyczne jedzenie: zatrzymane z powodu błędu")
            messagebox.showerror("Błąd klikania jedzenia", str(exc), parent=self.root)

    def stop_food(self):
        if self.food_capture_after_id is not None:
            self.root.after_cancel(self.food_capture_after_id)
            self.food_capture_after_id = None
        if self.food_after_id is not None:
            self.root.after_cancel(self.food_after_id)
            self.food_after_id = None
        if self.food_handle is not None:
            CloseHandle(self.food_handle)
            self.food_handle = None
        self.food_pid = None
        self.food_position_button.configure(text="Ustaw pozycję jedzenia")
        self.food_button.set_on(False)

    def load_minimap_settings(self):
        """Read the saved tracking switch, map zoom and center correction."""
        defaults = {"enabled": True, "zoom": 4, "offset": [0, 0]}
        try:
            saved = json.loads(self.minimap_settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return defaults
        if isinstance(saved, dict):
            defaults.update({key: saved[key] for key in defaults if key in saved})
        if defaults["zoom"] not in MAP_ZOOM_LEVELS:
            defaults["zoom"] = 4
        return defaults

    def save_minimap_settings(self):
        try:
            self.minimap_settings_path.write_text(
                json.dumps(self.minimap_settings, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            self.minimap_status.set(f"Nie udało się zapisać ustawień mapy: {exc}")

    def build_cavebot_tab(self, parent):
        # Nagłówek w jednej linii: tytuł, profil i tryb Human — mniej przewijania.
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=px((0, 10)))
        ttk.Label(header, text="Cavebot", font=("Segoe UI", 16, "bold")).pack(side="left")
        profile_row = ttk.Frame(header, style="Row.TFrame", padding=px((10, 5)))
        profile_row.pack(side="left", padx=px((24, 0)))
        ttk.Label(profile_row, text="Profil", style="Row.TLabel").pack(side="left", padx=px((0, 8)))
        self.profile_var = tk.StringVar(value=self.cavebot_profile.get("profile", ""))
        self.profile_box = ttk.Combobox(
            profile_row, textvariable=self.profile_var, values=list_profiles(), state="readonly", width=20
        )
        self.profile_box.pack(side="left")
        for label, command in (
            ("Wczytaj", self.load_selected_profile),
            ("Zapisz jako…", self.save_profile_as),
            ("Usuń", self.delete_selected_profile),
        ):
            ttk.Button(profile_row, text=label, command=command).pack(side="left", padx=px((6, 0)))
        self.add_tooltip(profile_row, "Profil to trasa (waypointy), lista atakowanych potworów, "
                                      "ignorowane potwory i opcje, zapisane pod nazwą w folderze profiles/.")
        human_row = ttk.Frame(header, style="Row.TFrame", padding=px((10, 5)))
        human_row.pack(side="right")
        ttk.Label(human_row, text="Tryb Human", style="Row.TLabel").pack(side="left", padx=px((0, 10)))
        self.human_pill = PillButton(human_row, self.toggle_human, on=human.enabled())
        self.human_pill.pack(side="left")
        self.add_info(human_row, "Tryb Human: kursor wykonuje niedokładny ruch z poprawkami zamiast "
                                 "skoku, kliknięcia trafiają w losowy punkt, reakcje mają nieregularne "
                                 "opóźnienia, a cavebot robi czasem krótkie przerwy. Dotyczy wszystkich "
                                 "funkcji bota.")

        route, map_column, targeting = self.add_columns(parent, weights=(4, 5, 4))
        self.build_cavebot_column(route)
        self.build_map_column(map_column)
        self.build_targeting_column(targeting)
        self.draw_map()

    def build_cavebot_column(self, parent):
        wrap = 320
        group = self.add_group(parent, "Cavebot")
        self.cavebot_pill = self.add_switch_row(group, "Chodzenie po trasie", self.toggle_cavebot)
        self.cavebot_status = tk.StringVar(value="Cavebot: wyłączony")
        self.add_status_label(group, self.cavebot_status, wrap=wrap)
        self.minimap_status = tk.StringVar(value="Pozycja: szukam minimapy…")
        self.add_status_label(group, self.minimap_status, wrap=wrap)
        self.cavebot_pause_var = tk.BooleanVar(value=self.cavebot_profile["pause_on_battle"])
        ttk.Checkbutton(
            group, text="Czekaj na koniec walki",
            variable=self.cavebot_pause_var, command=self.on_cavebot_pause_changed,
        ).pack(anchor="w", pady=px((8, 0)))
        self.add_tooltip(
            group.winfo_children()[-1],
            "Z włączonym atakiem cavebot stoi, gdy postać bije cel albo w zasięgu jest potwór z listy; "
            "potwory nieosiągalne nie zatrzymują trasy. Bez ataku czeka, aż Battle się opróżni.",
        )
        self.cavebot_loot_summary = tk.StringVar(value=self.loot_summary_text())
        ttk.Label(group, textvariable=self.cavebot_loot_summary, style="Muted.TLabel",
                  wraplength=px(wrap)).pack(anchor="w", pady=px((6, 0)))

        group = self.add_group(
            parent, "Waypointy",
            info="Lewy klik w mapę dodaje waypoint za zaznaczonym (albo na końcu), prawy usuwa "
                 "najbliższy. „Idź” wystarczy minąć o pole, „Stój” wymaga wejścia dokładnie na pole "
                 "— używaj go na schodach i dziurach.",
        )
        self.waypoint_list = self.make_listbox(group, height=11)
        self.waypoint_list.bind("<<ListboxSelect>>", lambda _event: self.draw_map())
        buttons = ttk.Frame(group)
        buttons.pack(fill="x", pady=px((6, 0)))
        for label, command in (
            ("+ Tu stoję", self.add_waypoint_at_player),
            ("▲", lambda: self.move_selected_waypoint(-1)),
            ("▼", lambda: self.move_selected_waypoint(1)),
            ("Usuń", self.remove_selected_waypoint),
        ):
            ttk.Button(buttons, text=label, command=command, width=3 if len(label) == 1 else None).pack(
                side="left", fill="x", expand=label.startswith("+"), padx=px((0, 4))
            )
        options = ttk.Frame(group)
        options.pack(fill="x", pady=px((8, 0)))
        ttk.Label(options, text="Nowy waypoint:").pack(side="left")
        self.waypoint_type_var = tk.StringVar(
            value=WAYPOINT_TYPES[self.cavebot_profile["waypoint_type"]]
        )
        type_box = ttk.Combobox(
            options, textvariable=self.waypoint_type_var, values=list(WAYPOINT_TYPES.values()),
            state="readonly", width=8,
        )
        type_box.pack(side="left", padx=px((6, 0)))
        type_box.bind("<<ComboboxSelected>>", lambda _event: self.save_cavebot_profile())
        ttk.Button(options, text="Wyczyść trasę", command=self.clear_waypoints).pack(side="right")
        actions = self.add_collapsible(group, "Lina i drabina — ustawienia")
        ttk.Label(
            actions,
            text="Waypoint „Drabina”: bot staje na polu i klika prawym w swoją postać (Use). "
                 "„Lina”: prawy klik na linie w plecaku, potem lewy na postać.",
            style="Muted.TLabel", wraplength=px(300),
        ).pack(anchor="w")
        for label, key, where in (
            ("Ustaw środek postaci", "player_center", "na swojej postaci"),
            ("Ustaw linę w plecaku", "rope_slot", "na linie w plecaku"),
        ):
            ttk.Button(actions, text=label, command=lambda k=key, w=where: self.start_point_capture(k, w)).pack(
                fill="x", pady=px((6, 0))
            )
        self.action_points_status = tk.StringVar(value=self.action_points_text())
        self.add_status_label(actions, self.action_points_status, wrap=300)
        self.refresh_waypoint_list()

    def build_map_column(self, parent):
        group = self.add_group(
            parent, "Mapa",
            info="Mapa pochodzi z pliku minimapy klienta (.otmm). Bot chodzi, klikając w minimapę "
                 "klienta najdalsze widoczne pole wyznaczonej drogi; klient sam prowadzi postać. "
                 "Pozycja jest liczona ze zrzutu minimapy, bez czytania pamięci.",
        )
        toolbar = ttk.Frame(group)
        toolbar.pack(fill="x", pady=px((0, 6)))
        for label, command in (
            ("▲ Piętro", lambda: self.change_map_floor(-1)),
            ("▼ Piętro", lambda: self.change_map_floor(1)),
            ("⌖ Do postaci", self.center_map_on_player),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side="left", padx=px((0, 4)))
        self.map_floor_label = tk.StringVar(value="")
        ttk.Label(toolbar, textvariable=self.map_floor_label, style="Muted.TLabel").pack(side="right")
        self.map_canvas = tk.Canvas(
            group, width=self.map_width, height=self.map_height, background="black",
            highlightthickness=1, highlightbackground=THEME["border"], cursor="crosshair",
        )
        self.map_canvas.pack(fill="x")
        self.map_canvas.bind("<Configure>", self.on_map_resize)
        self.map_canvas.bind("<MouseWheel>", self.zoom_map)
        self.map_canvas.bind("<Motion>", self.map_hover)
        self.map_canvas.bind("<Leave>", lambda _event: self.map_hover_status.set(self.map_help_text))
        self.map_canvas.bind("<ButtonPress-1>", self.map_press)
        self.map_canvas.bind("<B1-Motion>", self.map_drag)
        self.map_canvas.bind("<ButtonRelease-1>", self.map_release)
        self.map_canvas.bind("<Button-3>", self.map_remove_waypoint)
        self.map_help_text = "Lewy: dodaj · prawy: usuń · przeciągnij: przesuń · kółko: zoom"
        self.map_hover_status = tk.StringVar(value=self.map_help_text)
        ttk.Label(group, textvariable=self.map_hover_status, style="Muted.TLabel").pack(
            anchor="w", pady=px((4, 0))
        )
        # Śledzenie pozycji działa zawsze; zmienna zostaje dla zgodności z resztą kodu.
        self.minimap_enabled_var = tk.BooleanVar(value=True)

    def on_map_resize(self, event):
        """Fit the map to its column; redraw once the size settles."""
        width = max(px(160), event.width - 2)
        if width == self.map_width:
            return
        self.map_width = width
        if self.map_resize_after_id is not None:
            self.root.after_cancel(self.map_resize_after_id)
        self.map_resize_after_id = self.root.after(60, self.redraw_map_after_resize)

    def redraw_map_after_resize(self):
        self.map_resize_after_id = None
        self.draw_map()

    def build_targeting_column(self, parent):
        wrap = 320
        group = self.add_group(
            parent, "Targeting",
            info="Kolejność na liście to priorytet: bot atakuje najpierw potwora wyżej. "
                 "„+ Dodaj z Battle”: kliknij przycisk, wróć do gry i kliknij potwora w oknie Battle — "
                 "bot zapisze wzorzec jego nazwy (pewniejsze niż OCR). „Ignoruj” wyłącza potwora "
                 "z ataku bez usuwania go z listy.",
        )
        self.battle_attack_button = self.add_switch_row(
            group, "Atak potworów z listy", self.toggle_battle_attack
        )
        self.battle_monsters_var = tk.StringVar(value=", ".join(self.cavebot_profile["monsters"]))
        self.battle_monsters_var.trace_add("write", lambda *_args: self.on_monsters_changed())
        self.learn_button = ttk.Button(
            group, text="+ Dodaj z Battle (kliknij potwora w grze)", command=self.toggle_learn_monster
        )
        self.learn_button.pack(fill="x", pady=px((8, 0)))
        self.learn_status = tk.StringVar(value="Kliknij przycisk, potem potwora w oknie Battle.")
        self.add_status_label(group, self.learn_status, wrap=wrap)
        self.target_preview = ttk.Label(group)
        self.target_preview.pack(anchor="w")
        self.target_list = self.make_listbox(group, height=6)
        # Dwa rzędy po 2–3 przyciski: w kolumnie z trzech pięć się nie mieści.
        for row_buttons in (
            (("▲", lambda: self.move_monster(-1)), ("▼", lambda: self.move_monster(1)),
             ("Goń / Stój", self.toggle_monster_mode)),
            (("Ignoruj", self.toggle_ignore_monster), ("Usuń", self.remove_monster)),
        ):
            target_buttons = ttk.Frame(group)
            target_buttons.pack(fill="x", pady=px((6, 0)))
            for label, command in row_buttons:
                ttk.Button(target_buttons, text=label, command=command,
                           width=3 if len(label) == 1 else None).pack(
                    side="left", fill="x", expand=len(label) > 1, padx=px((0, 4))
                )
        add_row = ttk.Frame(group)
        add_row.pack(fill="x", pady=px((6, 0)))
        self.monster_name_var = tk.StringVar()
        entry = ttk.Entry(add_row, textvariable=self.monster_name_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self.add_monster())
        ttk.Button(add_row, text="Dodaj nazwę", command=self.add_monster).pack(side="left", padx=px((6, 0)))
        self.add_tooltip(entry, "Dodaje potwora bez wzorca — rozpoznawanie samym OCR, mniej pewne. "
                                "Wpisana tu nazwa poprawia też nazwę przy „+ Dodaj z Battle”.")
        self.refresh_target_list()

        group = self.add_group(parent, "Okno Battle")
        self.battle_window_status = tk.StringVar(
            value="Bot znajdzie okno Battle sam po włączeniu ataku lub cavebota."
        )
        self.add_status_label(group, self.battle_window_status, wrap=wrap)
        ttk.Button(group, text="Znajdź okno Battle teraz", command=self.detect_battle_window).pack(
            fill="x", pady=px((6, 0))
        )
        self.add_battle_profile_controls(group, "exp", "Wykrywanie Battle", switch=False)

        editor = self.add_collapsible(group, "Ręczny wzorzec (awaryjnie)")
        ttk.Label(
            editor,
            text="Wpisz nazwę i zaznacz w grze lewy górny oraz prawy dolny róg samej nazwy w Battle.",
            style="Muted.TLabel", wraplength=px(360),
        ).pack(anchor="w", pady=px((0, 5)))
        ttk.Entry(editor, textvariable=self.battle_template_name_var).pack(fill="x")
        template_buttons = ttk.Frame(editor)
        template_buttons.pack(fill="x", pady=px((6, 0)))
        ttk.Button(
            template_buttons, text="Lewy górny róg",
            command=lambda: self.toggle_battle_template_capture("top_left"),
        ).pack(side="left", fill="x", expand=True, padx=px((0, 3)))
        ttk.Button(
            template_buttons, text="Prawy dolny róg",
            command=lambda: self.toggle_battle_template_capture("bottom_right"),
        ).pack(side="left", fill="x", expand=True, padx=px((3, 0)))
        self.battle_template_status = tk.StringVar(
            value=f"Zapisane wzorce: {len(self.battle_templates)}"
        )
        self.add_status_label(editor, self.battle_template_status, wrap=360)
        row_options = ttk.Frame(editor)
        row_options.pack(fill="x", pady=px((8, 0)))
        ttk.Label(row_options, text="Wysokość wiersza Battle (px):").pack(side="left")
        self.battle_row_height_var = tk.StringVar(value="20")
        ttk.Entry(row_options, textvariable=self.battle_row_height_var, width=6).pack(
            side="left", padx=px((8, 0))
        )

    # --- dodawanie potwora kliknięciem w Battle ---------------------------------

    def toggle_learn_monster(self):
        if self.learn_monster_active:
            self.stop_learn_monster("Dodawanie anulowane.")
            return
        if self.battle_profiles["exp"]["region"] is None:
            self.learn_status.set("Najpierw szukam okna Battle…")
            self.detect_battle_window(
                callback=lambda: self.battle_profiles["exp"]["region"] is not None
                and not self.learn_monster_active and self.toggle_learn_monster()
            )
            return
        if not self.ensure_battle_process():
            return
        self.learn_monster_active = True
        self.learn_left_was_down = left_button_down()
        self.learn_button.configure(text="Anuluj dodawanie")
        self.learn_status.set("Wróć do gry i kliknij potwora w oknie Battle.")
        self.poll_learn_monster()

    def stop_learn_monster(self, message):
        self.learn_monster_active = False
        self.learn_button.configure(text="+ Dodaj z Battle (kliknij potwora w grze)")
        self.learn_status.set(message)

    def poll_learn_monster(self):
        if not self.learn_monster_active:
            return
        is_down = left_button_down()
        if is_down and not self.learn_left_was_down:
            position = foreground_client_position(self.battle_pid)
            left, top, right, bottom = self.battle_profiles["exp"]["region"]
            if position is not None and left <= position[0] < right and top <= position[1] < bottom:
                # Zrzut w chwili wciśnięcia: klient zaznacza cel na czerwono dopiero
                # po puszczeniu przycisku, a wzorzec ma mieć zwykły kolor nazwy.
                frame = capture_region(self.battle_pid, (left, top, right, bottom), grayscale=False)
                if frame is not None:
                    self.learn_monster_from(frame, position[0] - left, position[1] - top)
                    return
        self.learn_left_was_down = is_down
        self.root.after(10, self.poll_learn_monster)

    def learn_monster_from(self, frame, click_x, click_y):
        import cv2

        box = extract_battle_name(frame, click_x, click_y)
        if box is None:
            self.stop_learn_monster("Nie znalazłem nazwy w klikniętym wierszu; kliknij bliżej nazwy potwora.")
            return
        left, top, right, bottom = box
        crop = frame[top:bottom, left:right, :3]
        name = " ".join(self.monster_name_var.get().split())
        if not name:
            try:
                name = read_name_crop(crop)
            except Exception:
                name = ""
        if not name:
            name = f"Potwór {len(self.battle_templates) + 1}"
        try:
            self.store_battle_template(name, cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        except Exception as exc:
            self.stop_learn_monster(f"Nie udało się zapisać wzorca: {exc}")
            return
        self.monster_name_var.set("")
        self.show_target_preview(crop)
        self.stop_learn_monster(
            f"Dodano „{name}” ze wzorcem. Zła nazwa? Wpisz poprawną w pole poniżej i dodaj ponownie."
        )

    def show_target_preview(self, crop):
        import cv2

        zoom = 2 if crop.shape[0] < px(20) else 1
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        rgb = cv2.resize(rgb, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
        header = f"P6 {rgb.shape[1]} {rgb.shape[0]} 255\n".encode("ascii")
        self.target_preview_photo = tk.PhotoImage(data=header + rgb.tobytes(), format="PPM")
        self.target_preview.configure(image=self.target_preview_photo)

    # --- elementy układu ------------------------------------------------------

    def add_columns(self, parent, weights=(1, 1)):
        """Side-by-side columns that share the tab width."""
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        columns = []
        for index, weight in enumerate(weights):
            frame.columnconfigure(index, weight=weight, uniform="cols")
            column = ttk.Frame(frame)
            gap = px(14)
            column.grid(row=0, column=index, sticky="nsew",
                        padx=(0 if index == 0 else gap, 0 if index == len(weights) - 1 else gap))
            columns.append(column)
        return columns

    def add_group(self, parent, title, info=None):
        """Framed section with a title: one visible block per module in a column."""
        group = ttk.Frame(parent, style="Group.TFrame", padding=px((14, 10, 14, 14)))
        group.pack(fill="x", pady=px((0, 12)))
        head = ttk.Frame(group)
        head.pack(fill="x", pady=px((0, 6)))
        ttk.Label(head, text=title.upper(), style="GroupTitle.TLabel").pack(side="left")
        if info:
            self.add_info(head, info)
        body = ttk.Frame(group)
        body.pack(fill="x")
        return body

    def add_card(self, parent, title=None):
        """Block of settings inside a group (no border — the group already has one)."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=px((0, 4, 0, 0)))
        card.pack(fill="x", pady=px((8, 0)))
        if title:
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=px((0, 6)))
        # Osobna ramka na treść: wywołujący może w niej użyć grid albo pack.
        body = ttk.Frame(card)
        body.pack(fill="x")
        return body

    def add_tooltip(self, widget, text):
        """Show a longer explanation while the mouse is over the widget."""
        state = {"window": None}

        def show(_event):
            if state["window"] is not None:
                return
            window = tk.Toplevel(widget)
            window.wm_overrideredirect(True)
            window.attributes("-topmost", True)
            ttk.Label(window, text=text, style="Tooltip.TLabel", wraplength=px(440),
                      padding=px((10, 7))).pack()
            window.wm_geometry(f"+{widget.winfo_rootx() + px(10)}+"
                               f"{widget.winfo_rooty() + widget.winfo_height() + px(6)}")
            state["window"] = window

        def hide(_event):
            if state["window"] is not None:
                state["window"].destroy()
                state["window"] = None

        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    def add_info(self, parent, text, side="left"):
        """Small ⓘ marker with a tooltip, for explanations that do not fit one line."""
        label = ttk.Label(parent, text="ⓘ", style="Info.TLabel", cursor="question_arrow")
        label.pack(side=side, padx=px((6, 0)))
        self.add_tooltip(label, text)
        return label

    def add_tab_header(self, parent, title, subtitle):
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=px((0, 4)))
        ttk.Label(header, text=title, font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(header, text=subtitle, style="Muted.TLabel").pack(side="left", padx=px((14, 0)), pady=px((6, 0)))
        return header

    def add_status_label(self, parent, variable, wrap=560):
        ttk.Label(parent, textvariable=variable, style="Muted.TLabel", wraplength=px(wrap)).pack(
            anchor="w", pady=px((4, 0))
        )

    # --- karta Panel ------------------------------------------------------------

    def build_panel_tab(self, frame):
        header = self.add_tab_header(frame, f"{APP_NAME} {APP_VERSION}", "Światło, zaklęcia i jedzenie")
        self.topmost_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            header, text="Okno bota zawsze na wierzchu", variable=self.topmost_var,
            command=lambda: self.root.attributes("-topmost", self.topmost_var.get()),
        ).pack(side="right")
        left, right = self.add_columns(frame)

        group = self.add_group(left, "Światło")
        self.toggle_button = self.add_switch_row(group, "Light hack", self.toggle_light_hack)
        self.status = tk.StringVar(value="Status: wyłączony")
        row = ttk.Frame(group)
        row.pack(fill="x")
        ttk.Label(row, textvariable=self.status, style="Muted.TLabel").pack(side="left", pady=px((4, 0)))
        self.add_info(row, "Pełne światło w ciemnych jaskiniach. To jedyna funkcja, która zmienia "
                           "kod w pamięci uruchomionego klienta; po wyłączeniu bot przywraca "
                           "oryginalne bajty. Plik EXE nie jest zmieniany.")

        group = self.add_group(left, "Automatyczne zaklęcie")
        self.spell_button = self.add_switch_row(group, "Rzucaj zaklęcie co kilka sekund", self.toggle_spell)
        self.spell_status = tk.StringVar(value="Automat zaklęcia: wyłączony")
        self.add_status_label(group, self.spell_status)
        card = self.add_card(group)
        ttk.Label(card, text="Treść zaklęcia:").grid(row=0, column=0, sticky="w")
        self.spell_var = tk.StringVar()
        ttk.Entry(card, textvariable=self.spell_var).grid(row=0, column=1, columnspan=4, sticky="ew", padx=px((8, 0)))
        ttk.Label(card, text="Odstęp losowy:").grid(row=1, column=0, sticky="w", pady=px((10, 0)))
        self.interval_min_var = tk.StringVar(value="2")
        ttk.Entry(card, textvariable=self.interval_min_var, width=6).grid(row=1, column=1, sticky="w", padx=px((8, 0)), pady=px((10, 0)))
        ttk.Label(card, text="do").grid(row=1, column=2, padx=px(6), pady=px((10, 0)))
        self.interval_max_var = tk.StringVar(value="4")
        ttk.Entry(card, textvariable=self.interval_max_var, width=6).grid(row=1, column=3, sticky="w", pady=px((10, 0)))
        ttk.Label(card, text="sek.").grid(row=1, column=4, sticky="w", padx=px((6, 0)), pady=px((10, 0)))
        card.columnconfigure(4, weight=1)

        group = self.add_group(right, "Automatyczne jedzenie")
        self.food_button = self.add_switch_row(group, "Jedz co jakiś czas", self.toggle_food)
        self.food_status = tk.StringVar(value="Automatyczne jedzenie: wyłączone")
        self.add_status_label(group, self.food_status)
        card = self.add_card(group)
        ttk.Label(card, text="Odstęp:").grid(row=0, column=0, sticky="w")
        self.food_interval_min_var = tk.StringVar(value="30")
        ttk.Entry(card, textvariable=self.food_interval_min_var, width=6).grid(row=0, column=1, sticky="w", padx=px((8, 0)))
        ttk.Label(card, text="do").grid(row=0, column=2, padx=px(6))
        self.food_interval_max_var = tk.StringVar(value="45")
        ttk.Entry(card, textvariable=self.food_interval_max_var, width=6).grid(row=0, column=3, sticky="w")
        ttk.Label(card, text="sek.").grid(row=0, column=4, sticky="w", padx=px((6, 0)))
        self.food_position_button = ttk.Button(card, text="Ustaw pozycję jedzenia", command=self.toggle_food_capture)
        self.food_position_button.grid(row=1, column=0, columnspan=5, sticky="ew", pady=px((10, 0)))
        card.columnconfigure(4, weight=1)
        hint = ttk.Frame(group)
        hint.pack(fill="x", pady=px((6, 0)))
        ttk.Label(hint, text="Pozycję ustawisz prawym klikiem w jedzenie w grze.", style="Muted.TLabel").pack(side="left")
        self.add_info(hint, "Kliknij „Ustaw pozycję jedzenia”, wróć do gry i kliknij prawym przyciskiem "
                            "jedzenie w plecaku. Ten klik je zje i zapisze pozycję. Automat klika "
                            "tylko wtedy, gdy klient jest aktywnym oknem.")

    # --- karta Runy -----------------------------------------------------------------

    def build_runes_tab(self, rune_frame):
        self.add_tab_header(rune_frame, "Runemaker", "Runy z blanków i trening many, gdy mana przekroczy próg")
        left, right = self.add_columns(rune_frame)
        settings = self.automation

        group = self.add_group(
            left, "Runemaker",
            info="Gdy mana przekroczy próg: przedmiot z prawej ręki idzie do głównego plecaka, blank "
                 "runa z plecaka do ręki, bot rzuca zaklęcie, gotową runę odkłada w miejsce blanku "
                 "i wkłada przedmiot z powrotem do ręki. Każdy krok sprawdza na zrzucie; gdy coś się "
                 "nie uda, ponawia, a w razie kłopotu zatrzymuje się, nie gubiąc przedmiotu z ręki. "
                 "Główny plecak musi być otwarty, żeby bot znalazł w nim przedmiot z ręki.",
        )
        self.rune_button = self.add_switch_row(group, "Twórz runy", self.toggle_rune_making)
        self.rune_status = tk.StringVar(value="Runemaker: wyłączony")
        self.add_status_label(group, self.rune_status)
        card = self.add_card(group, "Zaklęcie")
        ttk.Label(card, text="Zaklęcie runy:").grid(row=0, column=0, sticky="w")
        self.rune_spell_var = tk.StringVar(value=settings.get("rune_spell", "adori vita vis"))
        ttk.Entry(card, textvariable=self.rune_spell_var).grid(row=0, column=1, columnspan=2, sticky="ew", padx=px((8, 0)))
        ttk.Label(card, text="Rób runę od many:").grid(row=1, column=0, sticky="w", pady=px((10, 0)))
        self.rune_mana_var = tk.StringVar(value=str(settings.get("rune_mana_pct", 90)))
        ttk.Entry(card, textvariable=self.rune_mana_var, width=6).grid(row=1, column=1, sticky="w", padx=px((8, 0)), pady=px((10, 0)))
        ttk.Label(card, text="%").grid(row=1, column=2, sticky="w", padx=px((6, 0)), pady=px((10, 0)))
        card.columnconfigure(2, weight=1)

        card = self.add_card(group, "Pozycje (Shift + lewy klik w grze)")
        for key, label in (
            ("rune_hand", "Ustaw slot prawej ręki"),
            ("rune_backpack", "Ustaw główny plecak (slot w Inventory)"),
            ("blank_rune", "Zapisz wzorzec blank runy (kliknij blank)"),
        ):
            ttk.Button(card, text=label, command=lambda k=key: self.start_rune_point_capture(k)).pack(
                fill="x", pady=px((0, 5))
            )
        self.rune_position_status = tk.StringVar(value=self.rune_positions_text())
        self.add_status_label(card, self.rune_position_status, wrap=520)

        group = self.add_group(
            right, "Mana trainer",
            info="Rzuca zaklęcie (np. utevo lux, exura), gdy mana przekroczy próg. Gdy Runemaker jest "
                 "włączony i ma blanki, trener czeka, żeby nie zabierać many na runy.",
        )
        self.trainer_button = self.add_switch_row(group, "Trenuj manę", self.toggle_mana_trainer)
        self.trainer_status = tk.StringVar(value="Mana trainer: wyłączony")
        self.add_status_label(group, self.trainer_status)
        card = self.add_card(group, "Zaklęcie")
        ttk.Label(card, text="Zaklęcie:").grid(row=0, column=0, sticky="w")
        self.trainer_spell_var = tk.StringVar(value=settings.get("trainer_spell", "utevo lux"))
        ttk.Entry(card, textvariable=self.trainer_spell_var).grid(row=0, column=1, columnspan=4, sticky="ew", padx=px((8, 0)))
        ttk.Label(card, text="Rzucaj od many:").grid(row=1, column=0, sticky="w", pady=px((10, 0)))
        self.trainer_mana_var = tk.StringVar(value=str(settings.get("trainer_mana_pct", 95)))
        ttk.Entry(card, textvariable=self.trainer_mana_var, width=6).grid(row=1, column=1, sticky="w", padx=px((8, 0)), pady=px((10, 0)))
        ttk.Label(card, text="%").grid(row=1, column=2, sticky="w", padx=px((6, 0)), pady=px((10, 0)))
        ttk.Label(card, text="Odstęp:").grid(row=2, column=0, sticky="w", pady=px((10, 0)))
        self.trainer_min_var = tk.StringVar(value=str(settings.get("trainer_min", 2)))
        ttk.Entry(card, textvariable=self.trainer_min_var, width=6).grid(row=2, column=1, sticky="w", padx=px((8, 0)), pady=px((10, 0)))
        ttk.Label(card, text="do").grid(row=2, column=2, padx=px(6), pady=px((10, 0)))
        self.trainer_max_var = tk.StringVar(value=str(settings.get("trainer_max", 5)))
        ttk.Entry(card, textvariable=self.trainer_max_var, width=6).grid(row=2, column=3, sticky="w", pady=px((10, 0)))
        ttk.Label(card, text="sek.").grid(row=2, column=4, sticky="w", padx=px((6, 0)), pady=px((10, 0)))
        card.columnconfigure(4, weight=1)

        group = self.add_group(
            right, "Mana",
            info="Bot sam znajduje okno Health Info klienta i odczytuje manę z napisu „aktualna / "
                 "maksymalna” (OCR), a między odczytami z długości niebieskiego paska.",
        )
        self.vitals_status = tk.StringVar(value="Okno Health Info: szukam po włączeniu modułu.")
        self.add_status_label(group, self.vitals_status, wrap=520)
        ttk.Button(group, text="Znajdź okno Health Info teraz", command=self.reset_vitals_window).pack(
            fill="x", pady=px((6, 0))
        )

        group = self.add_group(right, "Reakcja na Battle")
        card = self.add_card(group)
        options = self.rune_battle_options
        ttk.Checkbutton(card, text="Alarm dźwiękowy po wykryciu", variable=options["alarm"]).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(card, text="Odejdź w lewo o", variable=options["move_left"]).grid(row=1, column=0, sticky="w", pady=px((6, 0)))
        ttk.Entry(card, textvariable=options["left_steps"], width=4).grid(row=1, column=1, padx=px(6), pady=px((6, 0)))
        ttk.Label(card, text="kratek").grid(row=1, column=2, sticky="w", pady=px((6, 0)))
        ttk.Checkbutton(card, text="Wróć w prawo o", variable=options["return_right"]).grid(row=2, column=0, sticky="w", pady=px((6, 0)))
        ttk.Entry(card, textvariable=options["right_steps"], width=4).grid(row=2, column=1, padx=px(6), pady=px((6, 0)))
        ttk.Label(card, text="kratek, gdy Battle się opróżni").grid(row=2, column=2, sticky="w", pady=px((6, 0)))
        ttk.Checkbutton(card, text="Wstrzymaj pozostałe funkcje bota (poza light hackiem)",
                        variable=options["pause_bot"]).grid(row=3, column=0, columnspan=3, sticky="w", pady=px((6, 0)))
        self.add_battle_profile_controls(group, "runes", "Wykrywanie Battle (Runemaker)")

    # --- pasek stanu i mini-log ----------------------------------------------------

    def build_status_bar(self, root):
        """Bottom bar visible on every tab: state, STOP button and recent events."""
        bar = ttk.Frame(root, style="Bar.TFrame", padding=px((14, 8)))
        bar.pack(side="bottom", fill="x")
        top = ttk.Frame(bar, style="Bar.TFrame")
        top.pack(fill="x")
        self.status_vars = {}
        self.status_value_labels = {}
        for key, caption in (
            ("position", "Pozycja"), ("cavebot", "Cavebot"),
            ("targeting", "Targeting"), ("target", "Cel"), ("human", "Tryb"),
        ):
            cell = ttk.Frame(top, style="Bar.TFrame")
            cell.pack(side="left", padx=px((0, 28)))
            ttk.Label(cell, text=caption.upper(), style="BarCaption.TLabel").pack(anchor="w")
            self.status_vars[key] = tk.StringVar(value="—")
            label = ttk.Label(cell, textvariable=self.status_vars[key], style="BarValue.TLabel")
            label.pack(anchor="w")
            self.status_value_labels[key] = label
        ttk.Button(top, text="STOP wszystko  (F12)", style="Stop.TButton",
                   command=self.stop_everything).pack(side="right")
        self.event_list = tk.Listbox(
            bar, height=4, activestyle="none", borderwidth=0, highlightthickness=0,
            background=THEME["bg"], foreground=THEME["muted"], selectbackground=THEME["bg"],
            selectforeground=THEME["muted"], font=("Consolas", 9),
        )
        self.event_list.pack(fill="x", pady=px((8, 0)))

    def add_event(self, message):
        """Add one line to the in-window event log (skipping immediate repeats)."""
        if self.events and self.events[-1][1] == message:
            return
        stamp = time.strftime("%H:%M:%S")
        self.events.append((stamp, message))
        if hasattr(self, "event_list"):
            self.event_list.insert("end", f"{stamp}  {message}")
            if self.event_list.size() > 60:
                self.event_list.delete(0, self.event_list.size() - 61)
            self.event_list.see("end")

    def update_status_bar(self):
        try:
            if self.minimap_position is not None:
                x, y, z = self.minimap_position
                self.status_vars["position"].set(f"{x}, {y}, {z}")
            else:
                self.status_vars["position"].set("nieznana")
            walker = self.cavebot_walker
            if walker is not None and self.waypoints:
                self.status_vars["cavebot"].set(f"WŁ · waypoint {walker.index + 1}/{len(self.waypoints)}")
            else:
                self.status_vars["cavebot"].set("wyłączony")
            if self.battle_attack_enabled:
                found = "Battle OK" if self.battle_profiles["exp"]["region"] else "szukam Battle"
                self.status_vars["targeting"].set(f"WŁ · {found}")
            else:
                self.status_vars["targeting"].set("wyłączony")
            if self.battle_attack_enabled and self.battle_attacking:
                name = (self.battle_target_lock or "cel").title()
                health = self.battle_current_health
                if health is not None:
                    self.status_vars["target"].set(f"{name} · HP {health}%")
                else:
                    self.status_vars["target"].set(name)
            else:
                self.status_vars["target"].set("brak")
            self.status_vars["human"].set("Human" if human.enabled() else "zwykły")
            for key, variable in self.status_vars.items():
                value = variable.get()
                active = value.startswith("WŁ") or (key == "target" and value != "brak") or (
                    key == "human" and value == "Human")
                self.status_value_labels[key].configure(style="BarOn.TLabel" if active else "BarValue.TLabel")
        finally:
            self.root.after(400, self.update_status_bar)

    def poll_hotkeys(self):
        """F12 stops everything, also while the game window is active."""
        try:
            is_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x7B) & 0x8000)
            if is_down and not self.f12_was_down:
                self.stop_everything()
            self.f12_was_down = is_down
        finally:
            self.root.after(60, self.poll_hotkeys)

    def stop_everything(self):
        """Stop every automation (light hack stays as it is)."""
        self.cancel_battle_capture()
        self.cancel_battle_template_capture()
        self.point_capture = None
        self.loot_cancel.set()
        self.corpse_queue.clear()
        if self.learn_monster_active:
            self.stop_learn_monster("Dodawanie anulowane (STOP).")
        if self.battle_attack_enabled:
            self.toggle_battle_attack()
        self.stop_cavebot("Cavebot zatrzymany (STOP).")
        for profile_key in self.battle_profiles:
            if self.battle_monitors[profile_key]["after_id"] is not None:
                self.stop_battle_monitor(profile_key, resume_automations=True)
        self.stop_spell()
        self.stop_food()
        self.stop_pickup("Zbieranie amunicji: zatrzymane (STOP)")
        self.stop_fishing("Wędkowanie: zatrzymane (STOP)")
        self.stop_rune_making("Runemaker: zatrzymany (STOP)")
        self.stop_mana_trainer("Mana trainer: zatrzymany (STOP)")
        self.add_event("STOP — zatrzymano wszystkie funkcje bota.")

    # --- profile ---------------------------------------------------------------------

    def refresh_profile_list(self):
        self.profile_box.configure(values=list_profiles())

    def save_profile_as(self):
        current = self.profile_var.get() or "Nowy profil"
        name = simpledialog.askstring(
            "Zapisz profil", "Nazwa profilu (trasa + lista potworów):",
            initialvalue=current, parent=self.root,
        )
        if not name:
            return
        if name.strip() in list_profiles() and not messagebox.askyesno(
            "Nadpisać profil?", f"Profil „{name.strip()}” już istnieje. Nadpisać go?", parent=self.root
        ):
            return
        try:
            self.save_cavebot_profile()
            saved = save_named_profile(name, self.cavebot_profile)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Nie zapisano profilu", str(exc), parent=self.root)
            return
        self.cavebot_profile["profile"] = saved
        self.profile_var.set(saved)
        self.refresh_profile_list()
        self.save_cavebot_profile()
        self.add_event(f"Zapisano profil „{saved}” ({len(self.waypoints)} waypointów, "
                       f"{len(self.monster_names())} potworów).")

    def load_selected_profile(self):
        name = self.profile_var.get()
        if not name:
            messagebox.showinfo("Wybierz profil", "Najpierw wybierz profil z listy.", parent=self.root)
            return
        try:
            data = load_named_profile(name)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Nie wczytano profilu", str(exc), parent=self.root)
            return
        if self.cavebot_walker is not None:
            self.stop_cavebot("Cavebot zatrzymany: wczytano inny profil.")
        if self.battle_attack_enabled:
            # Lista celów ataku powstaje przy włączaniu, więc atak trzeba włączyć ponownie.
            self.toggle_battle_attack()
        for key in PROFILE_KEYS:
            self.cavebot_profile[key] = data[key]
        self.cavebot_profile["profile"] = name
        self.battle_monsters_var.set(", ".join(data["monsters"]))
        self.cavebot_pause_var.set(data["pause_on_battle"])
        self.cavebot_inspect_corpses_var.set(data.get("inspect_corpses", False))
        self.cavebot_learn_loot_var.set(data.get("learn_loot", False))
        self.cavebot_use_meat_var.set(data.get("use_meat", True))
        self.cavebot_loot_var.set(data.get("loot_items", False))
        self.cavebot_loot_now_var.set(data.get("loot_immediately", True))
        self.refresh_loot_controls()
        self.waypoint_type_var.set(WAYPOINT_TYPES[data["waypoint_type"]])
        self.map_pan = None
        self.refresh_waypoint_list()
        self.refresh_target_list()
        self.save_cavebot_profile()
        self.draw_map()
        self.add_event(f"Wczytano profil „{name}” ({len(data['waypoints'])} waypointów, "
                       f"{len(data['monsters'])} potworów).")

    def delete_selected_profile(self):
        name = self.profile_var.get()
        if not name or not messagebox.askyesno(
            "Usuń profil", f"Usunąć profil „{name}”? Bieżąca trasa zostaje.", parent=self.root
        ):
            return
        try:
            delete_named_profile(name)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Nie usunięto profilu", str(exc), parent=self.root)
            return
        self.profile_var.set("")
        self.cavebot_profile["profile"] = ""
        self.refresh_profile_list()
        self.save_cavebot_profile()
        self.add_event(f"Usunięto profil „{name}”.")

    # --- tryb Human ------------------------------------------------------------

    def toggle_human(self):
        human.set_enabled(not human.enabled())
        self.human_pill.set_on(human.enabled())
        self.cavebot_profile["human"] = human.enabled()
        self.save_cavebot_profile()

    # --- okno Battle -----------------------------------------------------------

    def detect_battle_window(self, callback=None):
        """Find the Battle window on a screenshot of the whole client (in the background)."""
        if callback is not None:
            self.battle_detect_callbacks.append(callback)
        if self.battle_detect_state is not None:
            return
        try:
            self.battle_detect_tesseract = find_tesseract()
        except Exception as exc:
            self.battle_window_status.set(f"Do wyszukania okna Battle potrzebny jest Tesseract OCR: {exc}")
            self.battle_detect_callbacks.clear()
            return
        if not self.ensure_battle_process():
            self.battle_detect_callbacks.clear()
            return
        self.battle_detect_state = "waiting"
        self.battle_window_status.set("Wróć do gry — szukam okna Battle na zrzucie klienta…")
        self.poll_battle_detection()

    def poll_battle_detection(self):
        state = self.battle_detect_state
        if state == "waiting":
            import mss  # noqa: F401  — świadomość DPI przed pobraniem rozmiaru okna

            bounds = foreground_client_bounds(self.battle_pid)
            if bounds is None:
                self.root.after(400, self.poll_battle_detection)
                return
            image = capture_region(self.battle_pid, (0, 0, bounds[2], bounds[3]),
                                   grayscale=False, label="okna gry")
            if image is None:
                self.root.after(400, self.poll_battle_detection)
                return
            result = {}

            def work():
                try:
                    result["value"] = find_battle_window(image, self.battle_detect_tesseract)
                except Exception as exc:
                    result["error"] = exc

            thread = threading.Thread(target=work, daemon=True)
            thread.start()
            self.battle_detect_state = (thread, result)
            self.root.after(200, self.poll_battle_detection)
            return
        thread, result = state
        if thread.is_alive():
            self.root.after(200, self.poll_battle_detection)
            return
        self.battle_detect_state = None
        callbacks, self.battle_detect_callbacks = self.battle_detect_callbacks, []
        if "error" in result:
            self.battle_window_status.set(f"Błąd wyszukiwania okna Battle: {result['error']}")
            return
        region, titles = result["value"]
        if region is None:
            seen = ", ".join(title for title in titles if title) or "brak"
            self.battle_window_status.set(
                "Nie znalazłem okna Battle. Otwórz je w kliencie (Ctrl+B) i spróbuj ponownie. "
                f"Widoczne okna: {seen}."
            )
            return
        left, top, right, bottom = region
        for key in ("exp", "runes"):
            if key == "exp" or self.battle_profiles[key]["region"] is None:
                self.battle_profiles[key]["region"] = region
                if key in self.battle_profile_status:
                    self.battle_profile_status[key].set(
                        f"Battle: X={left}–{right}, Y={top}–{bottom} (wykryte automatycznie)."
                    )
        self.battle_window_status.set(
            f"Okno Battle znalezione: {right - left} × {bottom - top} px w X={left}, Y={top}."
        )
        for callback in callbacks:
            callback()

    def battle_monitor_needed(self):
        return self.battle_attack_enabled or (
            self.cavebot_walker is not None and self.cavebot_pause_var.get()
        )

    def ensure_exp_battle_monitor(self):
        """Start Battle detection for the Cavebot tab when attack or pausing needs it."""
        if not self.battle_monitor_needed():
            return
        if self.battle_profiles["exp"]["region"] is None:
            self.detect_battle_window(callback=self.ensure_exp_battle_monitor)
            return
        if self.battle_monitors["exp"]["after_id"] is None:
            self.toggle_battle_monitor("exp")

    def release_exp_battle_monitor(self):
        if not self.battle_monitor_needed() and self.battle_monitors["exp"]["after_id"] is not None:
            self.stop_battle_monitor("exp", resume_automations=True)

    def on_cavebot_pause_changed(self):
        self.save_cavebot_profile()
        if self.cavebot_pause_var.get():
            self.ensure_exp_battle_monitor()
        else:
            self.release_exp_battle_monitor()

    def on_cavebot_inspect_corpses_changed(self):
        # Nauka wzorców i lootowanie wymagają otwierania ciał.
        if not self.cavebot_inspect_corpses_var.get():
            self.cavebot_learn_loot_var.set(False)
            self.cavebot_loot_var.set(False)
        self.refresh_loot_controls()
        self.save_cavebot_profile()

    def on_cavebot_learn_loot_changed(self):
        if self.cavebot_learn_loot_var.get():
            self.cavebot_inspect_corpses_var.set(True)
        self.refresh_loot_controls()
        self.save_cavebot_profile()

    def on_cavebot_loot_changed(self):
        if self.cavebot_loot_var.get():
            self.cavebot_inspect_corpses_var.set(True)
            if not self.cavebot_profile.get("loot_slot"):
                self.loot_slot_status.set("Ustaw jeszcze slot plecaka, do którego bot ma odkładać loot.")
        self.refresh_loot_controls()
        self.save_cavebot_profile()

    def start_loot_slot_capture(self):
        def store(key, position):
            self.cavebot_profile[key] = [position[0], position[1]]
            self.save_cavebot_profile()
            self.loot_slot_status.set(self.loot_slot_text())

        self.start_point_capture("loot_slot", "na pustym slocie w plecaku na loot",
                                 status=self.loot_slot_status, on_point=store)

    def loot_slot_text(self):
        slot = self.cavebot_profile.get("loot_slot")
        return f"Slot plecaka na loot: {'X=%d, Y=%d' % tuple(slot) if slot else 'nieustawiony'}"

    def on_cavebot_use_meat_changed(self):
        self.cavebot_profile["use_meat"] = bool(self.cavebot_use_meat_var.get())
        self.save_cavebot_profile()

    def make_listbox(self, parent, height):
        listbox = tk.Listbox(
            parent, height=height, activestyle="none", borderwidth=0, highlightthickness=1,
            highlightbackground=THEME["border"], background=THEME["row"],
            foreground=THEME["text"], selectbackground=THEME["accent"],
            font=("Consolas", 10), exportselection=False,
        )
        listbox.pack(fill="x", pady=px((6, 0)))
        return listbox

    # --- profil cavebota -----------------------------------------------------

    def save_cavebot_profile(self):
        self.cavebot_profile["monsters"] = [
            part.strip() for part in self.battle_monsters_var.get().split(",") if part.strip()
        ]
        self.cavebot_profile["pause_on_battle"] = bool(self.cavebot_pause_var.get())
        self.cavebot_profile["inspect_corpses"] = bool(self.cavebot_inspect_corpses_var.get())
        self.cavebot_profile["learn_loot"] = bool(self.cavebot_learn_loot_var.get())
        self.cavebot_profile["use_meat"] = bool(self.cavebot_use_meat_var.get())
        self.cavebot_profile["loot_items"] = bool(self.cavebot_loot_var.get())
        self.cavebot_profile["loot_immediately"] = bool(self.cavebot_loot_now_var.get())
        self.cavebot_profile["waypoint_type"] = next(
            (key for key, label in WAYPOINT_TYPES.items() if label == self.waypoint_type_var.get()),
            "walk",
        )
        try:
            save_profile(self.cavebot_profile)
        except OSError as exc:
            self.cavebot_status.set(f"Nie udało się zapisać trasy: {exc}")

    # --- potwory ---------------------------------------------------------------

    def monster_names(self):
        return [part.strip() for part in self.battle_monsters_var.get().split(",") if part.strip()]

    def add_monster(self):
        name = " ".join(self.monster_name_var.get().split())
        if not name:
            return
        names = self.monster_names()
        if name.casefold() not in {item.casefold() for item in names}:
            self.battle_monsters_var.set(", ".join(names + [name]))
        self.monster_name_var.set("")

    def remove_monster(self):
        selection = self.target_list.curselection()
        names = self.monster_names()
        if not selection or selection[0] >= len(names):
            return
        del names[selection[0]]
        self.battle_monsters_var.set(", ".join(names))

    def on_monsters_changed(self):
        self.refresh_target_list()
        self.save_cavebot_profile()

    def refresh_target_list(self, select=None):
        if not hasattr(self, "target_list"):
            return
        self.target_list.delete(0, "end")
        names = self.monster_names()
        ignored = set(self.cavebot_profile.get("ignored", []))
        modes = self.cavebot_profile.get("monster_modes", {})
        for index, name in enumerate(names):
            key = " ".join(name.split()).casefold()
            source = "wzorzec" if key in self.battle_templates else "OCR"
            mode = COMBAT_MODES[modes.get(key, "chase")]
            state = " · ignor." if key in ignored else ""
            self.target_list.insert("end", f"{index + 1:>2}. {name:<14} {mode:<4} {source}{state}")
        if not names:
            self.target_list.insert("end", "  Lista pusta — kliknij „+ Dodaj z Battle”.")
        if select is not None and 0 <= select < len(names):
            self.target_list.selection_set(select)
            self.target_list.see(select)

    def move_monster(self, direction):
        selection = self.target_list.curselection()
        names = self.monster_names()
        if not selection or selection[0] >= len(names):
            return
        index = selection[0]
        target = index + direction
        if 0 <= target < len(names):
            names[index], names[target] = names[target], names[index]
            self.battle_monsters_var.set(", ".join(names))
            self.refresh_target_list(select=target)

    def toggle_ignore_monster(self):
        selection = self.target_list.curselection()
        names = self.monster_names()
        if not selection or selection[0] >= len(names):
            return
        key = " ".join(names[selection[0]].split()).casefold()
        ignored = self.cavebot_profile.setdefault("ignored", [])
        if key in ignored:
            ignored.remove(key)
            self.add_event(f"Targeting: „{names[selection[0]]}” znów atakowany.")
        else:
            ignored.append(key)
            self.add_event(f"Targeting: „{names[selection[0]]}” ignorowany.")
        self.save_cavebot_profile()
        self.refresh_target_list(select=selection[0])

    def toggle_monster_mode(self):
        selection = self.target_list.curselection()
        names = self.monster_names()
        if not selection or selection[0] >= len(names):
            return
        key = " ".join(names[selection[0]].split()).casefold()
        modes = self.cavebot_profile.setdefault("monster_modes", {})
        modes[key] = "stand" if modes.get(key, "chase") == "chase" else "chase"
        self.add_event(f"Targeting: „{names[selection[0]]}” — tryb {COMBAT_MODES[modes[key]]}.")
        self.save_cavebot_profile()
        self.refresh_target_list(select=selection[0])

    # --- tryb walki klienta (Stand / Chase) -------------------------------------

    def detect_combat_buttons(self):
        """Find the Stand/Chase buttons on a screenshot of the client, in the background."""
        if self.combat_detect_state is not None or self.battle_pid is None:
            return
        if time.monotonic() < self.combat_detect_retry_at:
            return
        bounds = foreground_client_bounds(self.battle_pid)
        if bounds is None:
            return
        image = capture_region(self.battle_pid, (0, 0, bounds[2], bounds[3]), grayscale=False, label="okna gry")
        if image is None:
            return
        result = {}

        def work():
            try:
                result["value"] = find_combat_buttons(image)
            except Exception as exc:
                result["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self.combat_detect_state = (thread, result)
        self.root.after(200, self.poll_combat_detection)

    def poll_combat_detection(self):
        thread, result = self.combat_detect_state
        if thread.is_alive():
            self.root.after(200, self.poll_combat_detection)
            return
        self.combat_detect_state = None
        self.combat_buttons = result.get("value")
        if self.combat_buttons:
            self.add_event("Znaleziono przyciski trybu walki (Stand / Chase) w oknie Inventory.")
        else:
            self.combat_detect_retry_at = time.monotonic() + 30
            self.add_event("Nie widzę przycisków Stand / Chase — otwórz okno Inventory w kliencie.")

    def ensure_combat_mode(self, key):
        """Click Stand or Chase in the client when the target needs another mode."""
        desired = self.cavebot_profile.get("monster_modes", {}).get(key, "chase")
        buttons = self.combat_buttons
        if buttons is None:
            self.detect_combat_buttons()
            return
        boxes = list(buttons.values())
        margin = px(3)
        region = (
            max(0, min(box[0] for box in boxes) - margin),
            max(0, min(box[1] for box in boxes) - margin),
            max(box[0] + box[2] for box in boxes) + margin,
            max(box[1] + box[3] for box in boxes) + margin,
        )
        image = capture_region(self.battle_pid, region, grayscale=False, label="przycisków trybu walki")
        if image is None:
            return
        local = {name: (x - region[0], y - region[1], w, h) for name, (x, y, w, h) in buttons.items()}
        mode = current_mode(image, local)
        if mode == desired:
            return
        if mode is None:
            # Przyciski nie wyglądają jak Stand/Chase: okno Inventory mogło się przesunąć.
            self.combat_buttons = None
            self.detect_combat_buttons()
            return
        x, y, width, height = buttons[desired]
        if send_left_click(self.battle_pid, human.jitter(x + width // 2, width // 4),
                           human.jitter(y + height // 2, height // 4)):
            self.add_event(f"Tryb walki: {COMBAT_MODES[desired]} (dla „{key.title()}”).")

    # --- akcje na waypointach (drabina, lina) -----------------------------------

    def start_point_capture(self, key, where, status=None, on_point=None):
        """Wait for Shift + left click in the game; store it in the profile or pass it to on_point."""
        if not self.ensure_battle_process():
            return
        self.point_capture = key
        self.point_capture_callback = on_point
        self.point_left_was_down = left_button_down()
        (status or self.action_points_status).set(f"Wróć do gry i kliknij Shift + lewy przycisk {where}.")
        self.poll_point_capture()

    def poll_point_capture(self):
        if self.point_capture is None:
            return
        is_down = left_button_down()
        if is_down and not self.point_left_was_down and shift_key_down():
            position = foreground_client_position(self.battle_pid)
            if position is not None:
                callback = self.point_capture_callback
                key = self.point_capture
                self.point_capture = None
                self.point_capture_callback = None
                if callback is not None:
                    callback(key, (int(position[0]), int(position[1])))
                    return
                self.cavebot_profile[key] = [int(position[0]), int(position[1])]
                self.save_cavebot_profile()
                self.action_points_status.set(self.action_points_text())
                return
        self.point_left_was_down = is_down
        self.root.after(15, self.poll_point_capture)

    def action_points_text(self):
        center = self.cavebot_profile.get("player_center")
        rope = self.cavebot_profile.get("rope_slot")
        return (f"Postać: {'X=%d, Y=%d' % tuple(center) if center else 'nieustawiona'} · "
                f"lina: {'X=%d, Y=%d' % tuple(rope) if rope else 'nieustawiona'}")

    def perform_waypoint_action(self, kind):
        """Use a ladder (right-click own tile) or a rope (rope from backpack on own tile)."""
        center = self.cavebot_profile.get("player_center")
        if not center:
            self.stop_cavebot("Cavebot zatrzymany: ustaw środek postaci w „Lina i drabina”.")
            return False
        pid = self.minimap_pid
        target_x = human.jitter(center[0], px(5))
        target_y = human.jitter(center[1], px(5))
        if kind == "ladder":
            return send_right_click(pid, target_x, target_y)
        rope = self.cavebot_profile.get("rope_slot")
        if not rope:
            self.stop_cavebot("Cavebot zatrzymany: ustaw pozycję liny w „Lina i drabina”.")
            return False
        # Prawy klik na linie włącza celownik „Use with…”, lewy klik wskazuje pole postaci.
        if not send_right_click(pid, human.jitter(rope[0], px(3)), human.jitter(rope[1], px(3))):
            return False
        time.sleep(random.uniform(0.15, 0.35) if human.enabled() else 0.1)
        return send_left_click(pid, target_x, target_y)

    def monster_priority(self, key):
        order = [" ".join(name.split()).casefold() for name in self.monster_names()]
        return order.index(key) if key in order else len(order)

    # --- waypointy ---------------------------------------------------------------

    @property
    def waypoints(self):
        return self.cavebot_profile["waypoints"]

    def new_waypoint_type(self):
        return next(
            (key for key, label in WAYPOINT_TYPES.items() if label == self.waypoint_type_var.get()),
            "walk",
        )

    def add_waypoint(self, x, y, z):
        selection = self.waypoint_list.curselection()
        waypoint = {"x": int(x), "y": int(y), "z": int(z), "type": self.new_waypoint_type()}
        # Nowy waypoint trafia za zaznaczony, a bez zaznaczenia na koniec trasy.
        index = selection[0] + 1 if selection else len(self.waypoints)
        self.waypoints.insert(index, waypoint)
        self.waypoints_changed(select=index)

    def add_waypoint_at_player(self):
        if self.minimap_position is None:
            self.cavebot_status.set("Pozycja postaci nie jest jeszcze znana.")
            return
        self.add_waypoint(*self.minimap_position)

    def remove_selected_waypoint(self):
        selection = self.waypoint_list.curselection()
        if selection:
            del self.waypoints[selection[0]]
            self.waypoints_changed(select=min(selection[0], len(self.waypoints) - 1))

    def move_selected_waypoint(self, direction):
        selection = self.waypoint_list.curselection()
        if not selection:
            return
        index = selection[0]
        target = index + direction
        if 0 <= target < len(self.waypoints):
            self.waypoints[index], self.waypoints[target] = self.waypoints[target], self.waypoints[index]
            self.waypoints_changed(select=target)

    def clear_waypoints(self):
        if self.waypoints and messagebox.askyesno(
            "Wyczyść trasę", "Usunąć wszystkie waypointy?", parent=self.root
        ):
            self.waypoints.clear()
            self.waypoints_changed()

    def waypoints_changed(self, select=None):
        if self.cavebot_walker is not None:
            self.cavebot_walker.reset_progress()
        self.refresh_waypoint_list(select)
        self.save_cavebot_profile()
        self.draw_map()

    def refresh_waypoint_list(self, select=None):
        self.waypoint_list.delete(0, "end")
        current = self.cavebot_walker.index if self.cavebot_walker is not None else None
        for index, waypoint in enumerate(self.waypoints):
            marker = "▶" if index == current else " "
            self.waypoint_list.insert("end", f"{marker}{waypoint_text(index, waypoint)}")
        if not self.waypoints:
            self.waypoint_list.insert("end", "  Brak waypointów — kliknij mapę albo „+ Tu stoję”.")
        if select is not None and 0 <= select < len(self.waypoints):
            self.waypoint_list.selection_set(select)
            self.waypoint_list.see(select)

    # --- walker --------------------------------------------------------------------

    def toggle_cavebot(self):
        if self.cavebot_walker is not None:
            self.stop_cavebot("Cavebot: wyłączony")
            return
        if not self.waypoints:
            self.cavebot_status.set("Dodaj co najmniej jeden waypoint.")
            return
        if not self.minimap_enabled_var.get():
            self.cavebot_status.set("Włącz najpierw „Śledzenie pozycji”.")
            return
        if self.minimap_map is None:
            self.cavebot_status.set("Mapa nie jest jeszcze wczytana; poczekaj chwilę.")
            return
        walker = CavebotWalker(self.minimap_map, self.waypoints)
        selection = self.waypoint_list.curselection()
        if selection:
            walker.index = selection[0]
        elif self.minimap_position is not None:
            # Bez zaznaczenia zaczynamy od najbliższego waypointu na tym piętrze.
            x, y, z = self.minimap_position
            same_floor = [i for i, item in enumerate(self.waypoints) if item["z"] == z]
            if same_floor:
                walker.index = min(
                    same_floor,
                    key=lambda i: max(abs(self.waypoints[i]["x"] - x), abs(self.waypoints[i]["y"] - y)),
                )
        self.cavebot_walker = walker
        self.cavebot_pill.set_on(True)
        self.ensure_exp_battle_monitor()
        self.cavebot_status.set(f"Cavebot włączony; start od waypointu {walker.index + 1}. Wróć do gry.")
        self.add_event(f"Cavebot włączony (start od waypointu {walker.index + 1}).")
        self.refresh_waypoint_list()
        self.draw_map()

    def stop_cavebot(self, status):
        self.cavebot_walker = None
        if hasattr(self, "cavebot_pill"):
            self.release_exp_battle_monitor()
            self.cavebot_pill.set_on(False)
            self.cavebot_status.set(status)
            self.refresh_waypoint_list()
            self.draw_map()

    def cavebot_step(self, position):
        """Jeden krok walkera po udanym odczycie pozycji z minimapy."""
        walker = self.cavebot_walker
        if walker is None:
            return
        if self.other_bot_functions_paused():
            self.cavebot_status.set("Cavebot wstrzymany przez reakcję na Battle.")
            return
        if self.cavebot_pause_var.get():
            if self.battle_attack_enabled:
                # Z targetingiem czekamy tylko na walkę, którą da się stoczyć:
                # cel jest atakowany albo w zasięgu jest potwór z listy.
                if self.targeting_busy():
                    self.cavebot_status.set("Walka: czekam, aż targeting skończy.")
                    walker.reset_progress()
                    return
            elif self.battle_monitors["exp"]["present"]:
                self.cavebot_status.set("W Battle są potwory; czekam, aż lista się opróżni.")
                walker.reset_progress()
                return
        tracker = self.minimap_tracker
        if tracker.player_pixel is None:
            return
        width, height = tracker.view_size
        player_x, player_y = tracker.player_pixel
        scale = tracker.scale

        def can_click(dx, dy):
            x, y = player_x + dx * scale, player_y + dy * scale
            if not (0.08 * width <= x <= 0.92 * width and 0.08 * height <= y <= 0.92 * height):
                return False
            # Przyciski minimapy: „Centre” w lewym górnym, piętra i zoom w prawym dolnym rogu.
            if x < 0.2 * width and y < 0.2 * height:
                return False
            return not (x > 0.78 * width and y > 0.62 * height)

        previous_index = walker.index
        action = walker.step(position, time.monotonic(), can_click)
        message = action[-1]
        if action[0] == "action":
            if not self.perform_waypoint_action(action[1]):
                if self.cavebot_walker is None:
                    return
                message = "Okno gry nie jest aktywne; akcja pominięta."
                walker.action_at = None
                walker.action_attempts = max(0, walker.action_attempts - 1)
            else:
                self.add_event(f"Cavebot: {message}")
        if action[0] == "click":
            _kind, dx, dy, message = action
            left, top = self.minimap_region[0], self.minimap_region[1]
            client_x = human.jitter(left + player_x + dx * scale, scale // 3)
            client_y = human.jitter(top + player_y + dy * scale, scale // 3)
            if not send_left_click(self.minimap_pid, client_x, client_y):
                message = "Okno gry nie jest aktywne; kliknięcie pominięte."
                walker.last_click_at = None
        self.cavebot_status.set(message)
        if any(word in message for word in ("osiągnięty", "pomijam", "Zmiana piętra", "przerwa")):
            self.add_event(f"Cavebot: {message}")
        if walker.index != previous_index:
            self.refresh_waypoint_list()
            self.draw_map()

    # --- widok mapy --------------------------------------------------------------

    def map_center(self):
        """Return (x, y, z) shown in the middle of the map view, or None."""
        if self.map_pan is not None:
            return self.map_pan
        if self.minimap_position is not None:
            return self.minimap_position
        if self.waypoints:
            first = self.waypoints[0]
            return first["x"], first["y"], first["z"]
        return None

    def map_zoom_pixels(self):
        return max(1, round(self.minimap_settings["zoom"] * UI_SCALE))

    def change_map_floor(self, step):
        center = self.map_center()
        if center is None:
            return
        x, y, z = center
        self.map_pan = (x, y, min(15, max(0, z + step)))
        self.draw_map()

    def center_map_on_player(self):
        self.map_pan = None
        self.draw_map()

    def draw_map(self):
        """Render the .otmm floor with the character and the waypoint route."""
        canvas = self.map_canvas
        canvas.delete("all")
        center = self.map_center()
        if self.minimap_map is None or center is None:
            self.map_view = None
            self.map_floor_label.set("")
            canvas.create_text(
                self.map_width // 2, self.map_height // 2, fill="#aaaaaa",
                text="Pozycja nieznana — wróć do gry z otwartą minimapą.",
            )
            return
        import numpy

        x, y, z = center
        zoom = self.map_zoom_pixels()
        cols = -(-self.map_width // zoom)
        rows = -(-self.map_height // zoom)
        left, top = x - cols // 2, y - rows // 2
        view = numpy.full((rows, cols), UNKNOWN, dtype=numpy.uint8)
        floor = self.minimap_map.floors.get(z)
        if floor is not None:
            origin_x, origin_y, colors, _flags = floor
            src_left, src_top = max(left - origin_x, 0), max(top - origin_y, 0)
            src_right = min(left + cols - origin_x, colors.shape[1])
            src_bottom = min(top + rows - origin_y, colors.shape[0])
            if src_right > src_left and src_bottom > src_top:
                dst_left, dst_top = src_left + origin_x - left, src_top + origin_y - top
                view[dst_top:dst_top + src_bottom - src_top, dst_left:dst_left + src_right - src_left] = (
                    colors[src_top:src_bottom, src_left:src_right]
                )
        pixels = MAP_PALETTE_RGB[view].repeat(zoom, axis=0).repeat(zoom, axis=1)
        pixels = numpy.ascontiguousarray(pixels[:self.map_height, :self.map_width])
        header = f"P6 {self.map_width} {self.map_height} 255\n".encode("ascii")
        self.map_photo = tk.PhotoImage(data=header + pixels.tobytes(), format="PPM")
        canvas.create_image(0, 0, image=self.map_photo, anchor="nw")
        self.map_view = (left, top, z, zoom)
        self.map_floor_label.set(f"Piętro {z}" + ("  (podgląd)" if self.map_pan else ""))

        def to_canvas(tile_x, tile_y):
            return (tile_x - left) * zoom + zoom // 2, (tile_y - top) * zoom + zoom // 2

        # Trasa: linie między kolejnymi waypointami na tym piętrze i numerowane punkty.
        radius = max(px(6), zoom)
        selection = self.waypoint_list.curselection() if hasattr(self, "waypoint_list") else ()
        current = self.cavebot_walker.index if self.cavebot_walker is not None else None
        points = [(i, item) for i, item in enumerate(self.waypoints) if item["z"] == z]
        count = len(self.waypoints)
        for i, item in enumerate(self.waypoints):
            # Ostatni odcinek (powrót na początek pętli) rysujemy przerywaną linią.
            closing = i == count - 1
            if count < 2 or (closing and count < 3):
                continue
            nxt = self.waypoints[(i + 1) % count]
            if item["z"] != z or nxt["z"] != z:
                continue
            options = {"dash": (px(4), px(3))} if closing else {}
            canvas.create_line(*to_canvas(item["x"], item["y"]), *to_canvas(nxt["x"], nxt["y"]),
                               fill=THEME["accent"], width=px(2), **options)
        for i, item in points:
            cx, cy = to_canvas(item["x"], item["y"])
            fill = THEME["on"] if i == current else ("#f0c040" if i in selection else THEME["accent"])
            if item["type"] == "stand":
                canvas.create_rectangle(cx - radius, cy - radius, cx + radius, cy + radius,
                                        fill=fill, outline="black")
            elif item["type"] in ACTION_TYPES:
                # Romb: waypoint z akcją (drabina, lina).
                canvas.create_polygon(cx, cy - radius - 2, cx + radius + 2, cy, cx, cy + radius + 2,
                                      cx - radius - 2, cy, fill=fill, outline="black")
            else:
                canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                                   fill=fill, outline="black")
            canvas.create_text(cx, cy, text=str(i + 1), fill="black",
                               font=("Segoe UI", 7, "bold"))
        if self.minimap_position is not None and self.minimap_position[2] == z:
            cx, cy = to_canvas(*self.minimap_position[:2])
            arm = max(px(6), zoom * 2)
            for dx, dy in ((arm, 0), (0, arm)):
                canvas.create_line(cx - dx, cy - dy, cx + dx + 1, cy + dy + 1, fill="white", width=px(2))

    def map_tile(self, event):
        if self.map_view is None:
            return None
        left, top, z, zoom = self.map_view
        return left + event.x // zoom, top + event.y // zoom, z

    def zoom_map(self, event):
        levels = MAP_ZOOM_LEVELS
        current = levels.index(self.minimap_settings["zoom"])
        current = min(len(levels) - 1, current + 1) if event.delta > 0 else max(0, current - 1)
        if levels[current] != self.minimap_settings["zoom"]:
            self.minimap_settings["zoom"] = levels[current]
            self.save_minimap_settings()
            self.draw_map()
        return "break"

    def map_hover(self, event):
        tile = self.map_tile(event)
        if tile is None:
            self.map_hover_status.set("")
            return
        x, y, z = tile
        walkable = self.minimap_map.is_walkable(x, y, z)
        self.map_hover_status.set(
            f"Pole pod kursorem: X={x}, Y={y}, Z={z}" + ("" if walkable else "  (nieprzechodnie)")
        )

    def map_press(self, event):
        self.map_drag_start = (event.x, event.y, self.map_center())
        self.map_dragged = False

    def map_drag(self, event):
        if self.map_drag_start is None or self.map_view is None:
            return
        start_x, start_y, center = self.map_drag_start
        if center is None:
            return
        if not self.map_dragged and abs(event.x - start_x) + abs(event.y - start_y) < px(5):
            return
        self.map_dragged = True
        zoom = self.map_view[3]
        self.map_pan = (
            center[0] - (event.x - start_x) // zoom,
            center[1] - (event.y - start_y) // zoom,
            center[2],
        )
        self.draw_map()

    def map_release(self, event):
        dragged = self.map_dragged
        self.map_drag_start = None
        self.map_dragged = False
        if dragged:
            return
        tile = self.map_tile(event)
        if tile is not None:
            self.add_waypoint(*tile)

    def map_remove_waypoint(self, event):
        tile = self.map_tile(event)
        if tile is None:
            return
        x, y, z = tile
        near = [
            (max(abs(item["x"] - x), abs(item["y"] - y)), i)
            for i, item in enumerate(self.waypoints) if item["z"] == z
        ]
        near = [item for item in near if item[0] <= max(1, px(8) // self.map_view[3])]
        if near:
            del self.waypoints[min(near)[1]]
            self.waypoints_changed()


    def start_minimap(self):
        if self.minimap_after_id is None:
            self.minimap_status.set("Śledzenie pozycji: uruchamiam…")
            self.minimap_after_id = self.root.after(300, self.minimap_tick)

    def refresh_minimap_map(self):
        """Load the client's newest .otmm, again whenever the client saves it."""
        now = time.monotonic()
        if self.minimap_map is not None and now - self.minimap_map_checked < 30:
            return
        self.minimap_map_checked = now
        path = find_otmm_file()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        if self.minimap_map is not None and (path, mtime) == self.minimap_map_source:
            return
        self.minimap_status.set(f"Wczytuję mapę {path.name}…")
        self.root.update_idletasks()
        self.minimap_map = OtmmMap.load(path)
        self.minimap_map_source = (path, mtime)
        last = self.minimap_tracker.last_position if self.minimap_tracker else None
        self.minimap_tracker = MinimapTracker(
            self.minimap_map, offset=tuple(self.minimap_settings["offset"])
        )
        self.minimap_tracker.last_position = last
        if self.cavebot_walker is not None:
            self.cavebot_walker.map = self.minimap_map

    def detect_minimap_region(self):
        """Find the minimap in a screenshot of the whole client window."""
        bounds = foreground_client_bounds(self.minimap_pid)
        if bounds is None:
            return None
        _x, _y, width, height = bounds
        image = capture_region(self.minimap_pid, (0, 0, width, height), grayscale=False, label="okna gry")
        if image is None:
            return None
        regions = find_minimap_region(image)
        if not regions:
            return []
        # Gdy kandydatów jest kilka, wybieramy ten, który daje się dopasować do mapy.
        for left, top, right, bottom in regions:
            self.minimap_tracker.reset()
            if self.minimap_tracker.update(image[top:bottom, left:right]).ok:
                return [(left, top, right, bottom)]
        return regions[:1]

    def minimap_tick(self):
        self.minimap_after_id = None
        delay = 300
        try:
            delay = self.minimap_step()
        except ImportError as exc:
            self.minimap_status.set(f"Śledzenie pozycji wymaga pakietów mss, opencv-python i numpy ({exc}).")
            delay = None
        except Exception as exc:
            # Błąd jednego zrzutu (np. zmiana rozmiaru okna) nie wyłącza śledzenia.
            self.minimap_region = None
            self.minimap_status.set(self.minimap_position_text(f"Błąd odczytu minimapy: {exc}"))
            delay = 2000
        if delay is not None and self.minimap_enabled_var.get():
            self.minimap_after_id = self.root.after(delay, self.minimap_tick)

    def minimap_step(self):
        """Run one tracking step and return the delay before the next one in ms."""
        import mss  # noqa: F401  — mss włącza świadomość DPI, zanim pobierzemy rozmiar okna

        if self.minimap_handle is not None and not self.minimap_process_is_alive():
            self.close_minimap_handle()
        if self.minimap_handle is None:
            pid, handle, _base, _path = find_process(STATUS_PROCESS_ACCESS)
            if not handle:
                self.minimap_status.set(self.minimap_position_text("Czekam na uruchomienie klienta RetronicDX…"))
                return 2000
            self.minimap_pid, self.minimap_handle = pid, handle
            self.minimap_region = None
        self.refresh_minimap_map()

        if self.minimap_region is None:
            regions = self.detect_minimap_region()
            if regions is None:
                self.minimap_status.set(self.minimap_position_text("Oczekuję na aktywne okno gry."))
                return 500
            if not regions:
                self.minimap_status.set(self.minimap_position_text(
                    "Nie widzę minimapy; otwórz okno Minimap w kliencie."
                ))
                return 1000
            self.minimap_region = regions[0]
            self.minimap_failures = 0

        image = capture_region(self.minimap_pid, self.minimap_region, grayscale=False, label="minimapy")
        if image is None:
            self.minimap_status.set(self.minimap_position_text("Oczekuję na aktywne okno gry."))
            return 500
        result = self.minimap_tracker.update(image)
        if not result.ok:
            self.minimap_failures += 1
            # Seria nieudanych odczytów: okno minimapy mogło zostać przesunięte.
            if self.minimap_failures >= 10:
                self.minimap_region = None
            self.minimap_status.set(self.minimap_position_text(result.reason))
            return 300
        self.minimap_failures = 0
        position = (result.x, result.y, result.z)
        if position != self.minimap_position:
            self.minimap_position = position
            self.draw_map()
        self.cavebot_step(position)
        self.minimap_status.set(
            f"Pozycja: X={result.x}, Y={result.y}, Z={result.z} "
            f"(dopasowanie {result.score:.2f}, {result.elapsed_ms:.0f} ms)\n"
            f"Mapa: {self.minimap_map_source[0].name}"
        )
        return 300

    def minimap_position_text(self, message):
        if self.minimap_position is None:
            return message
        x, y, z = self.minimap_position
        return f"{message}\nOstatnia pewna pozycja: X={x}, Y={y}, Z={z}"

    def minimap_process_is_alive(self):
        exit_code = wt.DWORD()
        return (
            self.minimap_handle is not None
            and GetExitCodeProcess(self.minimap_handle, ctypes.byref(exit_code))
            and exit_code.value == 259
        )

    def close_minimap_handle(self):
        if self.minimap_handle is not None:
            CloseHandle(self.minimap_handle)
            self.minimap_handle = None
        self.minimap_pid = None
        self.minimap_region = None

    def stop_minimap(self, status):
        if self.minimap_after_id is not None:
            self.root.after_cancel(self.minimap_after_id)
            self.minimap_after_id = None
        self.close_minimap_handle()
        self.minimap_status.set(status)

    def build_pickup_tab(self, parent):
        self.add_tab_header(parent, "Trainer", "Kamienie i spiry do lewej ręki, wędkowanie")
        left, right = self.add_columns(parent)

        group = self.add_group(left, "Zbieranie amunicji")
        self.pickup_button = self.add_switch_row(group, "Zbieraj amunicję", self.toggle_pickup)
        self.pickup_status = tk.StringVar(value="Zbieranie amunicji: wyłączone")
        self.add_status_label(group, self.pickup_status)
        card = self.add_card(group, "Ustawienia")
        ttk.Label(card, text="Odstęp skanowania:").grid(row=0, column=0, sticky="w")
        self.pickup_interval_min_var = tk.StringVar(value="0.5")
        ttk.Entry(card, textvariable=self.pickup_interval_min_var, width=6).grid(row=0, column=1, sticky="w", padx=px((8, 0)))
        ttk.Label(card, text="do").grid(row=0, column=2, padx=px(6))
        self.pickup_interval_max_var = tk.StringVar(value="1")
        ttk.Entry(card, textvariable=self.pickup_interval_max_var, width=6).grid(row=0, column=3, sticky="w")
        ttk.Label(card, text="sek.").grid(row=0, column=4, sticky="w", padx=px((6, 0)))
        ttk.Label(card, text="Próg dopasowania:").grid(row=1, column=0, sticky="w", pady=px((10, 0)))
        self.pickup_threshold_var = tk.StringVar(value="0.8")
        ttk.Entry(card, textvariable=self.pickup_threshold_var, width=6).grid(row=1, column=1, sticky="w", padx=px((8, 0)), pady=px((10, 0)))
        ttk.Label(card, text="0.5–0.99", style="Muted.TLabel").grid(row=1, column=2, columnspan=3, sticky="w", padx=px((6, 0)), pady=px((10, 0)))
        self.pickup_ctrl_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card, text="Przenoś cały stos (Ctrl przy upuszczaniu)",
                        variable=self.pickup_ctrl_var).grid(row=2, column=0, columnspan=5, sticky="w", pady=px((10, 0)))
        self.pickup_auto_var = tk.BooleanVar(value=self.automation.get("trainer_auto_area", True))
        ttk.Checkbutton(card, text="Pola wokół postaci:", variable=self.pickup_auto_var,
                        command=lambda: self.pickup_position_status.set(self.pickup_positions_text())).grid(row=3, column=0, sticky="w", pady=px((10, 0)))
        self.pickup_radius_var = tk.StringVar(value=str(self.automation.get("trainer_radius", "3 × 3")))
        ttk.Combobox(card, textvariable=self.pickup_radius_var, values=("3 × 3", "5 × 5"), width=6,
                     state="readonly").grid(row=3, column=1, columnspan=3, sticky="w", padx=px((8, 0)), pady=px((10, 0)))
        card.columnconfigure(4, weight=1)
        hint = ttk.Frame(group)
        hint.pack(fill="x", pady=px((6, 0)))
        ttk.Label(hint, text="Łapie tło? Podnieś próg. Nie widzi amunicji? Obniż go.", style="Muted.TLabel").pack(side="left")
        self.add_info(hint, "Bot co losowy odstęp skanuje pola wokół postaci (mapę gry i postać "
                            "znajduje sam, także gdy chodzisz za potworami), przeciąga najlepiej "
                            "dopasowany przedmiot do ręki i pomija na 30 s miejsce, którego nie udało się "
                            "podnieść w trzech próbach. Stos kilku kamieni wygląda inaczej niż jeden — "
                            "zapisz wzorzec dla każdego wyglądu. Przedmiot pod ciałem potwora nie jest widoczny.")

        self.build_fishing_group(left)

        group = self.add_group(right, "Pozycje w oknie gry")
        card = self.add_card(group)
        button = ttk.Button(card, text="Ustaw slot lewej ręki", command=lambda: self.toggle_pickup_capture("hand"))
        button.pack(fill="x", pady=px((0, 5)))
        self.pickup_capture_buttons["hand"] = (button, "Ustaw slot lewej ręki")
        manual = self.add_collapsible(card, "Ręczny obszar (gdy automat wyłączony)")
        for target, label in (
            ("area_top_left", "Ustaw lewy górny róg obszaru zbierania"),
            ("area_bottom_right", "Ustaw prawy dolny róg obszaru zbierania"),
        ):
            button = ttk.Button(manual, text=label, command=lambda value=target: self.toggle_pickup_capture(value))
            button.pack(fill="x", pady=px((0, 5)))
            self.pickup_capture_buttons[target] = (button, label)
        self.pickup_position_status = tk.StringVar(value=self.pickup_positions_text())
        row = ttk.Frame(card)
        row.pack(fill="x")
        ttk.Label(row, textvariable=self.pickup_position_status, style="Muted.TLabel").pack(side="left")
        self.add_info(row, "Pozycje zaznaczasz w grze klawiszem Shift + lewy klik (klient robi wtedy "
                           "tylko „Look”, postać nie idzie). Obszar obejmij zwykle 3 × 3 pola wokół "
                           "postaci, razem z polem pod nią.")

        group = self.add_group(right, "Wzorce przedmiotów")
        card = self.add_card(group)
        name_row = ttk.Frame(card)
        name_row.pack(fill="x")
        ttk.Label(name_row, text="Nazwa:").pack(side="left")
        self.pickup_template_name_var = tk.StringVar()
        ttk.Entry(name_row, textvariable=self.pickup_template_name_var).pack(side="left", fill="x", expand=True, padx=px((8, 0)))
        self.add_info(name_row, "Połóż przedmiot na ziemi, wpisz nazwę (np. Small Stone, Spear) i zaznacz "
                                "lewy górny oraz prawy dolny róg samego przedmiotu, bez tła dookoła.")
        template_buttons = ttk.Frame(card)
        template_buttons.pack(fill="x", pady=px((8, 0)))
        for target, label in (
            ("template_top_left", "Lewy górny róg"),
            ("template_bottom_right", "Prawy dolny róg"),
        ):
            button = ttk.Button(template_buttons, text=label, command=lambda value=target: self.toggle_pickup_capture(value))
            button.pack(side="left", fill="x", expand=True, padx=px((0, 3)))
            self.pickup_capture_buttons[target] = (button, label)
        ttk.Button(template_buttons, text="Usuń wzorzec", command=self.remove_pickup_template).pack(
            side="left", padx=px((3, 0))
        )
        self.pickup_template_status = tk.StringVar(value=self.pickup_templates_text())
        self.add_status_label(card, self.pickup_template_status, wrap=520)

    # --- karta Loot --------------------------------------------------------------

    def build_loot_tab(self, parent):
        self.add_tab_header(parent, "Loot", "Otwieranie ciał po walce, jedzenie i przenoszenie przedmiotów do plecaka")
        left, right = self.add_columns(parent)

        group = self.add_group(
            left, "Lootowanie",
            info="Działa z włączonym atakiem potworów z listy. Bot otwiera ciało zabitego potwora od razu "
                 "albo — gdy wyłączysz „od razu po zabiciu” — dopiero po walce, z kolejki od najbliższego "
                 "(okno ciała poznaje po tytule „Dead…”), rozpoznaje ikony w slotach, zjada „Meat”, przeciąga na slot plecaka "
                 "przedmioty zaznaczone w katalogu jako „Zabieraj” (całe stosy), sprawdza, czy zniknęły "
                 "z ciała, i zamyka jego okno. Gdy przedmiot dwa razy się nie przeniesie (pełny plecak, "
                 "za mały udźwig), przestaje i pisze o tym. F12 przerywa lootowanie.",
        )
        self.loot_pill = self.add_switch_row(group, "Zabieraj loot do plecaka", self.toggle_loot,
                                             on=self.cavebot_loot_var.get())
        self.loot_status = tk.StringVar(value="Loot: czekam na pierwsze ciało.")
        self.add_status_label(group, self.loot_status)

        card = self.add_card(group, "Ciała")
        for text, variable, command, tip in (
            ("Otwieraj ciała po walce", self.cavebot_inspect_corpses_var,
             self.on_cavebot_inspect_corpses_changed,
             "Bez lootowania bot tylko otwiera ciało i pisze, co rozpoznał."),
            ("Otwieraj ciało od razu po zabiciu", self.cavebot_loot_now_var,
             self.save_cavebot_profile,
             "Włączone: bot otwiera ciało zabitego potwora, zanim zaatakuje następnego "
             "(pozostałe potwory mogą go w tym czasie bić). Wyłączone: ciała czekają w kolejce "
             "i bot otwiera je od najbliższego, gdy nie ma już kogo atakować."),
            ("Zapisuj wzorce nowych przedmiotów", self.cavebot_learn_loot_var,
             self.on_cavebot_learn_loot_changed,
             "Każda nieznana ikona trafia do katalogu jako „Nowy przedmiot” i jest domyślnie pomijana."),
            ("Jedz „Meat” z ciał (prawy klik)", self.cavebot_use_meat_var,
             self.on_cavebot_use_meat_changed,
             "Działa, gdy w katalogu jest wzorzec nazwany dokładnie Meat (pole „Zabieraj” nie ma znaczenia)."),
        ):
            ttk.Checkbutton(card, text=text, variable=variable, command=command).pack(anchor="w", pady=px((2, 0)))
            self.add_tooltip(card.winfo_children()[-1], tip)

        card = self.add_card(group, "Plecak na loot")
        row = ttk.Frame(card)
        row.pack(fill="x")
        ttk.Button(row, text="Ustaw slot plecaka", command=self.start_loot_slot_capture).pack(side="left")
        self.add_info(row, "Otwórz plecak na loot, kliknij przycisk, wróć do gry i Shift + lewym klikiem "
                           "wskaż w nim pusty slot. Plecak musi zostać otwarty, a okno ciała nie może go "
                           "zasłaniać.")
        self.loot_slot_status = tk.StringVar(value=self.loot_slot_text())
        self.add_status_label(card, self.loot_slot_status)

        group = self.add_group(left, "Ostatnie ciało",
                               info="Powiększone okno ciała z wykrytymi slotami: szare — pusty slot, "
                                    "zielone — rozpoznany wzorzec, żółte — nieznany przedmiot. "
                                    "Ostatnie 20 obrazów jest w folderze loot_debug.")
        self.loot_preview = ttk.Label(group, text="Brak obrazu — pojawi się po pierwszym ciele.",
                                      style="Muted.TLabel")
        self.loot_preview.pack(anchor="w")
        ttk.Button(group, text="Otwórz folder loot_debug", command=self.open_loot_debug_folder).pack(
            anchor="w", pady=px((8, 0))
        )
        ttk.Label(group, text="Historia", style="CardTitle.TLabel").pack(anchor="w", pady=px((10, 0)))
        self.loot_history_list = self.make_listbox(group, height=6)
        self.loot_session_status = tk.StringVar(value=self.loot_session_text())
        self.add_status_label(group, self.loot_session_status)

        group = self.add_group(
            right, "Katalog przedmiotów",
            info="Ikony zapisane z ciał. „Zabieraj” = bot przenosi przedmiot do plecaka; nowe wzorce "
                 "są domyślnie pomijane (×). Ikonę mięsa nazwij dokładnie Meat i zaznacz, aby bot je jadł.",
        )
        self.loot_pattern_listbox = self.make_listbox(group, height=14)
        self.loot_pattern_listbox.bind("<<ListboxSelect>>", self.select_loot_pattern)
        self.loot_pattern_preview_photo = None
        self.loot_pattern_preview = ttk.Label(group, text="Zaznacz wzorzec, aby zobaczyć ikonę")
        self.loot_pattern_preview.pack(anchor="w", pady=px((6, 0)))
        editor = ttk.Frame(group)
        editor.pack(fill="x", pady=px((6, 0)))
        ttk.Label(editor, text="Nazwa:").grid(row=0, column=0, sticky="w")
        self.loot_pattern_name_var = tk.StringVar()
        ttk.Entry(editor, textvariable=self.loot_pattern_name_var).grid(
            row=0, column=1, sticky="ew", padx=px((8, 0))
        )
        self.loot_pattern_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            editor, text="Zabieraj (loot)",
            variable=self.loot_pattern_enabled_var,
        ).grid(row=1, column=1, sticky="w", pady=px((5, 0)))
        buttons = ttk.Frame(editor)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=px((5, 0)))
        ttk.Button(buttons, text="Zapisz nazwę i ustawienie", command=self.save_loot_pattern).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(buttons, text="Usuń wzorzec", command=self.remove_loot_pattern).pack(
            side="left", padx=px((6, 0))
        )
        editor.columnconfigure(1, weight=1)
        self.loot_pattern_status = tk.StringVar()
        self.add_status_label(group, self.loot_pattern_status)
        self.refresh_loot_patterns()

    def toggle_loot(self):
        self.cavebot_loot_var.set(not self.cavebot_loot_var.get())
        self.on_cavebot_loot_changed()

    def loot_summary_text(self):
        """One line for the Cavebot tab: what happens with corpses after a fight."""
        if self.cavebot_loot_var.get():
            return "Ciała: otwieram i zabieram loot (ustawienia w karcie „Loot”)."
        if self.cavebot_inspect_corpses_var.get():
            return "Ciała: otwieram, bez zabierania lootu (karta „Loot”)."
        return "Ciała: nie otwieram (karta „Loot”)."

    def loot_session_text(self):
        if not self.loot_session_counts:
            return "W tej sesji nic jeszcze nie zabrano."
        parts = [f"{name} ×{count}" for name, count in self.loot_session_counts.most_common()]
        return "Zabrano w tej sesji: " + ", ".join(parts)

    def refresh_loot_controls(self):
        """Sync the loot switch and summaries with the option variables."""
        self.loot_pill.set_on(self.cavebot_loot_var.get())
        self.cavebot_loot_summary.set(self.loot_summary_text())

    def open_loot_debug_folder(self):
        LOOT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(LOOT_DEBUG_DIR)

    def show_loot_preview(self, path):
        import base64
        import cv2

        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path else None
        if image is None:
            return
        # Obraz jest już powiększony 2×; zmniejszamy go, żeby historia była widoczna bez przewijania.
        limit = px(380)
        if image.shape[1] > limit:
            factor = limit / image.shape[1]
            image = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", image)
        if ok:
            self.loot_preview_photo = tk.PhotoImage(
                data=base64.b64encode(encoded.tobytes()).decode("ascii"), format="png"
            )
            self.loot_preview.configure(image=self.loot_preview_photo, text="")

    def record_loot_result(self, result):
        """Show one corpse result in the Loot tab (history, session totals, preview)."""
        self.loot_status.set(result["message"])
        self.loot_history.appendleft(f"{time.strftime('%H:%M:%S')}  {result['message']}")
        self.loot_history_list.delete(0, tk.END)
        for line in self.loot_history:
            self.loot_history_list.insert(tk.END, line)
        self.loot_session_counts.update(result.get("looted", []))
        self.loot_session_status.set(self.loot_session_text())
        self.show_loot_preview(result.get("debug"))

    def remove_loot_pattern(self):
        pattern_id = self.loot_pattern_selected
        if pattern_id is None:
            self.loot_pattern_status.set("Zaznacz wzorzec z listy, aby go usunąć.")
            return
        name = self.loot_patterns[pattern_id]["name"]
        if not messagebox.askyesno("Usuń wzorzec", f"Usunąć wzorzec „{name}” z katalogu?", parent=self.root):
            return
        try:
            remove_pattern(pattern_id)
        except (OSError, KeyError) as exc:
            self.loot_pattern_status.set(f"Nie udało się usunąć wzorca: {exc}")
            return
        self.loot_pattern_selected = None
        self.refresh_loot_patterns()
        self.loot_pattern_status.set(f"Usunięto wzorzec „{name}”.")

    def refresh_loot_patterns(self):
        if not hasattr(self, "loot_pattern_listbox"):
            return
        selected = self.loot_pattern_selected
        self.loot_patterns = load_patterns()
        self.loot_pattern_ids = sorted(self.loot_patterns)
        self.loot_pattern_listbox.delete(0, tk.END)
        for pattern_id in self.loot_pattern_ids:
            item = self.loot_patterns[pattern_id]
            marker = "✓" if item["enabled"] else "×"
            self.loot_pattern_listbox.insert(tk.END, f"{marker}  {item['name']}  [{pattern_id}]")
        if not self.loot_pattern_ids:
            self.loot_pattern_selected = None
            self.loot_pattern_preview.configure(image="", text="Zaznacz wzorzec, aby zobaczyć ikonę")
            self.loot_pattern_preview_photo = None
            self.loot_pattern_status.set("Nie zapisano jeszcze ikon z ciał.")
            return
        if selected not in self.loot_pattern_ids:
            selected = self.loot_pattern_ids[0]
        index = self.loot_pattern_ids.index(selected)
        self.loot_pattern_listbox.selection_set(index)
        self.loot_pattern_listbox.see(index)
        self.select_loot_pattern()

    def select_loot_pattern(self, _event=None):
        selection = self.loot_pattern_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self.loot_pattern_ids):
            return
        pattern_id = self.loot_pattern_ids[index]
        item = self.loot_patterns[pattern_id]
        self.loot_pattern_selected = pattern_id
        self.loot_pattern_name_var.set(item["name"])
        self.loot_pattern_enabled_var.set(item["enabled"])
        import base64
        import cv2

        image = item["image"]
        height, width = image.shape[:2]
        scale = max(1, min(4, 96 // max(height, width)))
        preview = cv2.resize(
            image, (width * scale, height * scale), interpolation=cv2.INTER_NEAREST
        )
        ok, encoded = cv2.imencode(".png", preview)
        if ok:
            self.loot_pattern_preview_photo = tk.PhotoImage(
                data=base64.b64encode(encoded.tobytes()).decode("ascii"), format="png"
            )
            self.loot_pattern_preview.configure(image=self.loot_pattern_preview_photo, text="")

    def save_loot_pattern(self):
        pattern_id = self.loot_pattern_selected
        if pattern_id is None:
            self.loot_pattern_status.set("Zaznacz wzorzec z listy, aby go edytować.")
            return
        try:
            update_pattern(
                pattern_id, self.loot_pattern_name_var.get(),
                self.loot_pattern_enabled_var.get(),
            )
        except (OSError, KeyError, ValueError) as exc:
            self.loot_pattern_status.set(f"Nie udało się zapisać zmian: {exc}")
            return
        self.refresh_loot_patterns()
        self.loot_pattern_status.set(f"Zapisano zmiany dla {pattern_id}.")
        index = self.loot_pattern_ids.index(pattern_id)
        self.loot_pattern_listbox.selection_set(index)
        self.loot_pattern_listbox.see(index)

    def pickup_positions_text(self):
        hand = (
            f"Lewa ręka: X={self.pickup_hand_position[0]}, Y={self.pickup_hand_position[1]}"
            if self.pickup_hand_position else "Lewa ręka: nieustawiona"
        )
        auto = getattr(self, "pickup_auto_var", None)
        if auto is not None and auto.get():
            area = "Obszar: automatycznie, pola wokół postaci"
        elif self.pickup_area:
            left, top, right, bottom = self.pickup_area
            area = f"Obszar: {left},{top} – {right},{bottom} ({right - left} × {bottom - top} px)"
        else:
            area = "Obszar zbierania: nieustawiony"
        return f"{hand}\n{area}"

    def pickup_templates_text(self):
        if not self.pickup_templates:
            return "Brak zapisanych wzorców."
        return "Zapisane wzorce: " + ", ".join(sorted(self.pickup_templates))

    def ensure_pickup_process(self):
        if self.pickup_handle is not None:
            return True
        try:
            pid, handle, _base, _path = find_process(STATUS_PROCESS_ACCESS)
        except Exception as exc:
            messagebox.showerror("Błąd klienta", str(exc), parent=self.root)
            return False
        if not handle:
            messagebox.showerror(
                "Nie znaleziono klienta", "Uruchom klienta RetronicDX.", parent=self.root
            )
            return False
        self.pickup_pid = pid
        self.pickup_handle = handle
        return True

    def pickup_process_is_alive(self):
        exit_code = wt.DWORD()
        return (
            self.pickup_handle is not None
            and GetExitCodeProcess(self.pickup_handle, ctypes.byref(exit_code))
            and exit_code.value == 259
        )

    def close_pickup_handle(self):
        if self.pickup_handle is not None:
            CloseHandle(self.pickup_handle)
            self.pickup_handle = None
        self.pickup_pid = None

    def toggle_pickup_capture(self, target):
        if self.pickup_after_id is not None:
            messagebox.showinfo(
                "Wyłącz zbieranie", "Najpierw wyłącz zbieranie amunicji.", parent=self.root
            )
            return
        if self.pickup_capture_target == target:
            self.cancel_pickup_capture()
            self.pickup_position_status.set("Zaznaczanie anulowane.")
            return
        self.cancel_pickup_capture()
        if target.startswith("template_"):
            name = " ".join(self.pickup_template_name_var.get().split())
            if not name:
                self.pickup_template_status.set("Najpierw wpisz nazwę przedmiotu dla wzorca.")
                return
        if not self.ensure_pickup_process():
            return
        self.pickup_capture_target = target
        self.pickup_left_was_down = left_button_down()
        button, _label = self.pickup_capture_buttons[target]
        button.configure(text="Shift + lewy klik w grze — anuluj")
        prompt = {
            "hand": "Wróć do gry i kliknij Shift + lewy przycisk na slocie lewej ręki.",
            "area_top_left": "Wróć do gry i kliknij Shift + lewy przycisk w lewym górnym rogu obszaru.",
            "area_bottom_right": "Wróć do gry i kliknij Shift + lewy przycisk w prawym dolnym rogu obszaru.",
            "template_top_left": "Wróć do gry i kliknij Shift + lewy przycisk w lewym górnym rogu przedmiotu.",
            "template_bottom_right": "Wróć do gry i kliknij Shift + lewy przycisk w prawym dolnym rogu przedmiotu.",
        }[target]
        status = (
            self.pickup_template_status if target.startswith("template_")
            else self.pickup_position_status
        )
        status.set(prompt)
        self.poll_pickup_capture()

    def cancel_pickup_capture(self):
        if self.pickup_capture_after_id is not None:
            self.root.after_cancel(self.pickup_capture_after_id)
            self.pickup_capture_after_id = None
        if self.pickup_capture_target is not None:
            button, label = self.pickup_capture_buttons[self.pickup_capture_target]
            button.configure(text=label)
        self.pickup_capture_target = None

    def poll_pickup_capture(self):
        self.pickup_capture_after_id = None
        target = self.pickup_capture_target
        if target is None or self.pickup_handle is None:
            return
        if not self.pickup_process_is_alive():
            self.cancel_pickup_capture()
            self.close_pickup_handle()
            self.pickup_position_status.set("Klient został zamknięty; zaznacz pozycję ponownie.")
            return
        is_down = left_button_down()
        if is_down and not self.pickup_left_was_down and shift_key_down():
            position = foreground_client_position(self.pickup_pid)
            if position is not None:
                self.cancel_pickup_capture()
                self.store_pickup_point(target, position)
                return
        self.pickup_left_was_down = is_down
        self.pickup_capture_after_id = self.root.after(15, self.poll_pickup_capture)

    def store_pickup_point(self, target, position):
        if target == "hand":
            self.pickup_hand_position = position
            self.automation["trainer_hand"] = list(position)
            self.save_automation()
        elif target.startswith("area_"):
            corner = target[len("area_"):]
            self.pickup_area_points[corner] = position
            top_left = self.pickup_area_points["top_left"]
            bottom_right = self.pickup_area_points["bottom_right"]
            self.pickup_area = None
            if top_left and bottom_right:
                if bottom_right[0] - top_left[0] < 20 or bottom_right[1] - top_left[1] < 20:
                    self.pickup_position_status.set(
                        "Obszar jest za mały lub rogi są w złej kolejności; zaznacz go ponownie."
                    )
                    return
                self.pickup_area = (*top_left, *bottom_right)
        else:
            corner = target[len("template_"):]
            self.pickup_template_points[corner] = position
            if corner == "top_left":
                self.pickup_template_status.set(
                    "Lewy górny róg zapisany. Zaznacz prawy dolny róg przedmiotu."
                )
            else:
                self.save_pickup_template()
            return
        self.pickup_position_status.set(self.pickup_positions_text())

    def save_pickup_template(self):
        name = " ".join(self.pickup_template_name_var.get().split())
        top_left = self.pickup_template_points["top_left"]
        bottom_right = self.pickup_template_points["bottom_right"]
        self.pickup_template_points = {"top_left": None, "bottom_right": None}
        if not name or top_left is None or bottom_right is None:
            self.pickup_template_status.set("Zaznacz oba rogi przedmiotu, aby zapisać wzorzec.")
            return
        try:
            template = save_pickup_template(self.pickup_pid, name, top_left, bottom_right)
        except Exception as exc:
            self.pickup_template_status.set(f"Nie udało się zapisać wzorca: {exc}")
            return
        if template is None:
            self.pickup_template_status.set(
                "Wróć do aktywnego okna gry i zaznacz wzorzec ponownie."
            )
            return
        self.pickup_templates[name] = template
        self.pickup_template_status.set(
            f"Wzorzec „{name}” zapisany. {self.pickup_templates_text()}"
        )

    def remove_pickup_template(self):
        name = " ".join(self.pickup_template_name_var.get().split())
        if name not in self.pickup_templates:
            self.pickup_template_status.set(
                f"Nie ma wzorca o nazwie „{name}”. {self.pickup_templates_text()}"
            )
            return
        try:
            remove_pickup_template(name)
        except (OSError, ValueError) as exc:
            self.pickup_template_status.set(f"Nie udało się usunąć wzorca: {exc}")
            return
        del self.pickup_templates[name]
        self.pickup_template_status.set(
            f"Wzorzec „{name}” usunięty. {self.pickup_templates_text()}"
        )

    def toggle_pickup(self):
        if self.pickup_after_id is not None:
            self.stop_pickup("Zbieranie amunicji: wyłączone")
            return
        auto_area = self.pickup_auto_var.get()
        if self.pickup_hand_position is None or (not auto_area and self.pickup_area is None):
            messagebox.showerror(
                "Brak pozycji",
                "Najpierw ustaw slot lewej ręki"
                + ("." if auto_area else " i oba rogi obszaru zbierania."),
                parent=self.root,
            )
            return
        if not self.pickup_templates:
            messagebox.showerror(
                "Brak wzorców",
                "Zapisz co najmniej jeden wzorzec kamienia lub spira.",
                parent=self.root,
            )
            return
        try:
            interval_min = float(self.pickup_interval_min_var.get().replace(",", "."))
            interval_max = float(self.pickup_interval_max_var.get().replace(",", "."))
            threshold = float(self.pickup_threshold_var.get().replace(",", "."))
            if not all(math.isfinite(value) for value in (interval_min, interval_max, threshold)):
                raise ValueError("Wpisz poprawne liczby.")
            if interval_min < 0.2 or interval_max < 0.2:
                raise ValueError("Odstęp skanowania musi wynosić co najmniej 0,2 sekundy.")
            if interval_min > interval_max:
                raise ValueError("Wartość „od” nie może być większa niż wartość „do”.")
            if not 0.5 <= threshold <= 0.99:
                raise ValueError("Próg dopasowania musi mieścić się w zakresie 0,5–0,99.")
        except ValueError as exc:
            messagebox.showerror("Nieprawidłowe ustawienia", str(exc), parent=self.root)
            return
        self.cancel_pickup_capture()
        if not self.ensure_pickup_process():
            return
        self.pickup_interval_min = interval_min
        self.pickup_interval_max = interval_max
        self.pickup_threshold = threshold
        self.pickup_count = 0
        self.pickup_last_attempt = None
        self.pickup_attempt_count = 0
        self.pickup_ignored_spots = {}
        self.pickup_view = None
        self.pickup_view_checked_at = -100.0
        self.automation.update(trainer_auto_area=auto_area, trainer_radius=self.pickup_radius_var.get())
        self.save_automation()
        self.pickup_button.set_on(True)
        self.pickup_status.set("Zbieranie amunicji włączone; wróć do gry.")
        self.schedule_pickup_tick(250)

    def schedule_pickup_tick(self, delay_ms=None):
        if delay_ms is None:
            delay_ms = int(random.uniform(self.pickup_interval_min, self.pickup_interval_max) * 1000)
        self.pickup_after_id = self.root.after(max(1, delay_ms), self.pickup_tick)

    def pickup_tick(self):
        self.pickup_after_id = None
        if not self.pickup_process_is_alive():
            self.stop_pickup("Zbieranie amunicji: klient został zamknięty")
            return
        if self.other_bot_functions_paused():
            self.schedule_pickup_tick(250)
            return
        area = self.pickup_area
        if self.pickup_auto_var.get():
            area = self.pickup_area_around_player()
            if area is None:
                self.pickup_status.set("Szukam mapy gry i postaci (wróć do gry)…")
                self.schedule_pickup_tick(1000)
                return
        try:
            detections = find_ground_items(
                self.pickup_pid, area, self.pickup_templates, self.pickup_threshold
            )
        except Exception as exc:
            self.stop_pickup("Zbieranie amunicji: zatrzymane z powodu błędu")
            messagebox.showerror("Błąd wyszukiwania amunicji", str(exc), parent=self.root)
            return
        if detections is None:
            self.pickup_status.set("Oczekuję na aktywne okno gry.")
            self.schedule_pickup_tick(500)
            return

        now = time.monotonic()
        self.pickup_ignored_spots = {
            spot: until for spot, until in self.pickup_ignored_spots.items() if until > now
        }
        candidates = [
            item for item in detections
            if not any(
                abs(item[2] - x) <= 8 and abs(item[3] - y) <= 8
                for x, y in self.pickup_ignored_spots
            )
        ]
        if not candidates:
            self.pickup_last_attempt = None
            self.pickup_attempt_count = 0
            self.pickup_status.set(
                f"Brak amunicji w obszarze; zebrano {self.pickup_count} razy."
            )
            self.schedule_pickup_tick()
            return

        score, name, x, y = candidates[0]
        last = self.pickup_last_attempt
        if last is not None and abs(last[0] - x) <= 8 and abs(last[1] - y) <= 8:
            self.pickup_attempt_count += 1
        else:
            self.pickup_attempt_count = 1
        self.pickup_last_attempt = (x, y)
        # Ten sam punkt wraca po kilku próbach: przedmiot jest nieruchomy,
        # ręka jest zajęta albo to fałszywe dopasowanie. Pomiń go na chwilę.
        if self.pickup_attempt_count > 3:
            self.pickup_ignored_spots[(x, y)] = now + 30
            self.pickup_last_attempt = None
            self.pickup_attempt_count = 0
            self.pickup_status.set(
                f"„{name}” przy X={x}, Y={y} nie daje się podnieść; pomijam to miejsce na 30 s."
            )
            self.schedule_pickup_tick()
            return
        try:
            dragged = drag_item(
                self.pickup_pid, x, y, *self.pickup_hand_position,
                hold_ctrl=self.pickup_ctrl_var.get(),
                out_of_window_message="Pozycja przedmiotu lub slotu lewej ręki jest poza oknem gry.",
            )
        except Exception as exc:
            self.stop_pickup("Zbieranie amunicji: zatrzymane z powodu błędu")
            messagebox.showerror("Błąd przeciągania amunicji", str(exc), parent=self.root)
            return
        if dragged:
            self.pickup_count += 1
            self.pickup_status.set(
                f"Przeniesiono „{name}” (dopasowanie {score:.2f}) do lewej ręki; "
                f"zebrano {self.pickup_count} razy."
            )
        else:
            self.pickup_status.set("Oczekuję na aktywne okno gry.")
        # Krótka przerwa, aby serwer zdążył przenieść przedmiot przed kolejnym skanem.
        self.schedule_pickup_tick(int(random.uniform(0.4, 0.7) * 1000))

    def pickup_area_around_player(self):
        """Client rectangle of the 3 × 3 (or 5 × 5) tiles around the character.

        Mapę gry bot znajduje raz; postać jest zawsze na środkowym polu mapy,
        więc obszar idzie razem z nią, także gdy chodzi za potworami.
        """
        now = time.monotonic()
        if self.pickup_view is None:
            if now - self.pickup_view_checked_at < 3.0:
                return None
            self.pickup_view_checked_at = now
            bounds = foreground_client_bounds(self.pickup_pid)
            if bounds is None:
                return None
            image = capture_region(self.pickup_pid, (0, 0, bounds[2], bounds[3]), grayscale=False, label="okna gry")
            if image is None:
                return None
            self.pickup_view = find_game_view(image[:, :, :3])
            if self.pickup_view is None:
                return None
        left, top, _right, _bottom = self.pickup_view
        tile = tile_size(self.pickup_view)
        radius = 2 if self.pickup_radius_var.get().startswith("5") else 1
        return (
            int(left + (7 - radius) * tile), int(top + (5 - radius) * tile),
            int(left + (8 + radius) * tile), int(top + (6 + radius) * tile),
        )

    def stop_pickup(self, status):
        if self.pickup_after_id is not None:
            self.root.after_cancel(self.pickup_after_id)
            self.pickup_after_id = None
        self.cancel_pickup_capture()
        self.close_pickup_handle()
        self.pickup_button.set_on(False)
        self.pickup_status.set(status)

    # --- wędkowanie ----------------------------------------------------------------

    def build_fishing_group(self, parent):
        group = self.add_group(
            parent, "Wędkowanie",
            info="Bot klika prawym przyciskiem wędkę (celownik „Use with…”), a potem lewym losowe "
                 "pole wody w zasięgu. Wodę zna z mapy .otmm i pozycji z minimapy, a na zrzucie "
                 "sprawdza, czy pole jest niebieskie (bez pozycji — tylko po kolorze). Złowione ryby "
                 "klient kładzie w osobnych slotach; co kilka rzutów bot przeciąga rybę z pierwszego "
                 "slotu na kolejny niepełny stos. Stos 100 sztuk rozpoznaje po tym, że przeciągnięcie "
                 "nic nie zmieniło. F12 zatrzymuje wędkowanie.",
        )
        self.fishing_button = self.add_switch_row(group, "Łów ryby", self.toggle_fishing)
        self.fishing_status = tk.StringVar(value="Wędkowanie: wyłączone")
        self.add_status_label(group, self.fishing_status)
        card = self.add_card(group, "Ustawienia")
        ttk.Label(card, text="Odstęp rzutów:").grid(row=0, column=0, sticky="w")
        self.fishing_min_var = tk.StringVar(value=str(self.automation.get("fishing_min", 1.2)))
        ttk.Entry(card, textvariable=self.fishing_min_var, width=6).grid(row=0, column=1, sticky="w", padx=px((8, 0)))
        ttk.Label(card, text="do").grid(row=0, column=2, padx=px(6))
        self.fishing_max_var = tk.StringVar(value=str(self.automation.get("fishing_max", 2.0)))
        ttk.Entry(card, textvariable=self.fishing_max_var, width=6).grid(row=0, column=3, sticky="w")
        ttk.Label(card, text="sek.").grid(row=0, column=4, sticky="w", padx=px((6, 0)))
        ttk.Label(card, text="Zasięg (pola):").grid(row=1, column=0, sticky="w", pady=px((10, 0)))
        self.fishing_range_var = tk.StringVar(value=str(self.automation.get("fishing_range", 6)))
        ttk.Combobox(card, textvariable=self.fishing_range_var, values=tuple(str(n) for n in range(1, 8)),
                     width=4, state="readonly").grid(row=1, column=1, sticky="w", padx=px((8, 0)), pady=px((10, 0)))
        self.fishing_stack_var = tk.BooleanVar(value=self.automation.get("fishing_stack", True))
        ttk.Checkbutton(card, text="Łącz ryby w jeden stos, co", variable=self.fishing_stack_var).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=px((10, 0)))
        self.fishing_stack_every_var = tk.StringVar(value=str(self.automation.get("fishing_stack_every", 3)))
        ttk.Entry(card, textvariable=self.fishing_stack_every_var, width=4).grid(row=2, column=3, sticky="w", pady=px((10, 0)))
        ttk.Label(card, text="rzuty").grid(row=2, column=4, sticky="w", padx=px((6, 0)), pady=px((10, 0)))
        card.columnconfigure(4, weight=1)

        card = self.add_card(group, "Wędka i ryba")
        row = ttk.Frame(card)
        row.pack(fill="x")
        ttk.Button(row, text="Ustaw wędkę", command=lambda: self.start_fishing_capture("fishing_rod")).pack(
            side="left", fill="x", expand=True, padx=px((0, 3)))
        ttk.Button(row, text="Ustaw rybę (wzorzec)", command=lambda: self.start_fishing_capture("fish")).pack(
            side="left", fill="x", expand=True, padx=px((3, 0)))
        self.add_info(row, "Shift + lewy klik w grze: na wędce i na rybie w plecaku. Wędkę trzymaj w ręce "
                           "albo w innym pojemniku niż ryby — nowa ryba przesuwa przedmioty w plecaku. "
                           "Wzorzec ryby jest potrzebny tylko do łączenia stosów. Wymaga klasycznego "
                           "sterowania (prawy klik = Use).")
        self.fishing_position_status = tk.StringVar(value=self.fishing_positions_text())
        self.add_status_label(card, self.fishing_position_status)

    def fishing_positions_text(self):
        rod = self.automation.get("fishing_rod")
        fish = "zapisany" if self.fishing_template is not None else "brak"
        return (f"Wędka: {'X=%d, Y=%d' % tuple(rod) if rod else 'nieustawiona'} · "
                f"wzorzec ryby: {fish}")

    def start_fishing_capture(self, key):
        if self.fishing_after_id is not None:
            messagebox.showinfo("Wyłącz wędkowanie", "Najpierw wyłącz wędkowanie.", parent=self.root)
            return
        where = "na wędce" if key == "fishing_rod" else "na rybie w plecaku"
        self.start_point_capture(key, where, status=self.fishing_position_status,
                                 on_point=self.store_fishing_point)

    def store_fishing_point(self, key, position):
        if key == "fish":
            image = self.capture_client()
            if image is None:
                self.fishing_position_status.set("Wróć do aktywnego okna gry i kliknij rybę ponownie.")
                return
            template = slot_crop(image, position, px(13)).copy()
            save_item_template("fish", template)
            self.fishing_template = template
        else:
            self.automation[key] = list(position)
            self.save_automation()
        self.fishing_position_status.set(self.fishing_positions_text())

    def toggle_fishing(self):
        if self.fishing_after_id is not None:
            self.stop_fishing("Wędkowanie: wyłączone")
            return
        if not self.automation.get("fishing_rod"):
            messagebox.showerror("Brak wędki", "Najpierw ustaw pozycję wędki.", parent=self.root)
            return
        stack = self.fishing_stack_var.get()
        if stack and self.fishing_template is None:
            messagebox.showerror("Brak wzorca ryby",
                                 "Zapisz wzorzec ryby albo wyłącz łączenie stosów.", parent=self.root)
            return
        try:
            low = float(self.fishing_min_var.get().replace(",", "."))
            high = float(self.fishing_max_var.get().replace(",", "."))
            every = int(self.fishing_stack_every_var.get())
            if not (math.isfinite(low) and math.isfinite(high)):
                raise ValueError("Wpisz poprawne liczby.")
            if low < 0.5 or high < 0.5:
                raise ValueError("Odstęp rzutów musi wynosić co najmniej 0,5 sekundy.")
            if low > high:
                raise ValueError("Wartość „od” nie może być większa niż wartość „do”.")
            if not 1 <= every <= 50:
                raise ValueError("Łączenie stosów: wpisz liczbę rzutów od 1 do 50.")
        except ValueError as exc:
            messagebox.showerror("Nieprawidłowe ustawienia", str(exc), parent=self.root)
            return
        if not self.ensure_battle_process():
            return
        self.automation.update(fishing_min=low, fishing_max=high, fishing_stack=stack,
                               fishing_stack_every=every, fishing_range=int(self.fishing_range_var.get()))
        self.save_automation()
        self.fishing_view = None
        self.fishing_view_at = -100.0
        self.fishing_recent.clear()
        self.fishing_casts = 0
        self.fishing_casts_since_stack = 0
        self.fishing_merges = 0
        self.fishing_full_crops = []
        self.fishing_verify = None
        self.fishing_button.set_on(True)
        self.fishing_status.set("Wędkowanie włączone; wróć do gry.")
        self.add_event("Wędkowanie włączone.")
        self.schedule_fishing_tick(300)

    def schedule_fishing_tick(self, delay_ms=None):
        if delay_ms is None:
            delay_ms = int(random.uniform(self.automation["fishing_min"], self.automation["fishing_max"]) * 1000)
        self.fishing_after_id = self.root.after(max(1, int(delay_ms)), self.fishing_tick)

    def fishing_tick(self):
        self.fishing_after_id = None
        try:
            delay = self.fishing_step()
        except Exception as exc:
            # Błąd jednego kroku (np. okno gry zmieniło rozmiar) nie wyłącza wędkowania.
            self.add_event(f"Wędkowanie: błąd kroku ({exc}); ponawiam.")
            self.fishing_view = None
            delay = 2000
        if delay is not False:
            self.schedule_fishing_tick(delay)

    def fishing_step(self):
        """One cast or one stack merge; returns the delay in ms (None = random interval, False = stop)."""
        if not self.ensure_battle_process():
            self.stop_fishing("Wędkowanie: klient został zamknięty")
            return False
        if self.other_bot_functions_paused():
            self.fishing_status.set("Pauza: wykryto wpis w Battle.")
            return 500
        image = self.capture_client()
        if image is None:
            self.fishing_status.set("Wędkowanie: czekam na aktywne okno gry.")
            return 500
        now = time.monotonic()
        if self.fishing_view is None or now - self.fishing_view_at > 30:
            self.fishing_view = find_game_view(image)
            self.fishing_view_at = now
            if self.fishing_view is None:
                self.fishing_status.set("Nie widzę mapy gry; sprawdzam ponownie.")
                return 1500
        if self.fishing_verify is not None:
            return self.fishing_check_merge(image)
        if (self.automation["fishing_stack"] and self.fishing_template is not None
                and self.fishing_casts_since_stack >= self.automation["fishing_stack_every"]):
            delay = self.fishing_merge(image)
            if delay is not None:
                return delay
        return self.fishing_cast(image)

    def fishing_cast(self, image):
        view = self.fishing_view
        reach = self.automation["fishing_range"]
        position = self.minimap_position
        if position is not None and self.minimap_map is not None:
            tiles = fishing.water_tiles(self.minimap_map, position, reach)
            # Mapa mówi, gdzie jest woda; zrzut odrzuca pola zasłonięte (statek, stwór, przedmiot).
            tiles = [tile for tile in tiles if fishing.looks_like_water(image, view, *tile)] or tiles
            source = "mapa"
        else:
            tiles = fishing.visible_water(image, view, reach)
            source = "zrzut"
        tile = fishing.pick_tile(tiles, self.fishing_recent)
        if tile is None:
            self.fishing_status.set(f"Brak wody w zasięgu {reach} pól; podejdź bliżej wody.")
            return 1500
        rod = self.automation["fishing_rod"]
        x, y = fishing.tile_center(view, *tile)
        spread = tile_size(view) * 0.3
        # Prawy klik na wędce włącza celownik „Use with…”, lewy klik wskazuje pole wody.
        if not send_right_click(self.battle_pid, human.jitter(rod[0], px(3)), human.jitter(rod[1], px(3))):
            self.fishing_status.set("Wędkowanie: czekam na aktywne okno gry.")
            return 500
        time.sleep(random.uniform(0.15, 0.35) if human.enabled() else 0.1)
        if not send_left_click(self.battle_pid, human.jitter(x, spread), human.jitter(y, spread)):
            return 500
        self.fishing_recent.append(tile)
        self.fishing_casts += 1
        self.fishing_casts_since_stack += 1
        self.fishing_status.set(
            f"Rzut {self.fishing_casts}: pole {tile[0]:+d}, {tile[1]:+d} ({len(tiles)} pól wody, {source}); "
            f"połączono stosy {self.fishing_merges} razy.")
        pause = human.maybe_break()
        return int(pause * 1000) if pause else None

    def fishing_slots(self, image):
        return fishing.find_fish_slots(image, self.fishing_template, exclude=(self.fishing_view,))

    def fishing_merge(self, image):
        """Drag the first fish slot onto the next stack that is not full; None when nothing to merge."""
        slots = self.fishing_slots(image)
        half = px(13)

        def is_full(slot):
            crop = slot_crop(image, slot, half)
            return any(similarity(crop, full) >= 0.97 for full in self.fishing_full_crops)

        move = fishing.stack_move(slots, is_full)
        if move is None:
            self.fishing_casts_since_stack = 0
            return None
        source, target = move
        if not drag_item(self.battle_pid, *source, *target,
                         out_of_window_message="Slot z rybą jest poza oknem gry."):
            return 500
        self.fishing_verify = {"count": len(slots), "source": source,
                               "source_crop": slot_crop(image, source, half).copy(),
                               "target_crop": slot_crop(image, target, half).copy()}
        self.fishing_status.set(f"Łączę ryby: {len(slots)} slotów z rybą.")
        return int(random.uniform(0.5, 0.8) * 1000)

    def fishing_check_merge(self, image):
        """After a drag: fewer fish slots = merged; unchanged source = the target stack is full."""
        verify, self.fishing_verify = self.fishing_verify, None
        slots = self.fishing_slots(image)
        if len(slots) < verify["count"]:
            self.fishing_merges += 1
        elif similarity(slot_crop(image, verify["source"], px(13)), verify["source_crop"]) >= 0.95:
            self.fishing_full_crops.append(verify["target_crop"])
            self.add_event("Wędkowanie: stos ryb jest pełny, łączę z kolejnym.")
        # Kolejne łączenie od razu, dopóki są sloty do połączenia; potem znowu rzuty.
        return 300

    def stop_fishing(self, status):
        if self.fishing_after_id is not None:
            self.root.after_cancel(self.fishing_after_id)
            self.fishing_after_id = None
        self.fishing_verify = None
        if hasattr(self, "fishing_button"):
            self.fishing_button.set_on(False)
            self.fishing_status.set(status)

    # --- Runemaker i Mana trainer ------------------------------------------------------

    def save_automation(self):
        try:
            save_automation_settings(self.automation)
        except OSError as exc:
            self.add_event(f"Nie udało się zapisać automation.json: {exc}")

    def rune_positions_text(self):
        def point(key):
            value = self.automation.get(key)
            return f"X={value[0]}, Y={value[1]}" if value else "nieustawiony"

        blank = "zapisany" if self.rune_blank_template is not None else "brak"
        return (f"Prawa ręka: {point('rune_hand')} · główny plecak: {point('rune_backpack')}\n"
                f"Wzorzec blank runy: {blank}")

    def start_rune_point_capture(self, key):
        if self.rune_running:
            messagebox.showinfo("Wyłącz Runemaker", "Najpierw wyłącz Runemaker.", parent=self.root)
            return
        where = {
            "rune_hand": "na slocie prawej ręki w oknie Inventory",
            "rune_backpack": "na slocie plecaka w oknie Inventory",
            "blank_rune": "na blank runie w otwartym plecaku",
        }[key]
        self.start_point_capture(key, where, status=self.rune_position_status, on_point=self.store_rune_point)

    def store_rune_point(self, key, position):
        if key == "blank_rune":
            image = self.capture_client()
            if image is None:
                self.rune_position_status.set("Wróć do aktywnego okna gry i kliknij blank ponownie.")
                return
            template = slot_crop(image, position, px(13)).copy()
            save_item_template("blank_rune", template)
            self.rune_blank_template = template
        else:
            self.automation[key] = list(position)
            self.save_automation()
        self.rune_position_status.set(self.rune_positions_text())

    def capture_client(self):
        """Full client screenshot (BGR) or None when the game is not in front."""
        pid = self.rune_pid or self.battle_pid
        bounds = foreground_client_bounds(pid)
        if bounds is None:
            return None
        image = capture_region(pid, (0, 0, bounds[2], bounds[3]), grayscale=False, label="okna gry")
        return None if image is None else image[:, :, :3]

    def read_rune_number(self, variable, label, low, high):
        value = float(variable.get().replace(",", ".").replace("%", "").strip())
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{label}: wpisz liczbę od {low:g} do {high:g}.")
        return value

    def toggle_rune_making(self):
        if self.rune_running:
            self.stop_rune_making("Runemaker: wyłączony")
            return
        missing = [label for key, label in (("rune_hand", "slot prawej ręki"), ("rune_backpack", "główny plecak"))
                   if not self.automation.get(key)]
        if self.rune_blank_template is None:
            missing.append("wzorzec blank runy")
        if missing:
            messagebox.showerror("Brak ustawień", "Ustaw najpierw: " + ", ".join(missing) + ".", parent=self.root)
            return
        try:
            mana = self.read_rune_number(self.rune_mana_var, "Próg many", 1, 100)
            spell = self.checked_spell(self.rune_spell_var.get())
            find_tesseract()
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Nieprawidłowe ustawienia", str(exc), parent=self.root)
            return
        if not self.ensure_rune_process():
            return
        self.automation.update(rune_spell=spell, rune_mana_pct=mana)
        self.save_automation()
        self.rune_running = True
        self.rune_cycle = None
        self.rune_failures = 0
        self.rune_no_blanks_until = 0.0
        self.runes_created = 0
        self.rune_button.set_on(True)
        self.rune_status.set(f"Runemaker włączony; czekam na manę ≥ {mana:g}%.")
        self.add_event("Runemaker włączony.")
        self.schedule_rune_tick(200)

    def toggle_mana_trainer(self):
        if self.trainer_running:
            self.stop_mana_trainer("Mana trainer: wyłączony")
            return
        try:
            mana = self.read_rune_number(self.trainer_mana_var, "Próg many", 1, 100)
            low = self.read_rune_number(self.trainer_min_var, "Odstęp od", 0.5, 600)
            high = self.read_rune_number(self.trainer_max_var, "Odstęp do", 0.5, 600)
            if low > high:
                raise ValueError("Wartość „od” nie może być większa niż „do”.")
            spell = self.checked_spell(self.trainer_spell_var.get())
            find_tesseract()
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Nieprawidłowe ustawienia", str(exc), parent=self.root)
            return
        if not self.ensure_rune_process():
            return
        self.automation.update(trainer_spell=spell, trainer_mana_pct=mana, trainer_min=low, trainer_max=high)
        self.save_automation()
        self.trainer_running = True
        self.mana_trainer_next_at = 0.0
        self.trainer_button.set_on(True)
        self.trainer_status.set(f"Mana trainer włączony; czekam na manę ≥ {mana:g}%.")
        self.add_event("Mana trainer włączony.")
        self.schedule_rune_tick(200)

    def checked_spell(self, text):
        spell = " ".join(text.split())
        if not spell or any(ord(char) < 32 or ord(char) > 0xFFFF for char in spell):
            raise ValueError("Wpisz zaklęcie bez nowych linii i nietypowych znaków.")
        return spell

    def ensure_rune_process(self):
        if self.rune_handle is not None:
            exit_code = wt.DWORD()
            if GetExitCodeProcess(self.rune_handle, ctypes.byref(exit_code)) and exit_code.value == 259:
                return True
            self.close_rune_handle()
        try:
            pid, handle, _base, _path = find_process(STATUS_PROCESS_ACCESS)
        except Exception as exc:
            messagebox.showerror("Błąd klienta", str(exc), parent=self.root)
            return False
        if not handle:
            messagebox.showerror("Nie znaleziono klienta", "Uruchom klienta RetronicDX.", parent=self.root)
            return False
        self.rune_pid = pid
        self.rune_handle = handle
        return True

    def rune_process_is_alive(self):
        if self.rune_handle is None:
            return False
        exit_code = wt.DWORD()
        return bool(
            GetExitCodeProcess(self.rune_handle, ctypes.byref(exit_code))
            and exit_code.value == 259
        )

    def schedule_rune_tick(self, delay=600):
        if self.rune_after_id is not None:
            self.root.after_cancel(self.rune_after_id)
        self.rune_after_id = self.root.after(max(1, int(delay)), self.rune_tick)

    # --- mana z okna Health Info ---

    def reset_vitals_window(self):
        self.vitals_window = None
        self.vitals_detect_state = None
        self.vitals_bar_width = 0
        if not self.ensure_rune_process():
            return
        self.vitals_status.set("Szukam okna Health Info — wróć do gry.")
        self.read_mana(time.monotonic())

    def read_mana(self, now):
        """Current vitals dict from Health Info or None (still searching / game not in front)."""
        if self.vitals_window is None:
            state = self.vitals_detect_state
            if state is None:
                image = self.capture_client()
                if image is None:
                    self.vitals_status.set("Okno Health Info: czekam na aktywne okno gry.")
                    return None
                state = {"done": False, "windows": [], "error": None}

                def work(image=image, state=state):
                    try:
                        state["windows"] = find_mini_windows(image, find_tesseract())
                    except Exception as exc:  # błąd OCR tytułów nie może zatrzymać pętli Tk
                        state["error"] = exc
                    state["done"] = True

                threading.Thread(target=work, daemon=True).start()
                self.vitals_detect_state = state
                self.vitals_status.set("Szukam okna Health Info…")
                return None
            if not state["done"]:
                return None
            self.vitals_detect_state = None
            for title, region in state["windows"]:
                letters = "".join(char for char in title.lower() if char.isalpha())
                if "health" in letters or "info" in letters:
                    self.vitals_window = region
                    break
            if self.vitals_window is None:
                titles = ", ".join(title for title, _region in state["windows"]) or "żadnych"
                self.vitals_status.set(f"Nie widzę okna Health Info (okna: {titles}). Otwórz je w kliencie.")
                return None
        crop = capture_region(self.rune_pid, self.vitals_window, grayscale=False, label="Health Info")
        if crop is None:
            return None
        use_ocr = now - self.vitals_ocr_at >= 3.0
        vitals = read_vitals(crop[:, :, :3], self.vitals_bar_width, use_ocr=use_ocr)
        if vitals is None:
            self.vitals_misses += 1
            if self.vitals_misses >= 5:
                self.vitals_window = None
                self.vitals_misses = 0
            self.vitals_status.set("Nie widzę paska many w oknie Health Info.")
            return None
        self.vitals_misses = 0
        self.vitals_bar_width = vitals["bar_width"]
        if vitals["mana"]:
            self.vitals_ocr_at = now
            self.vitals = vitals
        elif self.vitals and self.vitals.get("mana"):
            vitals["mana"] = self.vitals["mana"]
        self.vitals = vitals
        numbers = f"{vitals['mana'][0]}/{vitals['mana'][1]} · " if vitals["mana"] else ""
        self.vitals_status.set(f"Mana: {numbers}{vitals['mana_pct']:.0f}% (okno Health Info)")
        return vitals

    # --- pętla ---

    def rune_tick(self):
        self.rune_after_id = None
        if not (self.rune_running or self.trainer_running):
            return
        if not self.rune_process_is_alive():
            self.stop_rune_making("Runemaker: klient został zamknięty")
            self.stop_mana_trainer("Mana trainer: klient został zamknięty")
            return
        delay = 600
        try:
            if self.rune_battle_paused or self.other_bot_functions_paused():
                self.rune_status.set("Pauza: wykryto wpis w Battle.")
            elif self.rune_running and self.rune_cycle is not None:
                delay = self.runemaker_step(time.monotonic())
            else:
                now = time.monotonic()
                vitals = self.read_mana(now)
                if vitals is not None:
                    delay = self.mana_actions(vitals, now)
        except Exception as exc:
            # Błąd jednego kroku (np. okno gry zmieniło rozmiar) nie wyłącza modułów.
            self.add_event(f"Runemaker: błąd kroku ({exc}); ponawiam.")
            delay = 2000
        if self.rune_running or self.trainer_running:
            self.schedule_rune_tick(delay)

    def mana_actions(self, vitals, now):
        """Start a rune cycle or cast the training spell, Runemaker first."""
        pct = vitals["mana_pct"]
        blanks_ready = self.rune_running and now >= self.rune_no_blanks_until
        if blanks_ready:
            threshold = self.automation["rune_mana_pct"]
            if pct >= threshold:
                self.rune_cycle = {"step": "start", "at": now + self.action_pause(), "tries": 0}
                self.rune_status.set(f"Mana {pct:.0f}% — zaczynam robić runę.")
                return 150
            self.rune_status.set(f"Mana {pct:.0f}%; runa od {threshold:g}% (zrobiono {self.runes_created}).")
        if self.trainer_running:
            threshold = self.automation["trainer_mana_pct"]
            if blanks_ready:
                self.trainer_status.set("Czekam: mana idzie na runy (Runemaker ma blanki).")
            elif pct < threshold:
                self.trainer_status.set(f"Mana {pct:.0f}%; rzucam od {threshold:g}%.")
            elif now >= self.mana_trainer_next_at:
                spell = self.automation["trainer_spell"]
                if send_spell(spell, self.rune_pid):
                    low, high = self.automation["trainer_min"], self.automation["trainer_max"]
                    self.mana_trainer_next_at = now + random.uniform(low, high)
                    self.trainer_status.set(f"Rzucono „{spell}” przy manie {pct:.0f}%.")
                else:
                    self.trainer_status.set("Czekam na aktywne okno gry.")
        return 600

    def action_pause(self):
        """Pause between two inventory moves (longer and uneven in Human mode)."""
        if human.enabled():
            return human.reaction("attack") + random.uniform(0.2, 0.5)
        return random.uniform(0.35, 0.6)

    # --- cykl jednej runy ---

    def runemaker_step(self, now):
        """One step of the rune cycle; returns the delay to the next tick in ms.

        start → (unequip → check_unequip) → equip → check_equip → cast → check_cast
        → store → check_store → (reequip → check_reequip) → koniec
        """
        cycle = self.rune_cycle
        if now < cycle["at"]:
            return max(50, int((cycle["at"] - now) * 1000))
        image = self.capture_client()
        if image is None:
            self.rune_status.set("Runemaker: czekam na aktywne okno gry.")
            return 500
        hand_point = tuple(self.automation["rune_hand"])
        half = px(14)
        hand = slot_crop(image, hand_point, half).copy()
        blank = self.rune_blank_template
        step = cycle["step"]
        pause = self.action_pause()

        def go(next_step, wait=pause, **values):
            cycle.update(values, step=next_step, at=now + wait, tries=0 if next_step != step else cycle["tries"])
            return 120

        def retry(message, limit=2):
            cycle["tries"] += 1
            if cycle["tries"] > limit:
                return None
            self.rune_status.set(f"{message}; ponawiam ({cycle['tries']}/{limit}).")
            cycle["at"] = now + pause + 0.5
            return 120

        if step == "start":
            cycle["hand0"] = hand
            if image_contains(hand, blank):
                return go("cast", 0.1, equip=None, source=None)
            if self.rune_search(image, blank, 0.8, hand_point) is None:
                # Bez blanków nie ruszamy przedmiotu w ręce.
                self.rune_cycle = None
                self.rune_no_blanks_until = now + 30.0
                self.add_event("Runemaker: brak blank run w otwartych plecakach.")
                self.rune_status.set("Brak blank run — sprawdzę znowu za 30 s (mana trainer może działać).")
                return 600
            if not self.drag_rune_item(hand_point, tuple(self.automation["rune_backpack"])):
                return 500
            self.rune_status.set("Zdejmuję przedmiot z prawej ręki do plecaka…")
            return go("check_unequip", pause + 0.4)
        if step == "check_unequip":
            if similarity(hand, cycle["hand0"]) < 0.85:
                # Ręka się zmieniła: przedmiot jest w plecaku. Zapamiętujemy jego wygląd
                # (środek slotu), żeby potem znaleźć go w otwartym plecaku.
                inner = px(10)
                cycle["equip"] = slot_crop(cycle["hand0"], (half, half), inner).copy()
                cycle["empty"] = hand
                return go("equip")
            if cycle["tries"] >= 1:
                # Nic się nie zmienia: ręka była pusta, nie ma czego zdejmować.
                cycle["equip"] = None
                cycle["empty"] = hand
                return go("equip", 0.1)
            cycle["tries"] += 1
            self.drag_rune_item(hand_point, tuple(self.automation["rune_backpack"]))
            cycle["at"] = now + pause + 0.4
            return 120
        if step == "equip":
            found = self.rune_search(image, blank, 0.8, hand_point)
            if found is None:
                self.rune_no_blanks_until = now + 30.0
                self.add_event("Runemaker: brak blank run w otwartych plecakach.")
                self.rune_status.set("Brak blank run — sprawdzę znowu za 30 s (mana trainer może działać).")
                return go("reequip", 0.1)
            x, y, _score = found
            if not self.drag_rune_item((x, y), hand_point):
                return 500
            self.rune_status.set("Blank runa do prawej ręki…")
            return go("check_equip", pause + 0.4, source=(x, y))
        if step == "check_equip":
            if image_contains(hand, blank):
                return go("cast", 0.2)
            delay = retry("Blank nie jest w ręce")
            if delay is not None:
                self.drag_rune_item(cycle["source"], hand_point)
                return delay
            return self.rune_cycle_failed("Nie udało się włożyć blank runy do ręki.", "reequip")
        if step == "cast":
            spell = self.automation["rune_spell"]
            if not send_spell(spell, self.rune_pid):
                return 500
            self.rune_status.set(f"Rzucam „{spell}”…")
            return go("check_cast", 1.2 + random.uniform(0, 0.6))
        if step == "check_cast":
            if not image_contains(hand, blank) and similarity(hand, cycle.get("empty")) < 0.85:
                self.runes_created += 1
                self.add_event(f"Runemaker: runa nr {self.runes_created} gotowa.")
                return go("store", rune=hand)
            delay = retry("Blank nadal jest w ręce (za mało many?)")
            if delay is not None:
                cycle["step"] = "cast"
                cycle["at"] = now + 2.0
                return delay
            self.add_event("Runemaker: zaklęcie nie zrobiło runy; odkładam blank.")
            return go("store", rune=hand)
        if step == "store":
            target = cycle.get("source") or tuple(self.automation["rune_backpack"])
            if not self.drag_rune_item(hand_point, target):
                return 500
            self.rune_status.set("Odkładam runę do plecaka…")
            return go("check_store", pause + 0.4)
        if step == "check_store":
            if similarity(hand, cycle["rune"]) < 0.85:
                return go("reequip")
            delay = retry("Runa nadal jest w ręce")
            if delay is not None:
                self.drag_rune_item(hand_point, cycle.get("source") or tuple(self.automation["rune_backpack"]))
                return delay
            return self.rune_cycle_failed("Nie udało się odłożyć runy (pełny plecak?).", stop=True)
        if step == "reequip":
            if cycle.get("equip") is None:
                return self.finish_rune_cycle()
            found = self.rune_search(image, cycle["equip"], 0.7, hand_point)
            if found is None:
                return self.rune_cycle_failed(
                    "Nie widzę przedmiotu zdjętego z ręki — otwórz główny plecak.", stop=True
                )
            if not self.drag_rune_item(found[:2], hand_point):
                return 500
            self.rune_status.set("Wkładam przedmiot z powrotem do ręki…")
            return go("check_reequip", pause + 0.4, equip_from=found[:2])
        if step == "check_reequip":
            if similarity(hand, cycle["hand0"]) >= 0.85:
                return self.finish_rune_cycle()
            delay = retry("Przedmiot nie wrócił do ręki")
            if delay is not None:
                cycle["step"] = "reequip"
                return delay
            return self.rune_cycle_failed("Nie udało się włożyć przedmiotu z powrotem do ręki.", stop=True)
        return self.finish_rune_cycle()

    def rune_search(self, image, template, threshold, hand_point):
        """Find an item in the side panels (containers), skipping the game map and the hand slot."""
        if self.rune_screen_view is None:
            self.rune_screen_view = find_game_view(image) or (0, 0, 0, 0)
        view = self.rune_screen_view
        height, width = image.shape[:2]
        regions = [(0, 0, view[0], height), (view[2], 0, width, height)] if view[2] else None
        half = px(18)
        x, y = hand_point
        return find_item(image, template, threshold, regions=regions,
                         exclude=[(x - half, y - half, x + half, y + half)])

    def drag_rune_item(self, source, target):
        return drag_item(
            self.rune_pid, int(source[0]), int(source[1]), int(target[0]), int(target[1]),
            out_of_window_message="Pozycja slotu jest poza oknem gry; ustaw ją ponownie.",
        )

    def finish_rune_cycle(self):
        self.rune_cycle = None
        self.rune_failures = 0
        self.rune_status.set(f"Gotowe; zrobiono {self.runes_created} run. Czekam na manę.")
        return 600

    def rune_cycle_failed(self, message, next_step=None, stop=False):
        self.add_event(f"Runemaker: {message}")
        self.rune_failures += 1
        if stop or self.rune_failures >= 3:
            self.stop_rune_making(f"Runemaker zatrzymany: {message}")
            self.root.bell()
            return 600
        if next_step:
            self.rune_cycle.update(step=next_step, tries=0, at=time.monotonic() + 0.5)
            return 300
        self.rune_cycle = None
        return 600

    def stop_rune_making(self, status):
        self.rune_running = False
        self.rune_cycle = None
        self.rune_battle_paused = False
        self.rune_button.set_on(False)
        self.rune_status.set(status)
        self.stop_rune_loop_if_idle()

    def stop_mana_trainer(self, status):
        self.trainer_running = False
        self.trainer_button.set_on(False)
        self.trainer_status.set(status)
        self.stop_rune_loop_if_idle()

    def stop_rune_loop_if_idle(self):
        if self.rune_running or self.trainer_running:
            return
        if self.rune_after_id is not None:
            self.root.after_cancel(self.rune_after_id)
            self.rune_after_id = None
        self.close_rune_handle()

    def close_rune_handle(self):
        if self.rune_handle is not None:
            CloseHandle(self.rune_handle)
            self.rune_handle = None
        self.rune_pid = None

    def add_battle_profile_controls(self, parent, profile, title, switch=True):
        if switch:
            monitor_button = self.add_switch_row(
                parent, title, lambda key=profile: self.toggle_battle_monitor(key)
            )
        else:
            monitor_button = _NoSwitch()
        self.battle_monitors[profile]["button"] = monitor_button
        monitor_status = tk.StringVar(value="Wykrywanie Battle: wyłączone")
        self.battle_monitors[profile]["status"] = monitor_status
        ttk.Label(parent, textvariable=monitor_status, style="Muted.TLabel", wraplength=px(320)).pack(
            anchor="w", pady=px((4, 0))
        )
        frame = self.add_collapsible(
            parent, "Kalibracja obszaru Battle" if switch else "Ręczny obszar Battle (awaryjnie)"
        )
        buttons = {}
        for corner, label in (
            ("top_left", "Ustaw lewy górny róg"),
            ("bottom_right", "Ustaw prawy dolny róg"),
        ):
            button = ttk.Button(
                frame,
                text=label,
                command=lambda value=corner, key=profile: self.toggle_battle_capture(value, key),
            )
            button.pack(fill="x", pady=px((0, 5)))
            buttons[corner] = button
        self.battle_capture_buttons[profile] = buttons
        status = tk.StringVar(value="Obszar Battle nieustawiony")
        self.battle_profile_status[profile] = status
        ttk.Label(frame, textvariable=status, style="Muted.TLabel", wraplength=px(532)).pack(
            anchor="w", pady=px((2, 0))
        )

    def add_section(self, parent, title):
        ttk.Label(parent, text=title.upper(), style="Section.TLabel").pack(anchor="w", pady=px((18, 2)))

    def add_switch_row(self, parent, title, command, on=False):
        """Wiersz z nazwą modułu i przełącznikiem On/Off po prawej."""
        row = ttk.Frame(parent, style="Row.TFrame", padding=px((10, 5)))
        row.pack(fill="x", pady=px((4, 0)))
        ttk.Label(row, text=title, style="Row.TLabel").pack(side="left")
        pill = PillButton(row, command, on=on)
        pill.pack(side="right")
        return pill

    def add_collapsible(self, parent, title):
        """Zwijana sekcja z rzadziej używanymi ustawieniami; zwraca jej zawartość."""
        holder = ttk.Frame(parent)
        holder.pack(fill="x", pady=px((4, 0)))
        header = ttk.Button(holder, style="Row.TButton")
        header.pack(fill="x")
        body = ttk.Frame(holder, padding=px((10, 8, 4, 4)))
        state = {"open": False}

        def toggle():
            state["open"] = not state["open"]
            if state["open"]:
                body.pack(fill="x")
            else:
                body.pack_forget()
            header.configure(text=f"{'▾' if state['open'] else '▸'}  {title}")

        header.configure(text=f"▸  {title}", command=toggle)
        return body

    def load_battle_templates(self):
        """Load saved grayscale name crops for image-based Battle matching."""
        if not self.battle_template_manifest.exists():
            return {}
        try:
            import cv2

            entries = json.loads(self.battle_template_manifest.read_text(encoding="utf-8"))
            result = {}
            for name, filename in entries.items():
                safe_name = Path(filename).name
                image = cv2.imread(
                    str(self.battle_template_dir / safe_name), cv2.IMREAD_GRAYSCALE
                )
                if image is not None and name.strip():
                    result[" ".join(name.split()).casefold()] = image
            return result
        except (OSError, ValueError, ImportError):
            return {}

    def toggle_battle_template_capture(self, corner):
        if self.battle_template_capture_corner == corner:
            self.cancel_battle_template_capture()
            self.battle_template_status.set("Zaznaczanie wzorca anulowane.")
            return
        if self.battle_template_capture_after_id is not None:
            self.battle_template_capture_corner = None
            if self.battle_template_capture_after_id is not None:
                self.root.after_cancel(self.battle_template_capture_after_id)
                self.battle_template_capture_after_id = None
        if any(item["after_id"] is not None for item in self.battle_monitors.values()):
            self.battle_template_status.set("Zatrzymaj monitor Battle przed zaznaczeniem wzorca.")
            return
        if self.battle_capture_corner is not None:
            self.battle_template_status.set("Najpierw zakończ kalibrację obszaru Battle.")
            return
        name = " ".join(self.battle_template_name_var.get().split())
        if not name:
            self.battle_template_status.set("Najpierw wpisz nazwę potwora dla wzorca.")
            return
        if not self.ensure_battle_process():
            return
        self.battle_template_capture_corner = corner
        self.battle_template_left_was_down = left_button_down()
        label = "lewy górny" if corner == "top_left" else "prawy dolny"
        self.battle_template_status.set(f"Wróć do gry i kliknij {label} róg nazwy „{name}”.")
        self.poll_battle_template_capture()

    def cancel_battle_template_capture(self):
        if self.battle_template_capture_after_id is not None:
            self.root.after_cancel(self.battle_template_capture_after_id)
            self.battle_template_capture_after_id = None
        self.battle_template_capture_corner = None

    def poll_battle_template_capture(self):
        self.battle_template_capture_after_id = None
        if self.battle_template_capture_corner is None or self.battle_pid is None:
            return
        exit_code = wt.DWORD()
        if not GetExitCodeProcess(self.battle_handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            self.cancel_battle_template_capture()
            self.close_battle_handle()
            self.battle_template_status.set("Klient został zamknięty; zaznaczanie anulowano.")
            return
        is_down = left_button_down()
        if is_down and not self.battle_template_left_was_down:
            position = foreground_client_position(self.battle_pid)
            if position is not None:
                corner = self.battle_template_capture_corner
                self.battle_template_points[corner] = position
                self.battle_template_capture_corner = None
                if corner == "top_left":
                    self.battle_template_status.set(
                        f"Lewy górny róg zapisany dla „{self.battle_template_name_var.get().strip()}”. Ustaw prawy dolny róg."
                    )
                else:
                    self.save_battle_template()
                return
        self.battle_template_left_was_down = is_down
        self.battle_template_capture_after_id = self.root.after(
            15, self.poll_battle_template_capture
        )

    def save_battle_template(self):
        name = " ".join(self.battle_template_name_var.get().split())
        top_left = self.battle_template_points["top_left"]
        bottom_right = self.battle_template_points["bottom_right"]
        self.battle_template_points = {"top_left": None, "bottom_right": None}
        if not name or top_left is None or bottom_right is None:
            self.battle_template_status.set("Zaznacz oba rogi nazwy, aby zapisać wzorzec.")
            return
        left, top = top_left
        right, bottom = bottom_right
        if right <= left or bottom <= top:
            self.battle_template_status.set("Rogi są w złej kolejności; zaznacz wzorzec ponownie.")
            return
        try:
            import cv2

            pixels = capture_region(
                self.battle_pid, (left, top, right, bottom), grayscale=False
            )
            if pixels is None:
                self.battle_template_status.set("Wróć do aktywnego okna gry i zaznacz wzorzec ponownie.")
                return
            template = cv2.cvtColor(pixels, cv2.COLOR_BGRA2GRAY)
            if template.shape[0] < 6 or template.shape[1] < 8:
                self.battle_template_status.set("Zaznacz większy fragment nazwy (co najmniej 8 × 6 px).")
                return
            self.store_battle_template(name, template)
            self.battle_template_status.set(
                f"Wzorzec „{name}” zapisany. Zapisane wzorce: {len(self.battle_templates)}."
            )
        except Exception as exc:
            self.battle_template_status.set(f"Nie udało się zapisać wzorca: {exc}")

    def store_battle_template(self, name, template):
        """Save a grayscale name crop as the template of a monster and add it to the list."""
        import cv2

        self.battle_template_dir.mkdir(parents=True, exist_ok=True)
        key = name.casefold()
        filename = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20] + ".png"
        destination = self.battle_template_dir / filename
        if not cv2.imwrite(str(destination), template):
            raise RuntimeError("Nie udało się zapisać obrazu wzorca.")
        metadata = {}
        if self.battle_template_manifest.exists():
            try:
                metadata = json.loads(
                    self.battle_template_manifest.read_text(encoding="utf-8")
                )
            except ValueError:
                metadata = {}
        metadata[name] = filename
        self.battle_template_manifest.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.battle_templates[key] = template
        allowed_names = [part.strip() for part in self.battle_monsters_var.get().split(",") if part.strip()]
        if name.casefold() not in {part.casefold() for part in allowed_names}:
            allowed_names.append(name)
            self.battle_monsters_var.set(", ".join(allowed_names))
        self.refresh_target_list()
        if self.battle_attack_enabled:
            # Nowy wzorzec działa od razu, bez ponownego włączania ataku.
            self.battle_active_templates[key] = template
            self.battle_ocr_fallback_names.discard(key)

    def ensure_battle_process(self):
        if self.battle_handle is not None:
            exit_code = wt.DWORD()
            if GetExitCodeProcess(self.battle_handle, ctypes.byref(exit_code)) and exit_code.value == 259:
                return True
            self.close_battle_handle()
        try:
            pid, handle, _base, _path = find_process(STATUS_PROCESS_ACCESS)
        except Exception as exc:
            messagebox.showerror("Błąd klienta", str(exc), parent=self.root)
            return False
        if not handle:
            messagebox.showerror(
                "Nie znaleziono klienta", "Uruchom klienta RetronicDX.", parent=self.root
            )
            return False
        self.battle_pid = pid
        self.battle_handle = handle
        return True

    def close_battle_handle(self):
        if self.battle_handle is not None:
            CloseHandle(self.battle_handle)
            self.battle_handle = None
        self.battle_pid = None

    def toggle_battle_capture(self, corner, profile):
        if self.battle_template_capture_corner is not None:
            self.battle_profile_status[profile].set(
                "Najpierw zakończ zaznaczanie wzorca potwora."
            )
            return
        if any(item["after_id"] is not None for item in self.battle_monitors.values()):
            messagebox.showinfo(
                "Zatrzymaj wykrywanie",
                "Zatrzymaj wykrywanie Battle przed zmianą obszaru.",
                parent=self.root,
            )
            return
        if self.battle_capture_corner == corner and self.battle_capture_profile == profile:
            self.cancel_battle_capture()
            self.battle_profile_status[profile].set("Ustawianie obszaru anulowane.")
            return
        if self.battle_capture_corner is not None:
            self.cancel_battle_capture()
        if not self.ensure_battle_process():
            return

        self.battle_capture_corner = corner
        self.battle_capture_profile = profile
        self.battle_left_was_down = left_button_down()
        button = self.battle_capture_buttons[profile][corner]
        if corner == "top_left":
            button.configure(text="Kliknij lewy górny róg — anuluj")
            prompt = "Wróć do gry i kliknij lewy górny róg wierszy Battle dla tego profilu."
        else:
            button.configure(text="Kliknij prawy dolny róg — anuluj")
            prompt = "Wróć do gry i kliknij prawy dolny róg wierszy Battle dla tego profilu."
        self.battle_profile_status[profile].set(prompt)
        self.poll_battle_capture()

    def cancel_battle_capture(self):
        if self.battle_capture_after_id is not None:
            self.root.after_cancel(self.battle_capture_after_id)
            self.battle_capture_after_id = None
        profile = self.battle_capture_profile
        if profile is not None and self.battle_capture_corner is not None:
            label = "Ustaw lewy górny róg" if self.battle_capture_corner == "top_left" else "Ustaw prawy dolny róg"
            self.battle_capture_buttons[profile][self.battle_capture_corner].configure(text=label)
        self.battle_capture_corner = None
        self.battle_capture_profile = None

    def poll_battle_capture(self):
        self.battle_capture_after_id = None
        if self.battle_capture_corner is None or self.battle_pid is None:
            return
        exit_code = wt.DWORD()
        if not GetExitCodeProcess(self.battle_handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            profile_key = self.battle_capture_profile
            self.cancel_battle_capture()
            self.close_battle_handle()
            self.battle_profile_status[profile_key].set(
                "Klient został zamknięty; ustaw obszar ponownie."
            )
            return

        is_down = left_button_down()
        if is_down and not self.battle_left_was_down:
            position = foreground_client_position(self.battle_pid)
            if position is not None:
                profile = self.battle_profiles[self.battle_capture_profile]
                profile[self.battle_capture_corner] = position
                profile_key = self.battle_capture_profile
                self.cancel_battle_capture()
                self.update_battle_region(profile_key)
                return
        self.battle_left_was_down = is_down
        self.battle_capture_after_id = self.root.after(15, self.poll_battle_capture)

    def update_battle_region(self, profile_key):
        profile = self.battle_profiles[profile_key]
        status = self.battle_profile_status[profile_key]
        top_left = profile["top_left"]
        bottom_right = profile["bottom_right"]
        if top_left is None or bottom_right is None:
            points = []
            if top_left:
                points.append(f"lewy górny: {top_left}")
            if bottom_right:
                points.append(f"prawy dolny: {bottom_right}")
            status.set("; ".join(points) or "Obszar Battle nieustawiony")
            return

        left, top = top_left
        right, bottom = bottom_right
        if right <= left or bottom <= top:
            profile["region"] = None
            status.set(
                "Punkty są w złej kolejności. Ustaw lewy górny i prawy dolny róg ponownie."
            )
            return
        profile["region"] = (left, top, right, bottom)
        status.set(
            f"Battle: X={left}–{right}, Y={top}–{bottom} względem okna gry."
        )

    def toggle_battle_monitor(self, profile_key):
        monitor = self.battle_monitors[profile_key]
        if monitor["after_id"] is not None:
            self.stop_battle_monitor(profile_key, resume_automations=True)
            return
        if any(key != profile_key and item["after_id"] is not None
               for key, item in self.battle_monitors.items()):
            messagebox.showinfo(
                "Inny monitor jest aktywny",
                "Zatrzymaj wykrywanie Battle w drugiej zakładce przed uruchomieniem tego profilu.",
                parent=self.root,
            )
            return
        if self.battle_capture_corner is not None:
            messagebox.showerror(
                "Ustawianie obszaru",
                "Zakończ ustawianie rogów przed rozpoczęciem wykrywania.",
                parent=self.root,
            )
            return
        if self.battle_template_capture_corner is not None:
            messagebox.showerror(
                "Zaznaczanie wzorca",
                "Zakończ zaznaczanie wzorca potwora przed rozpoczęciem wykrywania.",
                parent=self.root,
            )
            return
        profile_region = self.battle_profiles[profile_key]["region"]
        if profile_region is None:
            messagebox.showerror(
                "Brak obszaru",
                f"Najpierw skalibruj obszar Battle dla profilu: {'Expienie' if profile_key == 'exp' else 'Robienie run'}.",
                parent=self.root,
            )
            return
        if not self.ensure_battle_process():
            return

        monitor.update(baseline=None, candidate=None, candidate_count=0)
        monitor["region"] = profile_region
        monitor["button"].set_on(True)
        monitor["status"].set("Wróć do gry z pustą listą Battle; zapamiętam ją jako wzorzec.")
        self.log_battle_attack(
            f"Start monitora profilu={profile_key}; obszar={profile_region}", repeat=True
        )
        self.schedule_battle_poll(profile_key, 200)

    def toggle_battle_attack(self):
        if not self.battle_attack_enabled:
            exp_region = self.battle_profiles["exp"]["region"]
            if exp_region is None:
                self.detect_battle_window(
                    callback=lambda: self.battle_profiles["exp"]["region"] is not None
                    and not self.battle_attack_enabled and self.toggle_battle_attack()
                )
                return
            names = self.allowed_battle_monsters()
            if not names:
                messagebox.showerror(
                    "Brak nazw potworów",
                    "Wpisz co najmniej jedną dokładną nazwę potwora, którego bot może atakować.",
                    parent=self.root,
                )
                return
            templates = {
                name: template
                for name, template in self.battle_templates.items()
                if name in names
            }
            ocr_fallback_names = names - set(templates)
            try:
                row_height = int(self.battle_row_height_var.get())
            except ValueError:
                messagebox.showerror("Nieprawidłowy wiersz", "Wysokość wiersza musi być liczbą.", parent=self.root)
                return
            if not 8 <= row_height <= min(80, exp_region[3] - exp_region[1]):
                messagebox.showerror("Nieprawidłowy wiersz", "Wysokość wiersza musi mieścić się w obszarze Battle i wynosić 8–80 px.", parent=self.root)
                return
            if ocr_fallback_names:
                try:
                    find_tesseract()
                except Exception as exc:
                    messagebox.showerror(
                        "Brak wzorca lub OCR",
                        "Zapisz obraz wzorcowy dla każdego dozwolonego potwora albo zainstaluj Tesseract OCR.\n\n"
                        + str(exc),
                        parent=self.root,
                    )
                    return
            self.battle_attack_enabled = True
            self.battle_active_templates = templates
            self.battle_ocr_fallback_names = ocr_fallback_names
            self.reset_targeting_state()
            self.battle_target_lock = None
            self.battle_target_lock_count = 0
            self.battle_target_absence_count = 0
            self.battle_target_count_candidate = None
            self.battle_target_count_candidate_hits = 0
            self.battle_attack_button.set_on(True)
            method = "wzorce obrazu" if not ocr_fallback_names else "wzorce i OCR"
            message = f"Atak włączony ({method})."
            self.add_event(f"Targeting włączony ({method}).")
            self.combat_detect_retry_at = 0.0
            self.detect_combat_buttons()
            self.battle_monitors["exp"]["status"].set(message)
            self.ensure_exp_battle_monitor()
            self.log_battle_attack(
                f"Atak włączony; cele={sorted(names)}; wzorce={sorted(templates)}; "
                f"OCR={sorted(ocr_fallback_names)}",
                repeat=True,
            )
        else:
            self.battle_attack_enabled = False
            self.battle_active_templates = {}
            self.battle_ocr_fallback_names = set()
            self.battle_target_lock = None
            self.battle_target_lock_count = 0
            self.battle_target_absence_count = 0
            self.battle_target_count_candidate = None
            self.battle_target_count_candidate_hits = 0
            self.battle_attack_button.set_on(False)
            self.reset_targeting_state()
            self.battle_monitors["exp"]["status"].set("Automatyczny atak potworów wyłączony.")
            self.add_event("Targeting wyłączony.")
            self.release_exp_battle_monitor()
            self.log_battle_attack("Atak wyłączony", repeat=True)

    def allowed_battle_monsters(self):
        ignored = set(self.cavebot_profile.get("ignored", []))
        return {
            " ".join(name.split()).casefold()
            for name in self.battle_monsters_var.get().split(",")
            if name.strip() and " ".join(name.split()).casefold() not in ignored
        }

    def log_battle_attack(self, message, *, repeat=False):
        """Persist attack diagnostics so they remain available while the game is focused."""
        if not repeat and message == self._last_battle_attack_log_message:
            return
        self._last_battle_attack_log_message = message
        try:
            # Keep at most two files of ~1 MB: the current log and battle_attack.log.1.
            if self.battle_attack_log.exists() and self.battle_attack_log.stat().st_size > 1_000_000:
                self.battle_attack_log.replace(self.battle_attack_log.with_suffix(".log.1"))
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with self.battle_attack_log.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{timestamp} | {message}\n")
        except OSError:
            # Diagnostics must never interrupt Battle monitoring.
            pass
        if not message.startswith(("Rozpoznano", "W Battle nie ma", "Po kliknięciu nie widać",
                                   "Atak włączony;", "Atak wyłączony", "Start monitora", "Loot:")):
            if message.startswith("Cel='"):
                name = message.split("'")[1]
                message = f"Klikam cel: {name}"
            self.add_event(message)

    def reset_targeting_state(self):
        """Forget the current target and the game-view cache (start/stop of targeting)."""
        self.battle_target_lock = None
        self.battle_pending_target = None
        self.battle_attacking = False
        self.battle_marker_misses = 0
        self.battle_last_click_at = None
        self.battle_unconfirmed_clicks = 0
        self.battle_target_health = None
        self.battle_current_health = None
        self.target_state = "idle"          # idle → engaging (kliknięto) → locked (ramka celu)
        self.target_engage = None
        self.target_rest_until = 0.0
        self.target_has_work = False
        self.target_scan_at = 0.0
        self.target_unreachable_since = None
        self.target_unreachable_until = {}
        self.target_screen = None
        self.target_corpse_offset = None
        self.target_corpse_world = None
        # Ciała zabitych celów czekające na otwarcie po walce.
        self.corpse_queue = CorpseQueue()
        self.target_listed_count = 0
        if getattr(self, "target_watch_id", None) is not None:
            self.root.after_cancel(self.target_watch_id)
        self.target_watch_id = None
        self.target_watch_misses = 0
        self.screen_view = None
        self.screen_view_checked_at = -100.0
        self.screen_misses = 0
        self.screen_click_failures = 0

    def targeting_busy(self):
        """True while the cavebot should stand still for a fight."""
        if self.loot_inspection_running:
            return True
        if not self.battle_attack_enabled:
            return False
        if self.battle_attacking:
            return True
        now = time.monotonic()
        if (self.cavebot_inspect_corpses_var.get()
                and self.corpse_queue.pending(self.minimap_position, now)):
            # Cavebot czeka, aż bot otworzy ciała zabitych potworów.
            return True
        if now < self.target_rest_until:
            return False
        if self.target_state == "engaging":
            return True
        return self.target_has_work and now - self.target_scan_at < 3.0

    def scan_game_view(self, now):
        """Creatures on the game map with tile offsets and steps to reach them, or None.

        Mapę gry bot znajduje raz (ramka 15 × 11 pól) i potem przechwytuje
        tylko ją. Drogę do potwora liczy po mapie .otmm z pozycji z minimapy,
        traktując pola innych stworów jako zajęte.
        """
        pid = self.battle_pid
        bounds = foreground_client_bounds(pid)
        if bounds is None:
            return None
        if self.screen_view is None:
            if now - self.screen_view_checked_at < 5.0:
                return None
            self.screen_view_checked_at = now
            _x, _y, width, height = bounds
            image = capture_region(pid, (0, 0, width, height), grayscale=False, label="okna gry")
            if image is None:
                return None
            self.screen_view = find_game_view(image)
            if self.screen_view is None:
                self.log_battle_attack("Nie widzę mapy gry; cel wybieram z samej listy Battle.")
                return None
            self.log_battle_attack(
                f"Mapa gry: {self.screen_view}, pole {tile_size(self.screen_view):.0f} px.", repeat=True
            )
        view = self.screen_view
        image = capture_region(pid, view, grayscale=False, label="mapy gry")
        if image is None:
            return None
        local = (0, 0, view[2] - view[0], view[3] - view[1])
        creatures, player_found = locate_creatures(image, local)
        if not player_found:
            # Bez własnego paska pozycje są niepewne; po kilku razach szukamy mapy od nowa.
            self.screen_misses += 1
            if self.screen_misses >= 3:
                self.screen_view = None
                self.screen_misses = 0
            return None
        self.screen_misses = 0
        square = attack_square(image, local)
        position = self.minimap_position
        reach_known = (
            self.minimap_map is not None and position is not None and self.minimap_enabled_var.get()
        )
        for creature in creatures:
            creature["x"] += view[0]
            creature["y"] += view[1]
            if reach_known:
                px_, py_, z = position
                blocked = {(px_ + other["dx"], py_ + other["dy"]) for other in creatures if other is not creature}
                creature["steps"] = reach_steps(
                    self.minimap_map, position, (px_ + creature["dx"], py_ + creature["dy"]), blocked
                )
            else:
                creature["steps"] = max(0, max(abs(creature["dx"]), abs(creature["dy"])) - 1)
        return {
            "view": view,
            "tile": tile_size(view),
            "creatures": creatures,
            "square": square_offset(square, local) if square else None,
            "reach_known": reach_known,
        }

    def target_candidates(self, rows, screen, attacked_row=None, attacked_offset=None):
        """Return (allowed targets best first, number skipped as unreachable); see targeting.rank_candidates."""
        now = time.monotonic()
        self.target_unreachable_until = {
            key: until for key, until in self.target_unreachable_until.items() if until > now
        }
        return targeting.rank_candidates(
            rows,
            screen["creatures"] if screen else None,
            bool(screen and screen["reach_known"]),
            self.monster_priority,
            suppressed=self.target_unreachable_until,
            allow_screen=self.screen_click_failures < 2,
            attacked_row=attacked_row,
            attacked_offset=attacked_offset,
        )

    def attack_allowed_battle_monster(self, recognized):
        """One targeting step after a Battle scan.

        Stany: brak celu → kliknięto (czekamy na czerwoną ramkę, ponawiamy
        z rosnącą przerwą) → cel potwierdzony. Bot nigdy nie klika ponownie
        atakowanego celu, bo to wyłączyłoby atak.
        """
        if not self.battle_attack_enabled or recognized is None:
            return False
        if self.loot_inspection_running:
            return False
        region = self.battle_profiles["exp"]["region"]
        frame = capture_region(self.battle_pid, region, grayscale=False)
        if frame is None:
            return False
        now = time.monotonic()
        self.target_scan_at = now
        status = self.battle_monitors["exp"]["status"]
        allowed = self.allowed_battle_monsters()
        rows = assign_row_names(parse_battle_rows(frame), recognized)
        if not rows:
            # Pasków życia nie widać (inny wygląd klienta): wiersze z samych nazw, jak dawniej.
            rows = [{"y": text_y + px(10), "top": text_y - px(10), "hp": 100, "attacked": False,
                     "name": name, "text_x": text_x, "text_y": text_y}
                    for _row_index, name, text_x, text_y in recognized]
        for row in rows:
            row["key"] = targeting.normalize_name(row["name"])
            row["allowed"] = row["key"] in allowed
        try:
            screen = self.scan_game_view(now)
        except Exception as exc:
            # Błąd odczytu mapy gry nie zatrzymuje ataku z samej listy Battle.
            screen = None
            self.screen_view = None
            self.log_battle_attack(f"Odczyt mapy gry nieudany: {exc}")
        self.target_screen = screen

        attacked = next((row for row in rows if row["attacked"]), None)
        if (attacked is None and self.battle_target_lock is not None
                and self.target_unreachable_until.get(self.battle_target_lock, 0.0) <= now
                and attack_marker_pixels(frame) >= px(6)):
            attacked = {"y": -1, "hp": None, "key": self.battle_target_lock, "name": None,
                        "allowed": self.battle_target_lock in allowed}
        if (attacked is not None
                and self.target_unreachable_until.get(attacked.get("key"), 0.0) > now):
            # Marker nadal może wisieć na potworze, ale po potwierdzonej blokadzie
            # nie traktuj go ponownie jako aktywnego celu przez czas cooldownu.
            attacked = None
            self.battle_attacking = False
            self.target_state = "idle"
            self.target_engage = None
            self.battle_target_lock = None
            self.target_has_work = False
        if attacked is not None:
            if self.target_state != "locked":
                self.battle_target_health = None
                self.target_unreachable_since = None
                label = attacked["name"] or (self.battle_target_lock or "cel").title()
                self.log_battle_attack(
                    f"Atak potwierdzony: {label} (HP {attacked['hp']}%).", repeat=True
                )
            self.target_state = "locked"
            self.start_target_watch()
            self.target_engage = None
            self.battle_attacking = True
            self.battle_marker_misses = 0
            self.battle_unconfirmed_clicks = 0
            self.target_has_work = True
            if attacked["key"]:
                self.battle_target_lock = attacked["key"]
            # Ile potworów o tej nazwie jest w Battle: gdy po zniknięciu ramki
            # jest ich mniej, cel zginął (sama nazwa nie odróżnia dwóch larw).
            self.target_listed_count = sum(row.get("key") == self.battle_target_lock for row in rows)
            self.battle_current_health = attacked["hp"]
            self.remember_target_corpse_position(screen, attacked)
            if self.battle_target_lock and now - self.combat_checked_at > 2.0:
                self.combat_checked_at = now
                self.ensure_combat_mode(self.battle_target_lock)
            return self.maybe_retarget(rows, attacked, screen, now)

        if self.target_state == "locked":
            # Jedna klatka bez ramki (np. przerysowanie listy) to jeszcze nie
            # koniec ataku; kliknięcie w tej chwili wyłączyłoby trwający atak.
            self.battle_marker_misses += 1
            if self.battle_marker_misses < 2:
                return True
            listed = sum(row.get("key") == self.battle_target_lock for row in rows)
            self.end_target_lock(targeting.target_died(
                self.battle_current_health,
                listed > 0 and listed >= self.target_listed_count,
                self.target_still_on_tile(screen),
            ), now)
            if self.loot_inspection_running:
                return False
        self.battle_attacking = False
        self.battle_current_health = None

        candidates, skipped = self.target_candidates(rows, screen)
        self.target_has_work = bool(candidates)
        if not candidates:
            if skipped:
                message = f"Potwory z listy są nieosiągalne ({skipped}); cavebot idzie dalej."
            elif any(row["allowed"] for row in rows):
                message = "Potwór z listy jest w Battle, ale nie da się go teraz zaatakować."
            else:
                names = ", ".join(row["name"] for row in rows if row["name"]) or "brak rozpoznanych nazw"
                message = f"W Battle nie ma potwora z listy ({names})."
            self.target_state = "idle"
            self.target_engage = None
            status.set(message)
            self.log_battle_attack(message)
            # Walka skończona (nie ma kogo atakować): czas na ciała z kolejki.
            self.open_next_corpse(now)
            return False
        if now < self.target_rest_until:
            status.set("Cel nie reaguje na kliknięcia; krótka przerwa.")
            return False

        engage = self.target_engage
        if self.target_state == "engaging" and engage is not None:
            # Ramka pojawia się z opóźnieniem serwera; drugie kliknięcie za
            # wcześnie wyłączyłoby atak. Przerwa rośnie: 2 s, 3 s, 4,5 s…
            if now - engage["at"] < targeting.engage_wait(engage["attempt"]):
                status.set(f"Kliknięto „{engage['name']}”; czekam na potwierdzenie celu.")
                return False
            if engage["attempt"] >= targeting.MAX_ENGAGE_ATTEMPTS:
                if engage["via"] == "screen":
                    self.screen_click_failures += 1
                    if self.screen_click_failures >= 2:
                        self.log_battle_attack(
                            "Prawy klik na mapie nie zaczyna ataku (sterowanie klasyczne wyłączone?); "
                            "dalej klikam w Battle.", repeat=True,
                        )
                self.log_battle_attack(
                    f"„{engage['name']}” nie został celem po {engage['attempt']} kliknięciach; "
                    f"przerwa {targeting.ENGAGE_REST:.0f} s.",
                    repeat=True,
                )
                self.target_state = "idle"
                self.target_engage = None
                self.target_rest_until = now + targeting.ENGAGE_REST
                status.set("Cel nie reaguje na kliknięcia; krótka przerwa.")
                return False
        best = candidates[0]
        self.ensure_combat_mode(best["key"])
        return self.click_target(best, len(candidates), now)

    def end_target_lock(self, died, now):
        """The attack marker is gone: open the corpse of a killed target and stop attacking."""
        self.log_battle_attack("Cel nie jest już atakowany; szukam następnego.", repeat=True)
        if died:
            self.queue_target_corpse(now)
        self.target_state = "idle"
        self.battle_attacking = False
        self.battle_current_health = None

    def start_target_watch(self):
        """Start the fast check of the attacked creature (only when corpses are opened at once)."""
        if (self.target_watch_id is None and self.cavebot_inspect_corpses_var.get()
                and self.cavebot_loot_now_var.get()):
            self.target_watch_misses = 0
            self.target_watch_id = self.root.after(TARGET_WATCH_MS, self.watch_target)

    def watch_target(self):
        """Fast check of the attacked creature between Battle scans.

        Odczyt Battle (OCR) trwa ok. 1 s, a zabicie poznawaliśmy dopiero po
        dwóch takich odczytach — w tym czasie postać zdążyła ruszyć do
        następnego waypointu albo potwora, a zapamiętane pole celu było sprzed
        1–2 s. Tu co TARGET_WATCH_MS sprawdzamy sam czerwony kwadrat na mapie
        gry: pamiętamy jego świeże pole, a gdy kwadrat i ramka w Battle znikną,
        a na polu celu nie stoi już stwór, od razu otwieramy ciało.
        """
        self.target_watch_id = None
        if (self.target_state != "locked" or self.loot_inspection_running or not self.battle_attack_enabled
                or self.battle_pid is None or self.screen_view is None):
            return
        try:
            done = self.check_target_square()
        except Exception as exc:
            # Szybki odczyt jest tylko dodatkiem; zabicie i tak wykryje odczyt Battle.
            self.log_battle_attack(f"Szybki odczyt celu nieudany: {exc}")
            return
        if not done:
            self.target_watch_id = self.root.after(TARGET_WATCH_MS, self.watch_target)

    def check_target_square(self):
        """One fast check; return True when watching should stop (target killed or unclear)."""
        view = self.screen_view
        image = capture_region(self.battle_pid, view, grayscale=False, label="mapy gry")
        if image is None:
            return False
        local = (0, 0, view[2] - view[0], view[3] - view[1])
        square = attack_square(image, local)
        if square is not None:
            self.target_watch_misses = 0
            offset = square_offset(square, local)
            self.target_corpse_offset = offset
            player = self.minimap_position
            if player is not None:
                self.target_corpse_world = (player[0] + offset[0], player[1] + offset[1], player[2])
            return False
        # Jedna klatka bez kwadratu (efekt czaru, przerysowanie) to jeszcze nie koniec.
        self.target_watch_misses += 1
        if self.target_watch_misses < 2:
            return False
        frame = capture_region(self.battle_pid, self.battle_profiles["exp"]["region"], grayscale=False)
        if frame is None or attack_marker_pixels(frame) >= px(6):
            return False
        creatures, _player_found = locate_creatures(image, local)
        still_on_tile = self.target_still_on_tile({"creatures": creatures})
        if not targeting.target_died(self.battle_current_health, True, still_on_tile):
            # Na polu celu nadal stoi stwór: rozstrzygnie odczyt Battle (liczba potworów).
            return True
        self.end_target_lock(True, time.monotonic())
        return True

    def remember_target_corpse_position(self, screen, attacked):
        """Remember the target tile in world coordinates while the attack marker is visible."""
        offset = targeting.corpse_offset_from_screen(screen, attacked.get("hp"))
        if offset is None:
            return
        self.target_corpse_offset = offset
        player = self.minimap_position
        if player is not None:
            self.target_corpse_world = (player[0] + offset[0], player[1] + offset[1], player[2])

    def target_still_on_tile(self, screen):
        """Whether a creature stands on the last tile of the target (None when unknown)."""
        world, player = self.target_corpse_world, self.minimap_position
        tiles = set()
        if world is not None and player is not None and world[2] == player[2]:
            tiles.add((world[0] - player[0], world[1] - player[1]))
        if self.target_corpse_offset is not None:
            tiles.add(tuple(self.target_corpse_offset))
        if not screen or not tiles:
            return None
        # Minimapa spóźnia się za ruchem postaci, więc sprawdzamy też pole z mapy
        # gry; wystarczy, że jedno z nich jest puste (stwór na sąsiednim polu to nie cel).
        occupied = {(creature["dx"], creature["dy"]) for creature in screen["creatures"]}
        return tiles <= occupied

    def queue_target_corpse(self, now):
        """Open the killed target's corpse now, or queue it for after the fight."""
        if not self.cavebot_inspect_corpses_var.get():
            return
        name = (self.battle_target_lock or "cel").title()
        if self.cavebot_loot_now_var.get() and (
                self.target_corpse_world is not None or self.target_corpse_offset is not None):
            # Od razu, zanim targeting kliknie następny cel: attack_allowed_battle_monster
            # nie atakuje, dopóki trwa oglądanie ciała.
            self.log_battle_attack(f"Zabity: {name}; otwieram ciało od razu.", repeat=True)
            self.begin_corpse_inspection(self.target_corpse_world, self.target_corpse_offset or (0, 0),
                                         name=name, killed_at=now, screen_first=True)
            return
        if self.target_corpse_world is not None:
            if self.corpse_queue.add(self.target_corpse_world, now, name):
                self.loot_status.set(f"Zabity: {name}. Ciał w kolejce: {len(self.corpse_queue)}; "
                                     "otworzę je po walce.")
                self.log_battle_attack(f"Zabity: {name}; ciało w kolejce ({len(self.corpse_queue)}).",
                                       repeat=True)
        elif self.target_corpse_offset is not None:
            # Bez pozycji z minimapy znamy tylko przesunięcie względem postaci,
            # więc ciało trzeba otworzyć od razu, zanim postać się ruszy.
            self.begin_corpse_inspection(None, self.target_corpse_offset, name=name, killed_at=now)
        else:
            self.log_battle_attack(
                f"Zabity: {name}, ale nie znam pola ciała (brak czerwonego kwadratu celu na mapie).",
                repeat=True,
            )

    def open_next_corpse(self, now):
        """Open the nearest queued corpse once nothing is left to attack."""
        if self.loot_inspection_running or not self.cavebot_inspect_corpses_var.get():
            return
        entry = self.corpse_queue.pop_nearest(self.minimap_position, now)
        if entry is not None:
            self.begin_corpse_inspection(entry["world"], None, name=entry["name"],
                                         killed_at=entry["at"], tries=entry.get("tries", 0))

    def begin_corpse_inspection(self, corpse_world, fallback_offset, name=None, killed_at=None, tries=0,
                                screen_first=False):
        """Open the corpse at the world tile (or the offset from the player) in a worker thread.

        tries > 0 to ponowna próba po walce. Gdy wyliczone pole nie odpowiada,
        bot klika też pola wokół postaci (zwykła podłoga z mapy .otmm).
        screen_first — pole z mapy gry jest świeże (zabicie właśnie wykryte),
        więc klikamy je przed polem liczonym z (spóźnionej) minimapy.
        """
        if (not self.cavebot_inspect_corpses_var.get() or self.loot_inspection_running
                or not self.battle_attack_enabled or self.battle_pid is None):
            return
        self.loot_inspection_running = True
        self.loot_current = {"world": corpse_world, "name": name, "tries": tries,
                             "at": killed_at if killed_at is not None else time.monotonic()}
        otmm_map = self.minimap_map
        # Migawka stanu z wątku GUI; wątek roboczy nie czyta już pól okna.
        self.loot_cancel.clear()
        loot_slot = self.cavebot_profile.get("loot_slot")
        options = dict(
            pid=self.battle_pid,
            corpse_world=corpse_world,
            fallback_offset=fallback_offset,
            player_position=self.minimap_position,
            cached_view=self.target_screen["view"] if self.target_screen else None,
            learn=bool(self.cavebot_learn_loot_var.get()),
            use_meat=bool(self.cavebot_use_meat_var.get()),
            loot=bool(self.cavebot_loot_var.get()),
            loot_slot=tuple(loot_slot) if loot_slot else None,
            should_stop=self.loot_cancel.is_set,
            # Pozycja z minimapy (odświeżana w wątku GUI): czy postać jeszcze idzie do ciała.
            player_now=lambda: self.minimap_position,
            open_tile=lambda world: open_ground(otmm_map, world),
            screen_first=screen_first,
        )
        self.cavebot_status.set("Walka zakończona; otwieram ciało i sprawdzam zapisane wzorce…")
        self.loot_status.set(f"Otwieram ciało… (w kolejce jeszcze {len(self.corpse_queue)})")

        def work():
            self.finish_corpse_inspection(inspect_corpse(**options))

        threading.Thread(target=work, daemon=True).start()

    def finish_corpse_inspection(self, result):
        def update():
            self.loot_inspection_running = False
            self.battle_attacking = False
            self.target_state = "idle"
            self.battle_target_lock = None
            self.target_has_work = False
            message = result["message"]
            current, self.loot_current = self.loot_current, None
            if (result.get("retry") and current is not None and current["world"] is not None
                    and current["tries"] + 1 < CORPSE_TRIES
                    and self.corpse_queue.add(current["world"], current["at"], current["name"],
                                              tries=current["tries"] + 1)):
                # Ciało nie znika: cavebot czeka, a po walce bot szuka go też na polach obok.
                message += " Spróbuję jeszcze raz po walce."
            self.cavebot_status.set(message)
            self.add_event(f"Loot: {message}")
            # Do pliku z czasami etapów: tam szukamy przyczyn opóźnień i braku lootu.
            timing = f" [{result['timing']}]" if result.get("timing") else ""
            self.log_battle_attack(f"Loot: {message}{timing}", repeat=True)
            self.record_loot_result(result)
            if result.get("new_patterns"):
                self.refresh_loot_patterns()
                new_name = result["new_patterns"][-1]
                for index, pattern_id in enumerate(self.loot_pattern_ids):
                    if self.loot_patterns[pattern_id]["name"] == new_name:
                        self.loot_pattern_listbox.selection_clear(0, tk.END)
                        self.loot_pattern_listbox.selection_set(index)
                        self.loot_pattern_listbox.see(index)
                        self.select_loot_pattern()
                        break
                self.loot_pattern_status.set(
                    f"Automatycznie zapisano {len(result['new_patterns'])} nowych wzorców. Nadaj im nazwy."
                )
        self.root.after(0, update)

    def maybe_retarget(self, rows, attacked, screen, now):
        """Keep attacking the selected monster; retarget only after a sustained failure."""
        status = self.battle_monitors["exp"]["status"]
        name = attacked["name"] or (self.battle_target_lock or "cel").title()
        hp = attacked["hp"]
        record, stalled = targeting.track_health(self.battle_target_health, attacked["y"], hp, now, px(12))
        if record is not self.battle_target_health:
            # Nowy cel albo cel traci HP: liczymy od nowa.
            self.battle_target_health = record
            self.battle_pending_target = None

        offset = screen["square"] if screen else None
        self.target_unreachable_since = targeting.unreachable_since(
            screen, offset, self.target_unreachable_since, now
        )
        reason = targeting.retarget_reason(self.target_unreachable_since, stalled, now)
        blocked = reason is not None and "nieosiągalny" in reason
        candidates, _skipped = self.target_candidates(rows, screen, attacked_row=attacked, attacked_offset=offset)
        if blocked:
            candidates = [item for item in candidates
                          if item["key"] != attacked["key"] or item["steps"] is not None]
        if reason is None:
            status.set(targeting.attack_status(name, hp, stalled) + ".")
            return True
        if not candidates:
            if blocked:
                blocked_key = attacked.get("key") or self.battle_target_lock
                if blocked_key:
                    self.target_unreachable_until[blocked_key] = now + targeting.UNREACHABLE_SKIP_FOR
                self.battle_attacking = False
                self.battle_current_health = None
                self.battle_target_health = None
                self.battle_target_lock = None
                self.battle_marker_misses = 0
                self.target_state = "idle"
                self.target_engage = None
                self.target_has_work = False
                self.target_corpse_offset = None
                self.target_corpse_world = None
                status.set(f"Cel „{name}” jest zablokowany; pomijam go na 20 s i wracam do trasy.")
                self.log_battle_attack(
                    f"Cel „{name}” nieosiągalny; pomijam ten typ na 20 s i wracam do trasy.",
                    repeat=True,
                )
                return False
            status.set(targeting.attack_status(name, hp, stalled) + " (brak innego celu).")
            return True
        if (self.battle_last_click_at is not None
                and now - self.battle_last_click_at < targeting.RETARGET_MIN_INTERVAL):
            return True
        best = candidates[0]
        self.log_battle_attack(f"Zmiana celu: „{name}” {reason}; biorę „{best['name']}”.", repeat=True)
        self.ensure_combat_mode(best["key"])
        if self.click_target(best, len(candidates), now, retarget=True):
            self.battle_target_health = None
            self.target_unreachable_since = None
        return True

    def click_target(self, candidate, target_count, now, retarget=False):
        """Click a Battle row (left) or a creature on the map (right click = attack)."""
        name, key, via = candidate["name"], candidate["key"], candidate["via"]
        self.target_corpse_offset = None
        self.target_corpse_world = None
        if via == "screen":
            screen = self.target_screen
            view, tile, creature = screen["view"], screen["tile"], candidate["creature"]
            # Pasek wisi nad stworem; środek stwora jest ok. pół pola niżej.
            target_x = creature["x"]
            target_y = creature["y"] + tile * 0.5
            spread = int(tile * 0.15)
            bounds = (view[0] + 1, view[1] + 1, view[2] - 1, view[3] - 1)
            where = f"mapa ({creature['dx']:+d}, {creature['dy']:+d})"
        else:
            row = candidate["row"]
            left, top, right, bottom = self.battle_profiles["exp"]["region"]
            target_x = left + row["text_x"]
            target_y = top + row["text_y"]
            spread = px(8)
            bounds = (left, top, right - 1, bottom - 1)
            where = f"Battle (HP {row['hp']}%)"
        if human.enabled():
            signature = (key, via)
            pending = self.battle_pending_target
            if pending is None or pending[0] != signature:
                kind = "retarget" if retarget or self.battle_target_lock is not None else "attack"
                due = now + human.reaction(kind)
                self.battle_pending_target = (signature, due)
                self.battle_next_target_scan_at = due
                self.battle_monitors["exp"]["status"].set(f"Widzę „{name}”; reaguję jak człowiek…")
                return False
            if now < pending[1]:
                return False
            self.battle_pending_target = None
            target_x = human.jitter(target_x, spread)
            target_y = human.jitter(target_y, max(1, spread // 4) if via == "battle" else spread)
        target_x = int(min(bounds[2], max(bounds[0], target_x)))
        target_y = int(min(bounds[3], max(bounds[1], target_y)))
        send = send_right_click if via == "screen" else send_left_click
        clicked = send(self.battle_pid, target_x, target_y)
        if clicked and human.enabled() and via == "battle":
            # Odsuwamy mysz z listy Battle, jak człowiek po kliknięciu; kursor
            # nad wierszem zasłania czerwoną ramkę celu podświetleniem.
            left = self.battle_profiles["exp"]["region"][0]
            drift_cursor(
                self.battle_pid,
                left - random.randint(px(60), px(260)),
                target_y + random.randint(-px(80), px(120)),
            )
        self.log_battle_attack(
            f"Cel={name!r}; {where}; klik=({target_x},{target_y}); kandydatów={target_count}; "
            f"wynik={'wysłano' if clicked else 'odrzucono'}",
            repeat=True,
        )
        if not clicked:
            self.battle_monitors["exp"]["status"].set("Okno gry nie jest aktywne; atak pominięty.")
            return False
        self.battle_last_click_at = time.monotonic()
        self.battle_target_lock = key
        if not retarget:
            engage = self.target_engage
            attempt = engage["attempt"] + 1 if self.target_state == "engaging" and engage else 1
            self.target_engage = {"at": self.battle_last_click_at, "attempt": attempt, "via": via, "name": name}
            self.target_state = "engaging"
            self.battle_unconfirmed_clicks = attempt
        self.battle_monitors["exp"]["status"].set(f"Kliknięto „{name}” ({where}); czekam na czerwoną ramkę celu.")
        return True

    def schedule_battle_poll(self, profile_key, delay=250):
        self.battle_monitors[profile_key]["after_id"] = self.root.after(
            delay, lambda key=profile_key: self.poll_battle_list(key)
        )

    def poll_battle_list(self, profile_key):
        monitor = self.battle_monitors[profile_key]
        monitor["after_id"] = None
        region = monitor.get("region")
        if self.battle_handle is None or region is None:
            return
        exit_code = wt.DWORD()
        if not GetExitCodeProcess(self.battle_handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            self.stop_battle_monitor(profile_key, resume_automations=True)
            monitor["status"].set("Wykrywanie Battle: klient został zamknięty")
            return

        try:
            frame = capture_region(self.battle_pid, region)
            if frame is None:
                monitor["status"].set("Oczekuję na aktywne okno gry.")
                self.schedule_battle_poll(profile_key, 500)
                return
            if monitor["baseline"] is None:
                monitor["baseline"] = frame.copy()
                monitor["status"].set(
                    "Wzorzec zapisany. Oczekuję na nowy wpis w Battle."
                )
                self.schedule_battle_poll(profile_key)
                return

            present = differs_from_empty(frame, monitor["baseline"])
            recognized = None
            allowed_target_visible = False
            ocr_scan_failed = False
            if (
                profile_key == "exp"
                and self.battle_attack_enabled
                and time.monotonic() >= self.battle_next_target_scan_at
            ):
                self.battle_next_target_scan_at = time.monotonic() + 0.75
                try:
                    row_height = int(self.battle_row_height_var.get())
                    recognized = []
                    if self.battle_active_templates:
                        template_hits = find_battle_templates(
                            self.battle_pid,
                            region,
                            row_height,
                            self.battle_active_templates,
                        )
                        if template_hits is None:
                            recognized = None
                        else:
                            recognized.extend(
                                (row_index, name, text_x, text_y)
                                for row_index, name, text_x, text_y, _score in template_hits
                            )
                    if self.battle_ocr_fallback_names:
                        ocr_hits = read_battle_names(
                            self.battle_pid, region, row_height
                        )
                        if ocr_hits is None:
                            recognized = None
                        elif recognized is not None:
                            recognized.extend(
                                (row_index, name, text_x, text_y)
                                for row_index, name, text_x, text_y in ocr_hits
                                if " ".join(name.split()).casefold()
                                in self.battle_ocr_fallback_names
                            )
                    if not self.battle_active_templates and not self.battle_ocr_fallback_names:
                        recognized = None
                    allowed = self.allowed_battle_monsters()
                    allowed_target_visible = bool(recognized) and any(
                        " ".join(name.split()).casefold() in allowed
                        for _row_index, name, _text_x, _text_y in recognized
                    )
                    # OCR of a recognized row is direct evidence that Battle is
                    # occupied, even if the pixel comparison misses a highlight.
                    present = present or bool(recognized)
                    if allowed_target_visible:
                        present = True
                except Exception as exc:
                    # OCR errors are unknown, not evidence that Battle is empty.
                    ocr_scan_failed = True
                    message = f"Odczyt Battle nieudany; ponowię próbę: {exc}"
                    monitor["status"].set(message)
                    self.log_battle_attack(message)
            if ocr_scan_failed and monitor["present"] and not present:
                present = True
            if present == monitor["candidate"]:
                monitor["candidate_count"] += 1
            else:
                monitor["candidate"] = present
                monitor["candidate_count"] = 1
            if allowed_target_visible and not monitor["present"]:
                # An allowlisted OCR match is enough to attack now.
                monitor["candidate"] = True
                monitor["candidate_count"] = 3
            required_confirmations = (
                8
                if not present
                and profile_key == "exp"
                and self.battle_attack_enabled
                else 3
            )
            if monitor["candidate_count"] >= required_confirmations and present != monitor["present"]:
                self.set_battle_presence(profile_key, present)
            if (
                profile_key == "exp"
                and self.battle_attack_enabled
                and recognized is not None
            ):
                self.log_battle_attack(
                    "Rozpoznano: " + (", ".join(
                        f"{name}@({x},{y})" for _row, name, x, y in recognized
                    ) or "brak dozwolonego wpisu")
                )
                try:
                    self.attack_allowed_battle_monster(recognized)
                except Exception as exc:
                    # An OCR error must not stop Battle monitoring; retry on the next scan.
                    message = f"Odczyt Battle nieudany; ponowię próbę: {exc}"
                    monitor["status"].set(message)
                    self.log_battle_attack(message)
            if (
                not monitor["present"]
                and recognized is None
                and not ocr_scan_failed
                and not (profile_key == "exp" and self.battle_attack_enabled)
            ):
                monitor["status"].set("Monitorowanie aktywne; Battle jest puste.")
        except Exception as exc:
            self.stop_battle_monitor(profile_key, resume_automations=True)
            monitor["status"].set("Wykrywanie Battle: zatrzymane z powodu błędu")
            messagebox.showerror("Błąd wykrywania Battle", str(exc), parent=self.root)
            return
        self.schedule_battle_poll(profile_key)

    def other_bot_functions_paused(self):
        return self.rune_battle_paused and self.rune_battle_options["pause_bot"].get()

    def set_battle_presence(self, profile_key, present):
        monitor = self.battle_monitors[profile_key]
        if present == monitor["present"]:
            return
        monitor["present"] = present
        if present:
            if profile_key == "exp":
                monitor["status"].set(
                    "Wpis Battle wykryty; sprawdzam dozwolone cele."
                )
                self.battle_next_target_scan_at = 0.0
            else:
                options = self.rune_battle_options
                pause_enabled = options["pause_bot"].get()
                monitor["status"].set("Wykryto Battle; uruchamiam skonfigurowaną reakcję.")
                self.rune_battle_paused = pause_enabled
                if self.rune_running:
                    self.rune_status.set(
                        "Pauza Runemakera: wykryto wpis w Battle."
                        if pause_enabled else "Wykryto Battle; Runemaker działa dalej."
                    )
                if options["alarm"].get():
                    self.root.bell()
                if options["move_left"].get():
                    try:
                        steps = max(0, min(100, int(options["left_steps"].get())))
                    except ValueError:
                        steps = 0
                        monitor["status"].set("Nieprawidłowa liczba kratek w lewo.")
                    self.start_rune_battle_step("left", steps)
            return

        monitor["status"].set("Battle puste; przywracam działanie profilu.")
        if profile_key == "runes":
            options = self.rune_battle_options
            try:
                steps = max(0, min(100, int(options["right_steps"].get())))
            except ValueError:
                steps = 0
                monitor["status"].set("Nieprawidłowa liczba kratek w prawo.")
            if options["return_right"].get():
                self.start_rune_battle_step(
                    "right", steps, on_complete=self.finish_rune_battle_clear
                )
            else:
                self.finish_rune_battle_clear()

    def finish_rune_battle_clear(self):
        self.rune_battle_paused = False
        if self.rune_running:
            self.rune_status.set(f"Runemaker wznowiony; zrobiono {self.runes_created} run.")

    def stop_battle_monitor(self, profile_key, update_status=True, resume_automations=True):
        monitor = self.battle_monitors[profile_key]
        if monitor["after_id"] is not None:
            self.root.after_cancel(monitor["after_id"])
            monitor["after_id"] = None
        monitor["button"].set_on(False)
        if profile_key == "runes" and self.rune_battle_move_after_id is not None:
            self.root.after_cancel(self.rune_battle_move_after_id)
            self.rune_battle_move_after_id = None
        if monitor["present"] and resume_automations:
            monitor["present"] = False
            if profile_key == "runes":
                self.rune_battle_paused = False
                if self.rune_running:
                    self.rune_status.set(f"Runemaker wznowiony; zrobiono {self.runes_created} run.")
        if resume_automations or not monitor["present"]:
            monitor["baseline"] = None
        monitor["candidate"] = None
        monitor["candidate_count"] = 0
        monitor.pop("region", None)
        if self.battle_capture_after_id is None and all(
            item["after_id"] is None for item in self.battle_monitors.values()
        ):
            self.close_battle_handle()
        if update_status:
            monitor["status"].set("Wykrywanie Battle: wyłączone")

    def start_rune_battle_step(self, direction, remaining, on_complete=None):
        self.rune_battle_move_after_id = None
        if remaining <= 0:
            if on_complete:
                on_complete()
            return
        if foreground_process_id() != self.battle_pid:
            self.rune_battle_move_after_id = self.root.after(
                200, lambda: self.start_rune_battle_step(direction, remaining, on_complete)
            )
            return
        try:
            tap_arrow(direction, self.battle_pid)
        except Exception as exc:
            self.battle_monitors["runes"]["status"].set(f"Ruch reakcji Battle nie powiódł się: {exc}")
            return
        self.rune_battle_move_after_id = self.root.after(
            180,
            lambda: self.start_rune_battle_step(direction, remaining - 1, on_complete),
        )


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    BotWindow(root)
    root.mainloop()

