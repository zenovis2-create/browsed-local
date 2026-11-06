"""Shared Win32 helpers for the browsed-local helpers (ctypes only, no pip packages).

Everything that needs to know "which monitor is the virtual one" goes through here, so the
pointer overlay, the window guard and the agent CLI always agree.
"""
from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

# --------------------------------------------------------------------------- geometry


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def as_list(self) -> list[int]:
        return [self.left, self.top, self.width, self.height]


@dataclass(frozen=True)
class MonitorInfo:
    device: str  # e.g. \\.\DISPLAY5
    rect: Rect
    work: Rect
    primary: bool
    adapter: str  # e.g. "Virtual Display Driver"


# ------------------------------------------------------------- virtual monitor choice
# The driver that browsed-local documents (VirtualDrivers/Virtual-Display-Driver) reports
# its adapter as "Virtual Display Driver"; other indirect-display drivers use similar names.
_VIRTUAL_ADAPTER = re.compile(r"virtual display|mttvdd|indirect display|iddsample", re.I)


def pick_virtual(
    monitors: Iterable[MonitorInfo],
    device: Optional[str] = None,
    rect: Optional[tuple[int, int, int, int]] = None,
) -> Optional[MonitorInfo]:
    """Pure selection logic (unit-tested): explicit device, explicit rect, adapter name, then
    "the only non-primary monitor"."""
    mons = list(monitors)
    if device:
        for m in mons:
            if m.device.lower() == device.lower():
                return m
        return None
    if rect:
        for m in mons:
            if m.rect.as_list() == list(rect):
                return m
        return None
    named = [m for m in mons if not m.primary and _VIRTUAL_ADAPTER.search(m.adapter or "")]
    if len(named) == 1:
        return named[0]
    others = [m for m in mons if not m.primary]
    if len(others) == 1:
        return others[0]
    return None


# --------------------------------------------------------------------------- DPI / structs


def set_dpi_aware() -> None:
    """Per-monitor v2: every coordinate below is a real pixel on whichever monitor it is on.
    (The primary monitor is scaled 200% while the virtual one is 100%.)"""
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


def _rect(r: _RECT) -> Rect:
    return Rect(r.left, r.top, r.right, r.bottom)


def _adapter_names() -> dict[str, str]:
    out: dict[str, str] = {}
    user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_DISPLAY_DEVICEW), wintypes.DWORD]
    i = 0
    while True:
        dd = _DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        out[dd.DeviceName.lower()] = dd.DeviceString
        i += 1
    return out


def list_monitors() -> list[MonitorInfo]:
    adapters = _adapter_names()
    result: list[MonitorInfo] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RECT), wintypes.LPARAM)

    def cb(hmon, hdc, lprc, lparam):  # noqa: ANN001
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFOEXW)]
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            dev = info.szDevice
            result.append(
                MonitorInfo(dev, _rect(info.rcMonitor), _rect(info.rcWork), bool(info.dwFlags & 1), adapters.get(dev.lower(), ""))
            )
        return True

    user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT), proc, wintypes.LPARAM]
    user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    return result


def find_virtual_monitor() -> Optional[MonitorInfo]:
    """Honours BROWSED_VIRTUAL_DEVICE (e.g. \\\\.\\DISPLAY5) as an override."""
    return pick_virtual(list_monitors(), device=os.environ.get("BROWSED_VIRTUAL_DEVICE") or None)


# --------------------------------------------------------------------------- cursor


def cursor_pos() -> tuple[int, int]:
    p = _POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def set_cursor_pos(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))


# --------------------------------------------------------------------------- windows

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
GW_OWNER = 4
SW_RESTORE = 9
SW_MAXIMIZE = 3
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
MONITOR_DEFAULTTONEAREST = 2
DWMWA_CLOAKED = 14


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    cls: str
    pid: int
    exe: str
    rect: Rect
    maximized: bool
    minimized: bool
    monitor: str  # device name of the monitor holding most of the window


def _get_long_ptr(hwnd: int, index: int) -> int:
    fn = user32.GetWindowLongPtrW
    fn.argtypes = [wintypes.HWND, ctypes.c_int]
    fn.restype = ctypes.c_ssize_t
    return fn(hwnd, index)


def window_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def process_exe(pid: int) -> str:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32.OpenProcess.restype = ctypes.c_void_p
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(h))


def window_rect(hwnd: int) -> Rect:
    r = _RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return _rect(r)


def is_cloaked(hwnd: int) -> bool:
    v = wintypes.DWORD(0)
    try:
        dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        return False
    return v.value != 0


def monitor_of_window(hwnd: int, monitors: Optional[list[MonitorInfo]] = None) -> str:
    """Device name of the monitor the window mostly sits on."""
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(info)
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFOEXW)]
    if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        return info.szDevice
    return ""


