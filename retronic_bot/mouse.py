"""Przechwycenie pozycji i prawy klik w oknie klienta Windows."""

import ctypes
import ctypes.wintypes as wt
import time

from . import human
from .keyboard import (
    INPUT,
    INPUT_KEYBOARD,
    INPUT_MOUSE,
    KEYBDINPUT,
    KEYEVENTF_KEYUP,
    MOUSEINPUT,
    SendInput,
)


MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_RBUTTON = 0x02
VK_LBUTTON = 0x01
VK_CONTROL = 0x11
VK_SHIFT = 0x10


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wt.LONG), ("top", wt.LONG),
        ("right", wt.LONG), ("bottom", wt.LONG),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
GetCursorPos = user32.GetCursorPos
GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
GetCursorPos.restype = wt.BOOL
GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.argtypes = []
GetForegroundWindow.restype = wt.HWND
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
GetWindowThreadProcessId.restype = wt.DWORD
GetClientRect = user32.GetClientRect
GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
GetClientRect.restype = wt.BOOL
ClientToScreen = user32.ClientToScreen
ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(POINT)]
ClientToScreen.restype = wt.BOOL
SetCursorPos = user32.SetCursorPos
SetCursorPos.argtypes = [wt.INT, wt.INT]
SetCursorPos.restype = wt.BOOL
GetAsyncKeyState = user32.GetAsyncKeyState
GetAsyncKeyState.argtypes = [ctypes.c_int]
GetAsyncKeyState.restype = wt.SHORT


def _move_cursor(point):
    """Jump to the point, or glide there like a hand in Human mode."""
    if human.enabled():
        current = POINT()
        if GetCursorPos(ctypes.byref(current)):
            human.glide(SetCursorPos, (current.x, current.y), (point.x, point.y))
            return
    if not SetCursorPos(point.x, point.y):
        raise ctypes.WinError(ctypes.get_last_error())


def _restore_cursor(previous):
    # Człowiek nie odskakuje kursorem z powrotem w tej samej milisekundzie,
    # więc w trybie Human kursor zostaje tam, gdzie kliknął.
    if not human.enabled():
        SetCursorPos(previous.x, previous.y)


