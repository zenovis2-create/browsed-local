"""Native local controller. Closing this window never stops the screen server."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import webbrowser

from control_model import RequestState, SCREEN_URL, SERVER_ROOT, ServerBackend, ServerStatus


def set_dpi_awareness() -> None:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


def primary_work_area() -> tuple[int, int, int, int]:
    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    monitor = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)) or not info.dwFlags & 1:
        raise OSError("Primary monitor could not be verified")
    return info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom


class ControlWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("browsed-local · 가상 화면 제어")
        self.root.resizable(False, False)
        self.closed = False
        self.backend = ServerBackend()
        self.requests = RequestState()
        self.results: queue.Queue = queue.Queue()
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("TLabel", font=("맑은 고딕", 11))
        style.configure("TButton", font=("맑은 고딕", 11), padding=(12, 9))
        style.configure("Header.TLabel", font=("맑은 고딕", 20, "bold"))
        style.configure("Status.TLabel", font=("맑은 고딕", 16, "bold"))
        style.configure("Notice.TLabel", foreground="#5b6470", font=("맑은 고딕", 10))
        frame = ttk.Frame(self.root, padding=24)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="browsed-local", style="Header.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 16))
        self.status_text = tk.StringVar(value="확인 중")
        self.status_label = ttk.Label(frame, textvariable=self.status_text, style="Status.TLabel")
        self.status_label.grid(row=1, column=0, sticky="w")
        self.detail_text = tk.StringVar(value="현재 서버 상태를 확인하고 있습니다.")
        detail_height = tkfont.Font(self.root, font=("맑은 고딕", 11)).metrics("linespace") * 3 + 4
        detail_area = ttk.Frame(frame, width=490, height=detail_height)
        detail_area.grid(row=2, column=0, sticky="ew", pady=(6, 18))
        detail_area.grid_propagate(False)
        ttk.Label(detail_area, textvariable=self.detail_text, wraplength=490, justify="left", anchor="nw").grid(row=0, column=0, sticky="nw")
        powers = ttk.Frame(frame)
        powers.grid(row=3, column=0, sticky="ew")
        powers.columnconfigure((0, 1), weight=1)
        self.on_button = ttk.Button(powers, text="켜기", command=lambda: self.request("start"))
        self.off_button = ttk.Button(powers, text="끄기", command=lambda: self.request("stop"))
        self.on_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.off_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.open_button = ttk.Button(frame, text="화면 열기", command=self.open_screen)
        self.open_button.grid(row=4, column=0, sticky="ew", pady=(12, 14))
        account = ttk.Frame(frame)
        account.grid(row=5, column=0, sticky="ew")
        account.columnconfigure(0, weight=1)
        ttk.Label(account, text="접속 계정: codex").grid(row=0, column=0, sticky="w")
        self.copy_button = ttk.Button(account, text="비밀번호 복사", command=self.copy_password)
        self.copy_button.grid(row=0, column=1, sticky="e")
        self.feedback = tk.StringVar(value="")
        feedback_height = tkfont.Font(self.root, font=("맑은 고딕", 10)).metrics("linespace") * 2 + 4
        feedback_area = ttk.Frame(frame, width=490, height=feedback_height)
        feedback_area.grid(row=6, column=0, sticky="ew", pady=(6, 8))
        feedback_area.grid_propagate(False)
        ttk.Label(feedback_area, textvariable=self.feedback, style="Notice.TLabel", wraplength=490, justify="left", anchor="nw").grid(row=0, column=0, sticky="nw")
        ttk.Separator(frame).grid(row=7, column=0, sticky="ew", pady=(2, 12))
        ttk.Label(frame, text="이 창을 닫아도 서버는 계속 실행됩니다.\n서버를 꺼도 가상 모니터는 유지됩니다.", style="Notice.TLabel").grid(row=8, column=0, sticky="w")
        self.root.update_idletasks()
        width, height = max(560, self.root.winfo_reqwidth()), self.root.winfo_reqheight()
        try:
            left, top, right, bottom = primary_work_area()
            x, y = left + (right - left - width) // 2, top + (bottom - top - height) // 2
            self.root.geometry(f"{width}x{height}{x:+d}{y:+d}")
        except OSError:
            # Never reuse a previous Tk position on the virtual monitor.
            self.root.geometry(f"{width}x{height}+100+100")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.render()
        self.root.deiconify()
        self.root.after(0, lambda: self.request("status"))
        self.root.after(100, self.consume_results)
        self.root.after(6000, self.poll)

    def request(self, action: str) -> None:
        ticket = self.requests.begin(action)
        if ticket is None:
            return
        if action != "status":
            self.feedback.set("")
            self.render()

        def work() -> None:
            try:
                result = self.backend.call(action)
            except Exception:
                result = ServerStatus("error", "action_failed")
            self.results.put((ticket, result))

        threading.Thread(target=work, daemon=True).start()

    def consume_results(self) -> None:
        if self.closed:
            return
        while True:
            try:
                ticket, result = self.results.get_nowait()
            except queue.Empty:
                break
            if self.requests.finish(ticket, result):
                self.render()
        self.root.after(100, self.consume_results)

    def poll(self) -> None:
        if not self.closed:
            self.request("status")
            self.root.after(6000, self.poll)

    def render(self) -> None:
        pending = self.requests.pending_action
        state = self.requests.status.state
        if pending:
            self.status_text.set("켜는 중…" if pending.action == "start" else "끄는 중…")
            self.status_label.configure(foreground="#9a6700")
            self.detail_text.set("명령을 처리하고 있습니다. 잠시 기다려 주세요.")
        elif self.requests.sequence == 0 or (self.requests.pending_poll and self.requests.sequence == 1):
            self.status_text.set("확인 중")
            self.status_label.configure(foreground="#5b6470")
        else:
            self.status_text.set({"on": "켜짐", "off": "꺼짐", "error": "확인 오류"}[state])
            self.status_label.configure(foreground={"on": "#16733c", "off": "#5b6470", "error": "#b42318"}[state])
            self.detail_text.set(self.requests.status.message)
        self.on_button.configure(state="disabled" if pending or state == "on" else "normal")
        self.off_button.configure(state="disabled" if pending or state == "off" else "normal")
        self.open_button.configure(state="normal" if not pending and state == "on" else "disabled")
        self.copy_button.configure(state="disabled" if pending else "normal")

    def open_screen(self) -> None:
        try:
            if not webbrowser.open(SCREEN_URL, new=2):
                self.feedback.set("브라우저를 열지 못했습니다. 주소: " + SCREEN_URL)
        except OSError:
            self.feedback.set("브라우저를 열지 못했습니다. 주소: " + SCREEN_URL)

    def copy_password(self) -> None:
        try:
            data = json.loads((SERVER_ROOT / "credentials.json").read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError
            password = data.get("password")
            if data.get("host") != "127.0.0.1" or data.get("port") != 16901 or not isinstance(password, str) or not password:
                raise ValueError
            self.root.clipboard_clear()
            self.root.clipboard_append(password)
            self.root.update_idletasks()
            self.feedback.set("비밀번호를 복사했습니다. 접속 창에 붙여 넣으세요.")
        except (OSError, ValueError, tk.TclError):
            self.feedback.set("비밀번호를 읽거나 복사하지 못했습니다.")

    def close(self) -> None:
        self.closed = True
        self.root.destroy()


if __name__ == "__main__":
    set_dpi_awareness()
    ControlWindow().root.mainloop()
