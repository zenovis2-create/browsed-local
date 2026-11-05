"""Real Tk controls with an isolated fake backend; never touches a screen server."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from control_model import ServerStatus


loader = importlib.machinery.SourceFileLoader("browsed_local_gui", str(Path(__file__).with_name("virtual_screen_control.pyw")))
spec = importlib.util.spec_from_loader(loader.name, loader)
gui = importlib.util.module_from_spec(spec)
loader.exec_module(gui)


class FakeBackend:
    def __init__(self):
        self.calls = []

    def call(self, action):
        self.calls.append(action)
        return ServerStatus("on", "ready", 1) if action == "start" else ServerStatus("off", "stopped")


class GuiSmokeTests(unittest.TestCase):
    def test_controls_with_fake_server_and_fixture_password(self):
        with mock.patch.object(gui, "ServerBackend", FakeBackend):
            window = gui.ControlWindow()
        window.root.withdraw()
        self.addCleanup(lambda: window.close() if not window.closed else None)

        def settle():
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                window.root.update()
                if window.requests.pending_action is None and window.requests.pending_poll is None and window.requests.sequence:
                    return
                time.sleep(0.01)
            self.fail("Mock backend did not settle")

        settle()
        self.assertEqual(window.status_text.get(), "꺼짐")
        self.assertEqual(window.root.title(), "browsed-local · 가상 화면 제어")
        window.on_button.invoke()
        self.assertEqual(window.status_text.get(), "켜는 중…")
        self.assertTrue(window.off_button.instate(["disabled"]))
        settle()
        self.assertEqual(window.status_text.get(), "켜짐")
        with mock.patch.object(gui.webbrowser, "open", return_value=True) as open_browser:
            window.open_button.invoke()
            open_browser.assert_called_once_with("http://127.0.0.1:16901/", new=2)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            (fixture / "credentials.json").write_text(json.dumps({"host": "127.0.0.1", "port": 16901, "password": "fixture-only"}), encoding="utf-8")
            with mock.patch.object(gui, "SERVER_ROOT", fixture), mock.patch.object(window.root, "clipboard_clear"), mock.patch.object(window.root, "clipboard_append") as append:
                window.copy_button.invoke()
                append.assert_called_once_with("fixture-only")
                self.assertNotIn("fixture-only", window.feedback.get())
        window.off_button.invoke()
        settle()
        self.assertEqual(window.status_text.get(), "꺼짐")
        calls = list(window.backend.calls)
        window.close()
        self.assertEqual(window.backend.calls, calls, "Closing the GUI must never stop a server")


if __name__ == "__main__":
    unittest.main()
