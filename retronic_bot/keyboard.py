"""Wysyłanie tekstu do aktywnego okna klienta gry w Windows."""

import ctypes
import ctypes.wintypes as wt
import time


KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
VK_RETURN = 0x0D
VK_UP = 0x26
VK_LEFT = 0x25
VK_DOWN = 0x28
VK_RIGHT = 0x27

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wt.DWORD), ("union", INPUT_UNION)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.argtypes = []
GetForegroundWindow.restype = wt.HWND
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
GetWindowThreadProcessId.restype = wt.DWORD
SendInput = user32.SendInput
SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
SendInput.restype = wt.UINT


def foreground_process_id():
    hwnd = GetForegroundWindow()
    if not hwnd:
        return None
    pid = wt.DWORD()
    if not GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return None
    return pid.value


def send_spell(spell, target_pid):
    """Wpisz zaklęcie i Enter, wyłącznie gdy aktywny jest klient target_pid."""
    if foreground_process_id() != target_pid:
        return False
    if not spell or any(ord(char) < 32 for char in spell):
        raise ValueError("Zaklęcie nie może być puste ani zawierać znaków sterujących.")
    if any(ord(char) > 0xFFFF for char in spell):
        raise ValueError("Zaklęcie zawiera znak, którego nie obsługuje wejście Unicode Windows.")

    events = []
    for char in spell:
        events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
            0, ord(char), KEYEVENTF_UNICODE, 0, 0
        )))
        events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
            0, ord(char), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0
        )))
    events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
        VK_RETURN, 0, 0, 0, 0
    )))
    events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
        VK_RETURN, 0, KEYEVENTF_KEYUP, 0, 0
    )))

    event_array = (INPUT * len(events))(*events)
    sent = SendInput(len(event_array), event_array, ctypes.sizeof(INPUT))
    if sent != len(event_array):
        raise ctypes.WinError(ctypes.get_last_error())
    return True


def tap_arrow(direction, target_pid, hold_seconds=0.08):
    """Tap the left or right arrow only while the intended game is active."""
    virtual_key = {"left": VK_LEFT, "right": VK_RIGHT}.get(direction)
    if virtual_key is None:
        raise ValueError("Kierunek musi być 'left' albo 'right'.")
    if foreground_process_id() != target_pid:
        return False

    down = (INPUT * 1)(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
        virtual_key, 0, 0, 0, 0
    )))
    up = (INPUT * 1)(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
        virtual_key, 0, KEYEVENTF_KEYUP, 0, 0
    )))
    if SendInput(1, down, ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        time.sleep(hold_seconds)
    finally:
        if SendInput(1, up, ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())
    return True


def tap_movement(direction, target_pid, hold_seconds=0.08):
    """Tap one movement direction only while the intended game is active."""
    virtual_key = {
        "north": VK_UP,
        "west": VK_LEFT,
        "south": VK_DOWN,
        "east": VK_RIGHT,
    }.get(direction)
    if virtual_key is None:
        raise ValueError("Kierunek musi być north, east, south albo west.")
    if foreground_process_id() != target_pid:
        return False

    down = (INPUT * 1)(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
        virtual_key, 0, 0, 0, 0
    )))
    up = (INPUT * 1)(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
        virtual_key, 0, KEYEVENTF_KEYUP, 0, 0
    )))
    if SendInput(1, down, ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        time.sleep(hold_seconds)
    finally:
        if SendInput(1, up, ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())
    return True

