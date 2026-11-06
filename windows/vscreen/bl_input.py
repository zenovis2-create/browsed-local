"""Mouse and keyboard input for the virtual monitor via SendInput (ctypes only).

Coordinates are *stream* pixels: (0, 0) is the virtual monitor's top-left corner, the same
numbers a screenshot of the stream uses. Windows has one mouse cursor, so every action moves
it; callers can hand it back to where it was (see `Restore`).
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional

import bl_win

user32 = bl_win.user32

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0001, 0x0002, 0x0004
WHEEL_DELTA = 120


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def _send(items: list[INPUT]) -> None:
    arr = (INPUT * len(items))(*items)
    sent = user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))
    if sent != len(items):
        raise OSError(f"SendInput delivered {sent}/{len(items)} events (a higher-privilege window may be in the way)")


def _mouse(flags: int, data: int = 0) -> INPUT:
    i = INPUT(type=INPUT_MOUSE)
    i.mi = MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    i = INPUT(type=INPUT_KEYBOARD)
    i.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


# --------------------------------------------------------------------------- coordinates


def to_screen(virtual: bl_win.MonitorInfo, x: int, y: int) -> tuple[int, int]:
    """Stream pixel -> desktop pixel, clamped to the virtual monitor."""
    sx = virtual.rect.left + max(0, min(virtual.rect.width - 1, int(x)))
    sy = virtual.rect.top + max(0, min(virtual.rect.height - 1, int(y)))
    return sx, sy


class Restore:
    """Context manager: afterwards put the cursor back if it started on the REAL monitor
    (so an agent's click does not leave your pointer stranded on the virtual monitor)."""

    def __init__(self, virtual: bl_win.MonitorInfo, enabled: bool = True, settle_s: float = 0.12) -> None:
        self.virtual, self.enabled, self.settle_s = virtual, enabled, settle_s
        self.prev: Optional[tuple[int, int]] = None

    def __enter__(self) -> "Restore":
        self.prev = bl_win.cursor_pos()
        return self

    def __exit__(self, *exc) -> None:
        if self.enabled and self.prev and not self.virtual.rect.contains(*self.prev):
            time.sleep(self.settle_s)  # let the click land and the overlay see it
            bl_win.set_cursor_pos(*self.prev)


# --------------------------------------------------------------------------- mouse

_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def move_to(virtual: bl_win.MonitorInfo, x: int, y: int, hover_s: float = 0.03) -> tuple[int, int]:
    sx, sy = to_screen(virtual, x, y)
    bl_win.set_cursor_pos(sx, sy)
    time.sleep(hover_s)  # apps need a beat to register hover before the click
    return sx, sy


def click(virtual: bl_win.MonitorInfo, x: int, y: int, button: str = "left", count: int = 1) -> tuple[int, int]:
    down, up = _BUTTONS[button]
    pos = move_to(virtual, x, y)
    for n in range(count):
        _send([_mouse(down), _mouse(up)])
        if n + 1 < count:
            time.sleep(0.06)
    return pos


def drag(virtual: bl_win.MonitorInfo, x1: int, y1: int, x2: int, y2: int, button: str = "left", steps: int = 12) -> None:
    down, up = _BUTTONS[button]
    move_to(virtual, x1, y1)
    _send([_mouse(down)])
    for i in range(1, steps + 1):
        bl_win.set_cursor_pos(*to_screen(virtual, x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps))
        time.sleep(0.015)
    time.sleep(0.03)
    _send([_mouse(up)])


def scroll(virtual: bl_win.MonitorInfo, x: int, y: int, dy: float = 0.0, dx: float = 0.0) -> None:
    """dy > 0 scrolls DOWN, dx > 0 scrolls RIGHT (like the stream's own wheel)."""
    move_to(virtual, x, y)
    items = []
    if dy:
        items.append(_mouse(MOUSEEVENTF_WHEEL, int(-dy * WHEEL_DELTA)))
    if dx:
        items.append(_mouse(MOUSEEVENTF_HWHEEL, int(dx * WHEEL_DELTA)))
    if items:
        _send(items)


# --------------------------------------------------------------------------- keyboard

_NAMED = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "meta": 0x5B, "cmd": 0x5B,
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "bksp": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "space": 0x20, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22, "capslock": 0x14,
}
_EXTENDED = {0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x2D, 0x2E, 0x5B}
_MODIFIERS = {0x11, 0x10, 0x12, 0x5B}
for _n in range(1, 13):
    _NAMED[f"f{_n}"] = 0x70 + _n - 1


def parse_combo(combo: str) -> list[int]:
    """'ctrl+shift+t' -> [0x11, 0x10, 0x54]. Pure; raises ValueError on unknown names."""
    vks: list[int] = []
    for part in combo.lower().replace(" ", "").split("+"):
        if not part:
            raise ValueError(f"empty key name in '{combo}'")
        if part in _NAMED:
            vks.append(_NAMED[part])
        elif len(part) == 1 and (part.isalnum()):
            vks.append(ord(part.upper()))
        else:
            raise ValueError(f"unknown key '{part}'")
    return vks


def press(combo: str) -> None:
    vks = parse_combo(combo)
    mods = [v for v in vks[:-1]]
    last = vks[-1]

    def ev(vk: int, up: bool) -> INPUT:
        return _key(vk, 0, (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0) | (KEYEVENTF_KEYUP if up else 0))

    _send([ev(v, False) for v in mods] + [ev(last, False), ev(last, True)] + [ev(v, True) for v in reversed(mods)])


def type_text(text: str, delay_ms: float = 0.0) -> int:
    """Types text as Unicode key packets (Korean, emoji and so on work); '\\n' presses Enter."""
    n = 0
    for ch in text:
        if ch == "\n":
            press("enter")
        elif ch == "\t":
            press("tab")
        else:
            data = ch.encode("utf-16-le")  # characters outside the BMP are two UTF-16 units
            for i in range(0, len(data), 2):
                unit = int.from_bytes(data[i:i + 2], "little")
                _send([_key(0, unit, KEYEVENTF_UNICODE), _key(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)])
        n += 1
        if delay_ms:
            time.sleep(delay_ms / 1000.0)
    return n
