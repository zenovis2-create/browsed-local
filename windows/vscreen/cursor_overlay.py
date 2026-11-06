"""Draws the mouse pointer (plus click ripples and a wheel badge) onto the VIRTUAL monitor.

Why: Windows has a single mouse cursor and the screen stream does not contain it. When the
browser that shows the stream sits on the real monitor, moving the mouse over it warps the
one cursor onto the virtual monitor, where nobody sees it. This helper paints the cursor into
the virtual monitor itself, so it shows up in the stream (for you and for agents that read
screenshots). The overlay windows are click-through and never take focus.

Run:  pythonw cursor_overlay.py            (auto-detects the virtual monitor)
      pythonw cursor_overlay.py --device \\\\.\\DISPLAY5 --scale 1.8
"""
from __future__ import annotations

import argparse
import collections
import ctypes
import math
import os
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_win  # noqa: E402
import sprites  # noqa: E402

user32 = bl_win.user32
kernel32 = bl_win.kernel32
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x4, 0x10, 0x40
ULW_ALPHA = 2
WH_MOUSE_LL = 14
WM_TIMER, WM_QUIT = 0x0113, 0x0012
WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x201, 0x204, 0x207, 0x20A, 0x20E
CURSOR_SHOWING = 1

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", ctypes.c_void_p),
        ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hCursor", ctypes.c_void_p), ("ptScreenPos", bl_win._POINT)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", bl_win._POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


# IDC_* system cursor ids -> sprite names
_IDC = {32512: "arrow", 32513: "ibeam", 32514: "wait", 32515: "cross", 32516: "arrow", 32642: "size_nwse", 32643: "size_nesw",
        32644: "size_we", 32645: "size_ns", 32646: "size_all", 32648: "no", 32649: "hand", 32650: "appstarting", 32651: "arrow"}

user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(bl_win._POINT), ctypes.POINTER(bl_win._POINT),
                                       wintypes.HDC, ctypes.POINTER(bl_win._POINT), wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.LoadCursorW.restype = ctypes.c_void_p
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]


def _wndproc(hwnd, msg, wparam, lparam):  # noqa: ANN001
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_WNDPROC = WNDPROC(_wndproc)  # keep alive
_registered: set[str] = set()


