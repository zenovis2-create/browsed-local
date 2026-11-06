"""Keeps apps launched from the virtual monitor on the virtual monitor.

Windows opens many new windows on the primary monitor, which is the REAL one you are looking
at. This helper watches for new top-level windows and, if the last input happened on the
virtual monitor, moves the window there. Input on the real monitor cancels the rule, so
nothing you start from the real monitor is touched. It never closes or resizes anything beyond
fitting a moved window into the virtual monitor.

Run:  pythonw window_guard.py [--dry-run] [--ignore-exe obs64.exe]
Log:  windows/logs/window-guard.log (one JSON line per decision that moved a window)
"""
from __future__ import annotations

import argparse
import collections
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_win  # noqa: E402
import guard_logic as gl  # noqa: E402

user32 = bl_win.user32
kernel32 = bl_win.kernel32

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_TIMER = 0x0113
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_UNCLOAKED = 0x8018  # UWP/WinUI windows are created cloaked and uncloaked when ready
# NOT EVENT_SYSTEM_FOREGROUND: that fires for windows that already existed (the browser showing
# the stream!) and must never be moved.
WINEVENT_OUTOFCONTEXT = 0
OBJID_WINDOW = 0
GA_ROOT = 2
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
WM_KEYDOWN, WM_SYSKEYDOWN = 0x100, 0x104
BUTTONS_DOWN = {0x201, 0x204, 0x207, 0x20B, 0x20A, 0x20E}  # L/R/M/X down, wheel, hwheel


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", bl_win._POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.SetWinEventHook.restype = ctypes.c_void_p
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
user32.UnhookWinEvent.argtypes = [ctypes.c_void_p]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


