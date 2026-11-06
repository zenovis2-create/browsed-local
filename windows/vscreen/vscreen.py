"""vscreen: a small CLI so agents (Aside, Codex, Claude, ...) can work on the virtual monitor.

All output is JSON on stdout. Coordinates named `stream` are pixels in the screen stream the
browser shows (the virtual monitor's own 1920x1080), so a click at (x, y) on the streamed page
maps to the same (x, y) here; `screen` coordinates are Windows desktop pixels.

  vscreen.py info                          monitors, which one is virtual, stream geometry
  vscreen.py list [--all] [--json]         windows on the virtual monitor (or all monitors)
  vscreen.py open <exe|file|url> [args]    start an app and put its window on the virtual monitor
  vscreen.py move --title TEXT|--hwnd N --to virtual|real [--maximize]
  vscreen.py focus --title TEXT|--hwnd N
  vscreen.py shot [--out FILE]             PNG of the virtual monitor (Voxl /screenshot, ~20 ms)
  vscreen.py wait [--idle MS] [--timeout MS] [--since SEQ]   block until the screen settles (Voxl /wait)
  vscreen.py click X Y [--button right|middle] [--double]    click at stream pixel (X, Y)
  vscreen.py hover X Y | scroll X Y --dy N [--dx N] | drag X1 Y1 X2 Y2
  vscreen.py type "text" | key ctrl+l

Input commands put your real mouse cursor back afterwards (use --keep-cursor to leave it on the
virtual monitor). The reliable loop for an agent is: act -> `wait` -> `shot`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_win  # noqa: E402

AGENT_DESKTOP = os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "agent-desktop", "bin", "agent-desktop-win32-x64.exe")
STREAM_URL = "http://127.0.0.1:16901"
_HERE = os.path.dirname(os.path.abspath(__file__))


def _out(obj) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return 0


def _fail(msg: str, code: int = 1) -> int:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


def _virtual() -> bl_win.MonitorInfo | None:
    return bl_win.find_virtual_monitor()


def _win_record(w: bl_win.WindowInfo, virtual: bl_win.MonitorInfo | None, focused: int) -> dict:
    r = w.rect
    on_virtual = bool(virtual) and w.monitor.lower() == virtual.device.lower()
    rec = {
        "hwnd": w.hwnd,
        "title": w.title,
        "exe": os.path.basename(w.exe),
        "pid": w.pid,
        "monitor": w.monitor,
        "on_virtual": on_virtual,
        "focused": w.hwnd == focused,
        "maximized": w.maximized,
        "minimized": w.minimized,
        "screen_rect": r.as_list(),
    }
    if on_virtual and virtual and not w.minimized:  # a minimized window's rect is parked off-screen
        rec["stream_rect"] = [r.left - virtual.rect.left, r.top - virtual.rect.top, r.width, r.height]
        rec["stream_center"] = [r.left - virtual.rect.left + r.width // 2, r.top - virtual.rect.top + r.height // 2]
    return rec


def cmd_info(args) -> int:
    mons = bl_win.list_monitors()
    v = bl_win.pick_virtual(mons, device=os.environ.get("BROWSED_VIRTUAL_DEVICE") or None)
    cx, cy = bl_win.cursor_pos()
    return _out({
        "monitors": [
            {"device": m.device, "role": "virtual" if v and m.device == v.device else "real", "primary": m.primary,
             "adapter": m.adapter, "screen_rect": m.rect.as_list(), "work_rect": m.work.as_list()}
            for m in mons
        ],
        "virtual": v.device if v else None,
        "stream": {"url": "http://127.0.0.1:16901/", "size": [v.rect.width, v.rect.height] if v else None,
                   "origin_on_screen": [v.rect.left, v.rect.top] if v else None,
                   "note": "stream (x, y) = screen (origin_x + x, origin_y + y)"},
        "cursor": {"screen": [cx, cy], "on_virtual": bool(v and v.rect.contains(cx, cy))},
    })


def cmd_list(args) -> int:
    v = _virtual()
    fg = bl_win.foreground_window()
    recs = []
    for h in bl_win.enum_windows(bl_win.is_candidate_app_window):
        rec = _win_record(bl_win.window_info(h), v, fg)
        if args.all or rec["on_virtual"]:
            recs.append(rec)
    recs.sort(key=lambda r: (not r["focused"], r["title"].lower()))
    return _out({"virtual": v.device if v else None, "count": len(recs), "windows": recs})


def _find(args) -> int | None:
    if args.hwnd:
        return int(args.hwnd, 0) if isinstance(args.hwnd, str) else int(args.hwnd)
    if args.title:
        needle = args.title.lower()
        for h in bl_win.enum_windows(bl_win.is_candidate_app_window):
            if needle in bl_win.window_text(h).lower():
                return h
    return None


def cmd_move(args) -> int:
    h = _find(args)
    if not h:
        return _fail("window not found (use --title TEXT or --hwnd N)")
    mons = bl_win.list_monitors()
    v = bl_win.pick_virtual(mons)
    if args.to == "virtual":
        dst = v
    else:
        dst = next((m for m in mons if m.primary), None)
    if not dst:
        return _fail("target monitor not found")
    bl_win.move_window_to_monitor(h, dst, mons)
    if args.maximize:
        bl_win.user32.ShowWindow(h, bl_win.SW_MAXIMIZE)
    return _out({"ok": True, "window": _win_record(bl_win.window_info(h), v, bl_win.foreground_window())})


def cmd_focus(args) -> int:
    h = _find(args)
    if not h:
        return _fail("window not found")
    bl_win.user32.keybd_event(0x12, 0, 0, 0)  # a bare Alt tap lets a background process take the foreground
    bl_win.user32.keybd_event(0x12, 0, 2, 0)
    bl_win.user32.ShowWindow(h, bl_win.SW_RESTORE if bl_win.user32.IsIconic(h) else 5)
    ok = bool(bl_win.user32.SetForegroundWindow(h))
    return _out({"ok": ok, "foreground": bl_win.foreground_window() == h})


def cmd_open(args) -> int:
    mons = bl_win.list_monitors()
    v = bl_win.pick_virtual(mons)
    if not v:
        return _fail("virtual monitor not found")
    before = set(bl_win.enum_windows(bl_win.is_candidate_app_window))
    target = args.target
    started_pid = None
    if os.path.exists(target) and not target.lower().endswith((".exe", ".bat", ".cmd", ".com")) or "://" in target:
        os.startfile(target)  # documents and URLs: let Windows pick the app
    else:
        exe = shutil.which(target) or target
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: outlive this CLI
        p = subprocess.Popen([exe, *args.args], creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started_pid = p.pid
    needle = (args.title_contains or "").lower()
    exe_filter = (args.exe or "").lower()
    deadline = time.monotonic() + args.wait
    moved: list[dict] = []
    seen: set[int] = set()
    while time.monotonic() < deadline:
        for h in bl_win.enum_windows(bl_win.is_candidate_app_window):
            if h in before or h in seen:
                continue
            info = bl_win.window_info(h)
            if needle and needle not in info.title.lower():
                continue
            if exe_filter and exe_filter not in os.path.basename(info.exe).lower():
                continue
            if not needle and not exe_filter and started_pid and info.pid != started_pid and args.strict_pid:
                continue
            seen.add(h)
            bl_win.move_window_to_monitor(h, v, mons)
            if args.maximize:
                bl_win.user32.ShowWindow(h, bl_win.SW_MAXIMIZE)
            moved.append(_win_record(bl_win.window_info(h), v, bl_win.foreground_window()))
        if moved and time.monotonic() - deadline > -args.settle:
            break
        time.sleep(0.25)
    return _out({"ok": bool(moved), "started_pid": started_pid, "windows": moved,
                 "hint": None if moved else "no new window appeared in time; use --wait, --title-contains or `vscreen list --all`"})


def _credentials(path: str | None) -> tuple[str, str] | None:
    """(user, password) from credentials.json: --credentials, $BROWSED_CREDENTIALS, or the
    windows/ folder next to this one. The password is never printed or logged."""
    for cand in (path, os.environ.get("BROWSED_CREDENTIALS"), os.path.join(os.path.dirname(_HERE), "credentials.json")):
        if cand and os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8-sig") as f:
                    d = json.load(f)
                return str(d.get("username") or ""), str(d["password"])
            except (OSError, ValueError, KeyError):
                continue
    return None


def _voxl_get(path_and_query: str, creds: tuple[str, str], timeout: float):
    import base64
    import urllib.request
    req = urllib.request.Request(STREAM_URL + path_and_query)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode())
    # Loopback only: skip the system proxy lookup, which alone costs hundreds of ms on Windows.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def cmd_wait(args) -> int:
    creds = _credentials(args.credentials)
    if not creds:
        return _fail("credentials.json not found (use --credentials PATH or set BROWSED_CREDENTIALS)")
    q = f"/wait?idle={int(args.idle)}&timeout={int(args.timeout)}"
    if args.since is not None:
        q += f"&since={int(args.since)}"
    if args.change:
        q += "&change"
    if args.region:
        q += "&region=" + args.region
    try:
        with _voxl_get(q, creds, args.timeout / 1000.0 + 5) as r:
            return _out(json.loads(r.read().decode("utf-8")))
    except OSError as e:
        return _fail(f"stream not reachable: {e}")


def cmd_shot(args) -> int:
    v = _virtual()
    if not v:
        return _fail("virtual monitor not found")
    creds = _credentials(args.credentials)
    if creds and not args.no_voxl:
        out = os.path.abspath(args.out or os.path.join(os.environ.get("TEMP", "."), f"vscreen-{int(time.time())}.png"))
        try:
            t0 = time.monotonic()
            with _voxl_get("/screenshot", creds, 15) as r:
                data = r.read()
                seq = r.headers.get("X-Voxl-Seq")
            with open(out, "wb") as f:
                f.write(data)
            return _out({"ok": True, "path": out, "size": [v.rect.width, v.rect.height], "bytes": len(data), "seq": int(seq) if seq else None,
                         "source": "voxl", "ms": int((time.monotonic() - t0) * 1000)})
        except OSError:
            pass  # stream is off: fall back to a direct capture below
    if not os.path.exists(AGENT_DESKTOP):
        return _fail("agent-desktop not installed (npm i -g agent-desktop); it provides the virtual-monitor capture")
    shown = subprocess.run([AGENT_DESKTOP, "list-displays"], capture_output=True, text=True)
    index = None
    try:
        data = json.loads(shown.stdout)["data"]
        for i, d in enumerate(data):
            b = d["bounds"]
            if [int(b["x"]), int(b["y"]), int(b["width"]), int(b["height"])] == v.rect.as_list():
                index = i
    except (ValueError, KeyError):
        pass
    if index is None:
        return _fail("could not match the virtual monitor to an agent-desktop display index")
    out = os.path.abspath(args.out or os.path.join(os.environ.get("TEMP", "."), f"vscreen-{int(time.time())}.png"))
    r = subprocess.run([AGENT_DESKTOP, "screenshot", "--screen", str(index), out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        return _fail("capture failed: " + (r.stdout or r.stderr)[:300])
    return _out({"ok": True, "path": out, "size": [v.rect.width, v.rect.height]})


def _input_action(args, fn) -> int:
    import bl_input
    v = _virtual()
    if not v:
        return _fail("virtual monitor not found")
    with bl_input.Restore(v, enabled=not getattr(args, "keep_cursor", False)):
        try:
            pos = fn(bl_input, v)
        except OSError as e:
            return _fail(str(e))
    return _out({"ok": True, "stream": [args.x, args.y] if hasattr(args, "x") else None, "screen": list(pos) if pos else None})


def cmd_click(args) -> int:
    return _input_action(args, lambda i, v: i.click(v, args.x, args.y, args.button, 2 if args.double else 1))


def cmd_move_mouse(args) -> int:
    return _input_action(args, lambda i, v: i.move_to(v, args.x, args.y))


def cmd_scroll(args) -> int:
    def run(i, v):
        i.scroll(v, args.x, args.y, dy=args.dy, dx=args.dx)
        return i.to_screen(v, args.x, args.y)
    return _input_action(args, run)


def cmd_drag(args) -> int:
    def run(i, v):
        i.drag(v, args.x1, args.y1, args.x2, args.y2, args.button)
        return i.to_screen(v, args.x2, args.y2)
    return _input_action(args, run)


def cmd_type(args) -> int:
    import bl_input
    try:
        n = bl_input.type_text(args.text, args.delay_ms)
    except OSError as e:
        return _fail(str(e))
    return _out({"ok": True, "typed": n})


def cmd_key(args) -> int:
    import bl_input
    try:
        bl_input.press(args.combo)
    except (ValueError, OSError) as e:
        return _fail(str(e))
    return _out({"ok": True, "key": args.combo})


def main(argv: list[str] | None = None) -> int:
    bl_win.set_dpi_aware()
    # Window titles hold characters the console code page (cp949 here) cannot encode.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="vscreen", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="monitors and stream geometry").set_defaults(fn=cmd_info)
    p = sub.add_parser("list", help="windows on the virtual monitor")
    p.add_argument("--all", action="store_true", help="include windows on every monitor")
    p.add_argument("--json", action="store_true", help="(default; accepted for symmetry)")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("open", help="start an app on the virtual monitor")
    p.add_argument("target", help="exe name/path, file, or URL")
    p.add_argument("args", nargs="*", help="arguments for the exe")
    p.add_argument("--wait", type=float, default=15.0, help="seconds to wait for the window (default 15)")
    p.add_argument("--settle", type=float, default=0.8, help="seconds to keep looking after the first window")
    p.add_argument("--title-contains", help="only move a window whose title contains this")
    p.add_argument("--exe", help="only move a window of this exe (substring)")
    p.add_argument("--strict-pid", action="store_true", help="only windows of the process we started")
    p.add_argument("--maximize", action="store_true")
    p.set_defaults(fn=cmd_open)
    for name, fn, h in (("move", cmd_move, "move a window to the virtual or real monitor"), ("focus", cmd_focus, "bring a window to the foreground")):
        p = sub.add_parser(name, help=h)
        p.add_argument("--title", help="substring of the window title")
        p.add_argument("--hwnd", help="window handle (from `list`)")
        if name == "move":
            p.add_argument("--to", choices=["virtual", "real"], required=True)
            p.add_argument("--maximize", action="store_true")
        p.set_defaults(fn=fn)
    p = sub.add_parser("shot", help="PNG of the virtual monitor")
    p.add_argument("--out", help="output PNG path (default: %TEMP%)")
    p.add_argument("--credentials", help="path to credentials.json (default: ../credentials.json or $BROWSED_CREDENTIALS)")
    p.add_argument("--no-voxl", action="store_true", help="skip the Voxl /screenshot and capture directly")
    p.set_defaults(fn=cmd_shot)
    p = sub.add_parser("wait", help="block until the screen settles (Voxl /wait)")
    p.add_argument("--idle", type=int, default=300, help="ms the screen must stay still (default 300)")
    p.add_argument("--timeout", type=int, default=10000, help="give up after this many ms (default 10000)")
    p.add_argument("--since", type=int, help="seq from an earlier shot/wait: return at once if anything changed after it")
    p.add_argument("--change", action="store_true", help="return at the first change instead of waiting for stillness")
    p.add_argument("--region", help="x,y,w,h: only watch this rectangle")
    p.add_argument("--credentials", help="path to credentials.json")
    p.set_defaults(fn=cmd_wait)
    for name, fn, h in (("click", cmd_click, "click at stream pixel X Y"), ("hover", cmd_move_mouse, "move the pointer to X Y"), ("scroll", cmd_scroll, "scroll at X Y")):
        p = sub.add_parser(name, help=h)
        p.add_argument("x", type=int)
        p.add_argument("y", type=int)
        if name == "click":
            p.add_argument("--button", choices=["left", "right", "middle"], default="left")
            p.add_argument("--double", action="store_true")
        if name == "scroll":
            p.add_argument("--dy", type=float, default=0.0, help="notches; positive scrolls down")
            p.add_argument("--dx", type=float, default=0.0, help="notches; positive scrolls right")
        p.add_argument("--keep-cursor", action="store_true", help="leave the cursor on the virtual monitor afterwards")
        p.set_defaults(fn=fn)
    p = sub.add_parser("drag", help="press at X1 Y1, drag to X2 Y2")
    for a in ("x1", "y1", "x2", "y2"):
        p.add_argument(a, type=int)
    p.add_argument("--button", choices=["left", "right", "middle"], default="left")
    p.add_argument("--keep-cursor", action="store_true")
    p.set_defaults(fn=cmd_drag)
    p = sub.add_parser("type", help="type text into the focused window (Unicode, newline = Enter)")
    p.add_argument("text")
    p.add_argument("--delay-ms", type=float, default=0.0)
    p.set_defaults(fn=cmd_type)
    p = sub.add_parser("key", help="press a key combination, e.g. ctrl+l, enter, alt+f4")
    p.add_argument("combo")
    p.set_defaults(fn=cmd_key)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