class Surface:
    """A click-through, always-on-top, per-pixel-alpha window of fixed size."""

    def __init__(self, cls_name: str, w: int, h: int) -> None:
        self.w, self.h = w, h
        hinst = kernel32.GetModuleHandleW(None)
        if cls_name not in _registered:
            wc = WNDCLASSW()
            wc.lpfnWndProc = _WNDPROC
            wc.hInstance = hinst
            wc.lpszClassName = cls_name
            if not user32.RegisterClassW(ctypes.byref(wc)):
                raise ctypes.WinError(ctypes.get_last_error())
            _registered.add(cls_name)
        ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self.hwnd = user32.CreateWindowExW(ex, cls_name, "", WS_POPUP, 0, 0, w, h, None, None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(bmi)
        bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = w, -h, 1, 32
        self.bits = ctypes.c_void_p()
        self.dib = gdi32.CreateDIBSection(self.screen_dc, ctypes.byref(bmi), 0, ctypes.byref(self.bits), None, 0)
        gdi32.SelectObject(self.mem_dc, self.dib)
        self.visible = False
        self.pos = (None, None)

    def present(self, data: bytes, x: int, y: int) -> None:
        ctypes.memmove(self.bits, data, len(data))
        dst = bl_win._POINT(x, y)
        size = bl_win._POINT(self.w, self.h)
        src = bl_win._POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, per-pixel alpha
        user32.UpdateLayeredWindow(self.hwnd, self.screen_dc, ctypes.byref(dst), ctypes.byref(size), self.mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
        self.pos = (x, y)
        if not self.visible:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self.visible = True

    def move(self, x: int, y: int) -> None:
        if self.pos != (x, y):
            user32.SetWindowPos(self.hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            self.pos = (x, y)

    def hide(self) -> None:
        if self.visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False

    def raise_topmost(self) -> None:
        # NOMOVE matters: without it this call would drag the window to (0, 0)
        user32.SetWindowPos(self.hwnd, ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)


class Overlay:
    WHEEL_HOLD = 0.30  # seconds the badge stays fully lit after the last wheel event
    WHEEL_FADE = 0.35
    RIPPLE_LEN = 0.45

    def __init__(self, monitor: bl_win.MonitorInfo, scale: float, effects: bool, debug: bool = False) -> None:
        self.debug = debug
        self._last_debug = 0.0
        self.mon = monitor
        self.rect = monitor.rect
        self.scale = scale
        self.effects_on = effects
        self.effects = Surface("BrowsedLocalCursorEffects", sprites.EFFECT_SIZE, sprites.EFFECT_SIZE) if effects else None
        self.pointer = Surface("BrowsedLocalCursorOverlay", sprites.CANVAS, sprites.CANVAS)
        self.canvas = sprites.Canvas(sprites.EFFECT_SIZE, sprites.EFFECT_SIZE)
        self.events: collections.deque = collections.deque(maxlen=256)
        self.shape: str | None = None
        self.anchor: tuple[int, int] | None = None  # where the most recent click/wheel happened
        self.ripples: list[tuple[float, str, int, int]] = []  # (start, button, x, y)
        self.wheel: tuple[str, float, float] | None = None  # (direction, first_event, last_event)
        self.handles = {user32.LoadCursorW(None, ctypes.c_void_p(i)): n for i, n in _IDC.items()}
        self._hook_proc = HOOKPROC(self._on_mouse)
        self._hook = None
        self._last_effect = 0.0
        self._last_raise = 0.0
        self.errors = 0

    # ---- hook (must stay tiny: Windows drops slow low-level hooks)
    def _on_mouse(self, n_code, w_param, l_param):  # noqa: ANN001
        if n_code >= 0 and self.effects_on and w_param in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            try:
                s = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                self.events.append((w_param, s.pt.x, s.pt.y, ctypes.c_short((s.mouseData >> 16) & 0xFFFF).value, time.monotonic()))
            except Exception:
                pass
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def install_hook(self) -> None:
        if self.effects_on:
            self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_proc, kernel32.GetModuleHandleW(None), 0)

    def remove_hook(self) -> None:
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    # ---- per tick
    def classify(self, hcursor) -> str:  # noqa: ANN001
        return self.handles.get(hcursor, "arrow")

    def tick(self) -> None:
        now = time.monotonic()
        x, y = bl_win.cursor_pos()
        ci = CURSORINFO()
        ci.cbSize = ctypes.sizeof(ci)
        shown = bool(user32.GetCursorInfo(ctypes.byref(ci))) and bool(ci.flags & CURSOR_SHOWING)
        if self.debug and now - self._last_debug > 1.0:
            self._last_debug = now
            print(f"tick cursor=({x},{y}) on_virtual={self.rect.contains(x, y)} shown={shown} hcursor={ci.hCursor} shape={self.shape} pointer_visible={self.pointer.visible} pos={self.pointer.pos}", file=sys.stderr, flush=True)
        if self.rect.contains(x, y) and shown:
            shape = self.classify(ci.hCursor)
            sp = sprites.render_shape(shape, self.scale)
            if shape != self.shape or not self.pointer.visible:
                self.shape = shape
                self.pointer.present(sp.data, x - sp.hx, y - sp.hy)
            else:
                self.pointer.move(x - sp.hx, y - sp.hy)
        else:
            self.pointer.hide()
        if self.effects_on:
            self._effects(now, x, y)
        if now - self._last_raise > 2.0:  # other topmost windows may have climbed over us
            self._last_raise = now
            if self.effects:
                self.effects.raise_topmost()
            self.pointer.raise_topmost()

    def _effects(self, now: float, cx: int, cy: int) -> None:
        while self.events:
            msg, ex, ey, delta, t = self.events.popleft()
            if self.debug:
                print(f"event msg={msg:#x} at ({ex},{ey}) delta={delta} on_virtual={self.rect.contains(ex, ey)}", file=sys.stderr, flush=True)
            if not self.rect.contains(ex, ey):
                continue
            if msg == WM_MOUSEWHEEL or msg == WM_MOUSEHWHEEL:
                if delta == 0:
                    continue
                d = ("up" if delta > 0 else "down") if msg == WM_MOUSEWHEEL else ("right" if delta > 0 else "left")
                first = self.wheel[1] if self.wheel and self.wheel[0] == d and t - self.wheel[2] < 0.6 else t
                self.wheel = (d, first, t)
                self.anchor = (ex, ey)
            else:
                btn = "left" if msg == WM_LBUTTONDOWN else "right" if msg == WM_RBUTTONDOWN else "middle"
                self.ripples.append((t, btn, ex, ey))
                self.anchor = (ex, ey)
        self.ripples = [r for r in self.ripples if now - r[0] < self.RIPPLE_LEN]
        if self.wheel and now - self.wheel[2] > self.WHEEL_HOLD + self.WHEEL_FADE:
            self.wheel = None
        if not self.ripples and not self.wheel:
            if self.effects and self.effects.visible:
                self.effects.hide()
            return
        if now - self._last_effect < 0.028:
            return
        self._last_effect = now
        half = sprites.EFFECT_SIZE // 2
        c = self.canvas
        c.clear()
        # Anchor on where the last click/wheel happened, not on the live cursor: an agent may
        # hand the cursor back to the real monitor right after clicking, and the ripple must
        # still show on the virtual one.
        ax, ay = self.anchor if self.anchor else (cx, cy)
        for start, btn, rx, ry in self.ripples:
            sprites.draw_ripple(c, half + (rx - ax), half + (ry - ay), (now - start) / self.RIPPLE_LEN, btn)
        if self.wheel:
            d, first, last = self.wheel
            idle = now - last
            alpha = 1.0 if idle <= self.WHEEL_HOLD else max(0.0, 1.0 - (idle - self.WHEEL_HOLD) / self.WHEEL_FADE)
            sprites.draw_wheel(c, half, half, d, ((now - first) * 2.5) % 1.0, alpha)
        self.effects.present(bytes(c.buf), ax - half, ay - half)  # type: ignore[union-attr]

    def run(self) -> None:
        self.install_hook()
        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod(1)
        user32.SetTimer(None, 1, 8, None)
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_TIMER:
                    try:
                        self.tick()
                    except Exception as e:  # keep running; surface the first few
                        self.errors += 1
                        if self.errors <= 5:
                            print("tick error:", repr(e), file=sys.stderr)
                else:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self.remove_hook()
            winmm.timeEndPeriod(1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paint the mouse pointer onto the virtual monitor so it shows in the stream.")
    ap.add_argument("--device", help=r"virtual monitor device name, e.g. \\.\DISPLAY5 (default: auto-detect)")
    ap.add_argument("--scale", type=float, default=1.8, help="pointer size multiplier (default 1.8)")
    ap.add_argument("--no-effects", action="store_true", help="pointer only: no click ripples or wheel badge")
    ap.add_argument("--wait", type=float, default=0.0, help="seconds to wait for the virtual monitor to appear")
    ap.add_argument("--debug", action="store_true", help="print state once a second to stderr")
    args = ap.parse_args(argv)

    bl_win.set_dpi_aware()
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    mutex = kernel32.CreateMutexW(None, False, "Local\\browsed-local-cursor-overlay")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        print("cursor overlay already running", file=sys.stderr)
        return 0
    deadline = time.monotonic() + args.wait
    mon = None
    while True:
        mon = bl_win.pick_virtual(bl_win.list_monitors(), device=args.device) if args.device else bl_win.find_virtual_monitor()
        if mon or time.monotonic() >= deadline:
            break
        time.sleep(1.0)
    if not mon:
        print("virtual monitor not found; nothing to draw on", file=sys.stderr)
        return 2
    print(f"cursor overlay on {mon.device} {mon.rect.as_list()} ({mon.adapter})", flush=True)
    Overlay(mon, args.scale, not args.no_effects, args.debug).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