class Guard:
    def __init__(self, virtual: bl_win.MonitorInfo, cfg: gl.GuardConfig, dry_run: bool, log_path: str) -> None:
        self.virtual = virtual
        self.cfg = cfg
        self.dry_run = dry_run
        self.log_path = log_path
        self.ctx = gl.VirtualContext(cfg.context_s)
        self.tracker = gl.Tracker(cfg)
        self.inputs: collections.deque = collections.deque(maxlen=512)
        self.new_windows: collections.deque = collections.deque(maxlen=512)
        self._mouse_proc = HOOKPROC(self._on_mouse)
        self._key_proc = HOOKPROC(self._on_key)
        self._event_proc = WINEVENTPROC(self._on_event)
        self._hooks: list[int] = []
        self._events: list[int] = []
        self.moves = 0

    # ---- hooks: callbacks only append to a deque (Windows drops slow low-level hooks)
    def _on_mouse(self, n_code, w_param, l_param):  # noqa: ANN001
        if n_code >= 0 and w_param in BUTTONS_DOWN:
            s = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            self.inputs.append(("mouse", s.pt.x, s.pt.y, time.monotonic()))
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _on_key(self, n_code, w_param, l_param):  # noqa: ANN001
        if n_code >= 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
            self.inputs.append(("key", 0, 0, time.monotonic()))
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _on_event(self, hook, event, hwnd, id_object, id_child, thread, ms):  # noqa: ANN001
        if id_object == OBJID_WINDOW and id_child == 0 and hwnd:
            self.new_windows.append((int(hwnd), time.monotonic()))

    def install(self) -> None:
        hmod = kernel32.GetModuleHandleW(None)
        self._hooks.append(user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_proc, hmod, 0))
        self._hooks.append(user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._key_proc, hmod, 0))
        # Every top-level window that exists right now is, by definition, not new.
        for h in bl_win.enum_windows():
            self.tracker.handled.add(h)
        for ev in (EVENT_OBJECT_SHOW, EVENT_OBJECT_UNCLOAKED):
            self._events.append(user32.SetWinEventHook(ev, ev, None, self._event_proc, 0, 0, WINEVENT_OUTOFCONTEXT))

    def uninstall(self) -> None:
        for h in self._hooks:
            if h:
                user32.UnhookWindowsHookEx(h)
        for h in self._events:
            if h:
                user32.UnhookWinEvent(h)

    # ---- logic
    def _log(self, record: dict) -> None:
        record["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _fg_on_virtual(self) -> bool:
        fg = bl_win.foreground_window()
        return bool(fg) and bl_win.monitor_of_window(fg).lower() == self.virtual.device.lower()

    def _drain_inputs(self) -> None:
        while self.inputs:
            kind, x, y, t = self.inputs.popleft()
            on_virtual = self.virtual.rect.contains(x, y) if kind == "mouse" else self._fg_on_virtual()
            self.ctx.note_input(t, on_virtual)

    def _candidate(self, hwnd: int, monitors: list[bl_win.MonitorInfo]) -> gl.Candidate | None:
        if not bl_win.user32.IsWindow(hwnd) or not bl_win.is_candidate_app_window(hwnd):
            return None
        info = bl_win.window_info(hwnd)
        mon = next((m for m in monitors if m.device.lower() == info.monitor.lower()), None)
        covers = bool(mon) and info.rect.left <= mon.rect.left and info.rect.top <= mon.rect.top and info.rect.right >= mon.rect.right and info.rect.bottom >= mon.rect.bottom
        return gl.Candidate(hwnd, info.title, info.exe, info.monitor.lower() == self.virtual.device.lower(), info.rect.width, info.rect.height, covers, info.minimized)

    def tick(self) -> None:
        now = time.monotonic()
        self._drain_inputs()
        while self.new_windows:
            hwnd, t = self.new_windows.popleft()
            if user32.GetAncestor(hwnd, GA_ROOT) == hwnd:
                self.tracker.saw(hwnd, t)
        due = self.tracker.due(now)
        if not due:
            return
        monitors = bl_win.list_monitors()
        for hwnd in due:
            c = self._candidate(hwnd, monitors)
            if not c:
                continue
            move, reason = gl.should_move(c, self.ctx.active(now), self.cfg, self.tracker.handled)
            if not move:
                if c.on_virtual:
                    self.tracker.mark_handled(hwnd)  # landed where it should; stop watching
                continue
            if self.dry_run:
                self._log({"action": "would-move", "title": c.title, "exe": c.exe, "reason": reason})
                self.tracker.mark_handled(hwnd)
                continue
            before = bl_win.window_rect(hwnd).as_list()
            after = bl_win.move_window_to_monitor(hwnd, self.virtual, monitors).as_list()
            self.moves += 1
            self.tracker.mark_handled(hwnd)
            self._log({"action": "moved", "title": c.title, "exe": c.exe, "from": before, "to": after, "reason": reason})

    def run(self) -> None:
        self.install()
        user32.SetTimer(None, 1, 100, None)
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_TIMER:
                    try:
                        self.tick()
                    except Exception as e:  # never let one bad window stop the guard
                        self._log({"action": "error", "error": repr(e)})
                else:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self.uninstall()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Move windows launched from the virtual monitor onto it.")
    ap.add_argument("--device", help=r"virtual monitor device, e.g. \\.\DISPLAY5 (default: auto-detect)")
    ap.add_argument("--dry-run", action="store_true", help="only log what would be moved")
    ap.add_argument("--ignore-exe", action="append", default=[], help="exe base name to never move (repeatable)")
    ap.add_argument("--ignore-title", action="append", default=[], help="never move windows whose title contains this (repeatable), e.g. the page title of the stream viewer")
    ap.add_argument("--context-seconds", type=float, default=12.0)
    ap.add_argument("--wait", type=float, default=0.0, help="seconds to wait for the virtual monitor to appear")
    ap.add_argument("--log", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "window-guard.log"))
    args = ap.parse_args(argv)

    bl_win.set_dpi_aware()
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW(None, False, "Local\\browsed-local-window-guard")
    if ctypes.get_last_error() == 183:
        print("window guard already running", file=sys.stderr)
        return 0
    deadline = time.monotonic() + args.wait
    while True:
        mon = bl_win.pick_virtual(bl_win.list_monitors(), device=args.device) if args.device else bl_win.find_virtual_monitor()
        if mon or time.monotonic() >= deadline:
            break
        time.sleep(1.0)
    if not mon:
        print("virtual monitor not found", file=sys.stderr)
        return 2
    base = gl.GuardConfig()
    cfg = gl.GuardConfig(context_s=args.context_seconds, ignore_exes=tuple(args.ignore_exe), ignore_title_contains=base.ignore_title_contains + tuple(args.ignore_title))
    print(f"window guard on {mon.device} {mon.rect.as_list()}{' (dry run)' if args.dry_run else ''}", flush=True)
    Guard(mon, cfg, args.dry_run, args.log).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