def _click(down_flag, up_flag):
    if human.enabled():
        human.hover()
        down = (INPUT * 1)(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, down_flag, 0, 0)))
        up = (INPUT * 1)(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, up_flag, 0, 0)))
        if SendInput(1, down, ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            time.sleep(human.press_time())
        finally:
            if SendInput(1, up, ctypes.sizeof(INPUT)) != 1:
                raise ctypes.WinError(ctypes.get_last_error())
        return
    events = (INPUT * 2)(
        INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, down_flag, 0, 0)),
        INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, up_flag, 0, 0)),
    )
    sent = SendInput(len(events), events, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise ctypes.WinError(ctypes.get_last_error())


def right_button_down():
    return bool(GetAsyncKeyState(VK_RBUTTON) & 0x8000)


def left_button_down():
    return bool(GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def shift_key_down():
    return bool(GetAsyncKeyState(VK_SHIFT) & 0x8000)


def foreground_client_position(target_pid):
    """Return cursor position relative to the active target client's client area."""
    hwnd = GetForegroundWindow()
    pid = wt.DWORD()
    if not hwnd or not GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return None
    if pid.value != target_pid:
        return None

    cursor = POINT()
    origin = POINT(0, 0)
    rect = RECT()
    if not GetCursorPos(ctypes.byref(cursor)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not ClientToScreen(hwnd, ctypes.byref(origin)):
        raise ctypes.WinError(ctypes.get_last_error())

    x, y = cursor.x - origin.x, cursor.y - origin.y
    if x < 0 or y < 0 or x >= rect.right or y >= rect.bottom:
        return None
    return x, y


def foreground_client_bounds(target_pid):
    """Return the screen origin and client size while the target game is active."""
    hwnd = GetForegroundWindow()
    pid = wt.DWORD()
    if not hwnd or not GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return None
    if pid.value != target_pid:
        return None

    rect = RECT()
    origin = POINT(0, 0)
    if not GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not ClientToScreen(hwnd, ctypes.byref(origin)):
        raise ctypes.WinError(ctypes.get_last_error())
    return origin.x, origin.y, rect.right, rect.bottom


def send_right_click(target_pid, client_x, client_y):
    """Right-click client coordinates only while the intended game is foreground."""
    hwnd = GetForegroundWindow()
    pid = wt.DWORD()
    if not hwnd or not GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return False
    if pid.value != target_pid:
        return False

    rect = RECT()
    if not GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    if client_x < 0 or client_y < 0 or client_x >= rect.right or client_y >= rect.bottom:
        raise RuntimeError("Zapamiętana pozycja znajduje się poza obszarem okna gry.")

    point = POINT(client_x, client_y)
    if not ClientToScreen(hwnd, ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    previous = POINT()
    if not GetCursorPos(ctypes.byref(previous)):
        raise ctypes.WinError(ctypes.get_last_error())
    _move_cursor(point)
    # Klient musi zauważyć kursor nad przedmiotem w oknie pojemnika (np. Meat
    # w ciele), zanim dostanie kliknięcie — inaczej klik trafia „w nic”.
    time.sleep(0.05)
    try:
        _click(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
        time.sleep(0.04)
    finally:
        _restore_cursor(previous)
    return True


def send_left_click(target_pid, client_x, client_y):
    """Left-click client coordinates only while the intended game is foreground."""
    hwnd = GetForegroundWindow()
    pid = wt.DWORD()
    if not hwnd or not GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return False
    if pid.value != target_pid:
        return False

    rect = RECT()
    if not GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    if client_x < 0 or client_y < 0 or client_x >= rect.right or client_y >= rect.bottom:
        raise RuntimeError("Pozycja celu znajduje się poza obszarem okna gry.")
    point = POINT(client_x, client_y)
    if not ClientToScreen(hwnd, ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    previous = POINT()
    if not GetCursorPos(ctypes.byref(previous)):
        raise ctypes.WinError(ctypes.get_last_error())
    _move_cursor(point)
    # Give the game a frame to observe the pointer over the row before the
    # button event, and keep it there briefly after release.
    time.sleep(0.04)
    try:
        _click(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
        time.sleep(0.04)
    finally:
        _restore_cursor(previous)
    return True


def drag_item(target_pid, source_x, source_y, target_x, target_y, hold_ctrl=False,
              out_of_window_message="Pozycja blank runy lub slotu ręki jest poza oknem gry."):
    """Drag an item between two client-relative positions in the active game.

    With hold_ctrl the Ctrl key is held only around the release, so the client
    moves a whole stack instead of asking for the amount.
    """
    hwnd = GetForegroundWindow()
    pid = wt.DWORD()
    if not hwnd or not GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return False
    if pid.value != target_pid:
        return False

    rect = RECT()
    if not GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    for x, y in ((source_x, source_y), (target_x, target_y)):
        if x < 0 or y < 0 or x >= rect.right or y >= rect.bottom:
            raise RuntimeError(out_of_window_message)

    source = POINT(source_x, source_y)
    target = POINT(target_x, target_y)
    if not ClientToScreen(hwnd, ctypes.byref(source)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not ClientToScreen(hwnd, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    previous = POINT()
    if not GetCursorPos(ctypes.byref(previous)):
        raise ctypes.WinError(ctypes.get_last_error())

    _move_cursor(source)
    time.sleep(0.05)
    if human.enabled():
        human.hover()
    down = (INPUT * 1)(INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0),
    ))
    up = (INPUT * 1)(INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0),
    ))
    ctrl_down = (INPUT * 1)(INPUT(
        type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_CONTROL, 0, 0, 0, 0)
    ))
    ctrl_up = (INPUT * 1)(INPUT(
        type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, 0)
    ))
    button_is_down = False
    ctrl_is_down = False
    try:
        if SendInput(1, down, ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())
        button_is_down = True
        time.sleep(human.press_time() if human.enabled() else 0.05)
        _move_cursor(target)
        time.sleep(0.10)
        if hold_ctrl:
            if SendInput(1, ctrl_down, ctypes.sizeof(INPUT)) != 1:
                raise ctypes.WinError(ctypes.get_last_error())
            ctrl_is_down = True
            time.sleep(0.03)
        if SendInput(1, up, ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())
        button_is_down = False
        time.sleep(0.05)
    finally:
        # Nie zostaw przycisku myszy ani Ctrl wciśniętego po przerwanym przeciąganiu.
        if button_is_down:
            SendInput(1, up, ctypes.sizeof(INPUT))
        if ctrl_is_down:
            SendInput(1, ctrl_up, ctypes.sizeof(INPUT))
        _restore_cursor(previous)
    return True



def drift_cursor(target_pid, client_x, client_y):
    """Move the cursor (without clicking) to client coordinates of the active game.

    Po kliknięciu w wiersz Battle kursor nad wierszem zasłania czerwoną ramkę
    celu białym podświetleniem, a człowiek i tak odsuwa wtedy mysz.
    """
    hwnd = GetForegroundWindow()
    pid = wt.DWORD()
    if not hwnd or not GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or pid.value != target_pid:
        return False
    rect = RECT()
    if not GetClientRect(hwnd, ctypes.byref(rect)):
        return False
    point = POINT(max(0, min(rect.right - 1, client_x)), max(0, min(rect.bottom - 1, client_y)))
    if not ClientToScreen(hwnd, ctypes.byref(point)):
        return False
    _move_cursor(point)
    return True
