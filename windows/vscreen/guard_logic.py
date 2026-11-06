"""Pure decision logic for the window guard (no Win32 here, so it is unit-tested).

Rule, in plain words: a window that appears on the REAL monitor shortly after input happened
on the VIRTUAL monitor is almost certainly something that was launched from there, so it is
moved over. Input on the real monitor cancels that, so ordinary use of the real monitor is
never touched.
"""
from __future__ import annotations

import ntpath
from dataclasses import dataclass, field


@dataclass
class GuardConfig:
    context_s: float = 12.0  # how long "I was just working on the virtual monitor" lasts
    settle_s: float = 0.35  # wait for a new window to finish placing itself
    recheck_s: float = 1.6  # look once more: many apps move themselves after first show
    give_up_s: float = 5.0  # stop watching a window this long after it first showed
    min_width: int = 120
    min_height: int = 80
    ignore_exes: tuple[str, ...] = ()  # base names, case-insensitive, e.g. ("obs64.exe",)
    ignore_title_contains: tuple[str, ...] = ("browsed-local", "가상 화면 제어")


class VirtualContext:
    """Tracks where the user's last input happened."""

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self.until = 0.0

    def note_input(self, now: float, on_virtual: bool) -> None:
        self.until = now + self.window_s if on_virtual else 0.0

    def active(self, now: float) -> bool:
        return now < self.until


def exe_name(path: str) -> str:
    return ntpath.basename(path or "").lower()


@dataclass
class Candidate:
    hwnd: int
    title: str
    exe: str
    on_virtual: bool
    width: int
    height: int
    covers_monitor: bool  # looks like a fullscreen app/game
    minimized: bool = False


def should_move(c: Candidate, ctx_active: bool, cfg: GuardConfig, handled: set[int]) -> tuple[bool, str]:
    """(move?, reason) for one visible, un-owned top-level window."""
    if c.hwnd in handled:
        return False, "already handled"
    if c.on_virtual:
        return False, "already on the virtual monitor"
    if not ctx_active:
        return False, "no recent input on the virtual monitor"
    if c.minimized:
        return False, "minimized"
    if c.covers_monitor:
        return False, "fullscreen"
    if c.width < cfg.min_width or c.height < cfg.min_height:
        return False, "too small to be an app window"
    name = exe_name(c.exe)
    if name and name in {e.lower() for e in cfg.ignore_exes}:
        return False, f"ignored exe {name}"
    low = c.title.lower()
    for frag in cfg.ignore_title_contains:
        if frag.lower() in low:
            return False, f"ignored title '{frag}'"
    return True, "new window after input on the virtual monitor"


@dataclass
class Pending:
    first_seen: float
    checked_settle: bool = False
    checked_recheck: bool = False


@dataclass
class Tracker:
    """Schedules the two looks (settle, recheck) at each new window."""

    cfg: GuardConfig
    pending: dict[int, Pending] = field(default_factory=dict)
    handled: set[int] = field(default_factory=set)

    def saw(self, hwnd: int, now: float) -> None:
        if hwnd not in self.pending and hwnd not in self.handled:
            self.pending[hwnd] = Pending(now)

    def due(self, now: float) -> list[int]:
        """Windows that should be evaluated right now; drops the ones past give_up_s."""
        out: list[int] = []
        for hwnd, p in list(self.pending.items()):
            age = now - p.first_seen
            if age > self.cfg.give_up_s:
                del self.pending[hwnd]
                continue
            if not p.checked_settle and age >= self.cfg.settle_s:
                p.checked_settle = True
                out.append(hwnd)
            elif not p.checked_recheck and age >= self.cfg.recheck_s:
                p.checked_recheck = True
                out.append(hwnd)
        return out

    def mark_handled(self, hwnd: int) -> None:
        self.handled.add(hwnd)
        self.pending.pop(hwnd, None)
        if len(self.handled) > 2000:  # never grow without bound
            self.handled = set(list(self.handled)[-500:])
