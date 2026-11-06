import unittest

from guard_logic import Candidate, GuardConfig, Tracker, VirtualContext, exe_name, should_move


def cand(**kw):
    base = dict(hwnd=100, title="Untitled - App", exe=r"C:\Apps\app.exe", on_virtual=False, width=900, height=600, covers_monitor=False, minimized=False)
    base.update(kw)
    return Candidate(**base)


CFG = GuardConfig()


class ContextTests(unittest.TestCase):
    def test_virtual_input_opens_a_window_that_expires(self):
        ctx = VirtualContext(12.0)
        self.assertFalse(ctx.active(0.0))
        ctx.note_input(10.0, on_virtual=True)
        self.assertTrue(ctx.active(21.9))
        self.assertFalse(ctx.active(22.1))

    def test_real_monitor_input_cancels_it_immediately(self):
        ctx = VirtualContext(12.0)
        ctx.note_input(10.0, on_virtual=True)
        ctx.note_input(11.0, on_virtual=False)
        self.assertFalse(ctx.active(11.5))


class DecisionTests(unittest.TestCase):
    def test_new_window_on_real_monitor_after_virtual_input_moves(self):
        ok, why = should_move(cand(), True, CFG, set())
        self.assertTrue(ok, why)

    def test_nothing_moves_without_recent_virtual_input(self):
        ok, why = should_move(cand(), False, CFG, set())
        self.assertFalse(ok)
        self.assertIn("no recent input", why)

    def test_window_already_on_virtual_is_left_alone(self):
        self.assertFalse(should_move(cand(on_virtual=True), True, CFG, set())[0])

    def test_each_window_is_handled_once(self):
        self.assertFalse(should_move(cand(hwnd=5), True, CFG, {5})[0])

    def test_fullscreen_minimized_and_tiny_windows_are_skipped(self):
        self.assertFalse(should_move(cand(covers_monitor=True), True, CFG, set())[0])
        self.assertFalse(should_move(cand(minimized=True), True, CFG, set())[0])
        self.assertFalse(should_move(cand(width=60, height=40), True, CFG, set())[0])

    def test_the_viewer_and_the_control_panel_are_never_moved(self):
        self.assertFalse(should_move(cand(title="browsed-local - Aside"), True, CFG, set())[0])
        self.assertFalse(should_move(cand(title="browsed-local 가상 화면 제어"), True, CFG, set())[0])
        self.assertFalse(should_move(cand(title="가상 화면 제어"), True, CFG, set())[0])

    def test_extra_ignore_rules(self):
        cfg = GuardConfig(ignore_exes=("OBS64.exe",), ignore_title_contains=("my viewer",))
        self.assertFalse(should_move(cand(exe=r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"), True, cfg, set())[0])
        self.assertFalse(should_move(cand(title="Zenovis My Viewer - Chrome"), True, cfg, set())[0])
        self.assertTrue(should_move(cand(), True, cfg, set())[0])

    def test_exe_name(self):
        self.assertEqual(exe_name(r"C:\X\Y\Notepad.EXE"), "notepad.exe")
        self.assertEqual(exe_name(""), "")


class TrackerTests(unittest.TestCase):
    def test_two_looks_then_stop(self):
        t = Tracker(GuardConfig(settle_s=0.35, recheck_s=1.6, give_up_s=5.0))
        t.saw(7, 100.0)
        self.assertEqual(t.due(100.1), [])
        self.assertEqual(t.due(100.4), [7])  # settle look
        self.assertEqual(t.due(100.9), [])
        self.assertEqual(t.due(101.7), [7])  # recheck look
        self.assertEqual(t.due(102.0), [])
        self.assertEqual(t.due(106.0), [])
        self.assertNotIn(7, t.pending)

    def test_existing_windows_are_never_scheduled(self):
        t = Tracker(CFG)
        t.handled.add(9)
        t.saw(9, 1.0)
        self.assertEqual(t.due(5.0), [])

    def test_marking_handled_cancels_pending(self):
        t = Tracker(CFG)
        t.saw(3, 0.0)
        t.mark_handled(3)
        self.assertEqual(t.due(2.0), [])

    def test_handled_set_stays_bounded(self):
        t = Tracker(CFG)
        for i in range(2500):
            t.mark_handled(i)
        self.assertLess(len(t.handled), 2100)


if __name__ == "__main__":
    unittest.main()