def is_candidate_app_window(hwnd: int) -> bool:
    """A normal, visible, un-owned top-level window (not a tool window, tooltip, shell or
    cloaked UWP frame). Used by the guard and by `vscreen list`."""
    if not user32.IsWindowVisible(hwnd):
        return False
    if user32.GetWindow(hwnd, GW_OWNER):
        return False
    style = _get_long_ptr(hwnd, GWL_STYLE)
    ex = _get_long_ptr(hwnd, GWL_EXSTYLE)
    if style & WS_CHILD:
        return False
    if (ex & WS_EX_TOOLWINDOW) and not (ex & WS_EX_APPWINDOW):
        return False
    if ex & WS_EX_NOACTIVATE:
        return False
    if is_cloaked(hwnd):
        return False
    cls = window_class(hwnd)
    if cls in _IGNORED_CLASSES:
        return False
    r = window_rect(hwnd)
    if r.width < 80 or r.height < 50:
        return False
    return True


_IGNORED_CLASSES = {
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "NotifyIconOverflowWindow",
    "TopLevelWindowForOverflowXamlIsland", "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
    "ForegroundStaging", "tooltips_class32", "#32768", "#32769", "ApplicationFrameInputSinkWindow",
    "SysShadow", "MSCTFIME UI", "IME", "TaskListThumbnailWnd", "TaskListOverlayWnd",
    "BrowsedLocalCursorOverlay", "BrowsedLocalCursorEffects",
}


def window_info(hwnd: int) -> WindowInfo:
    pid = window_pid(hwnd)
    return WindowInfo(
        hwnd=hwnd,
        title=window_text(hwnd),
        cls=window_class(hwnd),
        pid=pid,
        exe=process_exe(pid),
        rect=window_rect(hwnd),
        maximized=bool(user32.IsZoomed(hwnd)),
        minimized=bool(user32.IsIconic(hwnd)),
        monitor=monitor_of_window(hwnd),
    )


def enum_windows(filter_fn: Optional[Callable[[int], bool]] = None) -> list[int]:
    out: list[int] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, lparam):  # noqa: ANN001
        if filter_fn is None or filter_fn(hwnd):
            out.append(hwnd)
        return True

    user32.EnumWindows.argtypes = [proc, wintypes.LPARAM]
    user32.EnumWindows(proc(cb), 0)
    return out


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


# --------------------------------------------------------------------------- moving


def target_rect_for(src: Rect, src_area: Rect, dst_area: Rect, margin: int = 24) -> Rect:
    """Where a window of rect `src` (sitting in `src_area`) goes inside `dst_area`: the same
    relative position, shrunk to fit, clamped so the title bar stays reachable (pure)."""
    w = min(src.width, max(200, dst_area.width - 2 * margin))
    h = min(src.height, max(120, dst_area.height - 2 * margin))
    sw = max(1, src_area.width - src.width)
    sh = max(1, src_area.height - src.height)
    fx = min(1.0, max(0.0, (src.left - src_area.left) / sw)) if src_area.width > src.width else 0.5
    fy = min(1.0, max(0.0, (src.top - src_area.top) / sh)) if src_area.height > src.height else 0.5
    x = dst_area.left + int(round(fx * max(0, dst_area.width - w)))
    y = dst_area.top + int(round(fy * max(0, dst_area.height - h)))
    x = max(dst_area.left, min(x, dst_area.right - w))
    y = max(dst_area.top, min(y, dst_area.bottom - 40 if dst_area.height > 80 else dst_area.bottom - h))
    return Rect(x, y, x + w, y + h)


def move_window_to_monitor(hwnd: int, dst: MonitorInfo, monitors: list[MonitorInfo]) -> Rect:
    """Moves a top-level window onto `dst`, keeping maximized windows maximized there."""
    src_dev = monitor_of_window(hwnd)
    src_mon = next((m for m in monitors if m.device.lower() == src_dev.lower()), None)
    src_area = src_mon.work if src_mon else dst.work
    was_max = bool(user32.IsZoomed(hwnd))
    if was_max or user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    new = target_rect_for(window_rect(hwnd), src_area, dst.work)
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos(hwnd, None, new.left, new.top, new.width, new.height, SWP_NOZORDER | SWP_NOACTIVATE)
    # The real monitor is 200% and the virtual one 100%: a per-monitor-DPI app rescales itself
    # while crossing, which shrinks the size we just asked for. Ask again now that it has settled.
    for _ in range(3):
        time.sleep(0.08)
        cur = window_rect(hwnd)
        if abs(cur.width - new.width) <= 8 and abs(cur.height - new.height) <= 8 and abs(cur.left - new.left) <= 8 and abs(cur.top - new.top) <= 8:
            break
        user32.SetWindowPos(hwnd, None, new.left, new.top, new.width, new.height, SWP_NOZORDER | SWP_NOACTIVATE)
    if was_max:
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
    return window_rect(hwnd)
