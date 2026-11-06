import unittest

import bl_win
from bl_win import MonitorInfo, Rect, pick_virtual, target_rect_for


def mon(device, rect, primary=False, adapter=""):
    r = Rect(*rect)
    return MonitorInfo(device, r, r, primary, adapter)


REAL = mon(r"\\.\DISPLAY1", (0, 0, 3840, 2400), True, "NVIDIA GeForce RTX 5090 Laptop GPU")
VIRTUAL = mon(r"\\.\DISPLAY5", (3840, 0, 5760, 1080), False, "Virtual Display Driver")


class PickVirtualTests(unittest.TestCase):
    def test_by_adapter_name(self):
        self.assertEqual(pick_virtual([REAL, VIRTUAL]), VIRTUAL)

    def test_never_picks_the_primary_even_if_named_virtual(self):
        fake = mon(r"\\.\DISPLAY1", (0, 0, 1920, 1080), True, "Virtual Display Driver")
        self.assertIsNone(pick_virtual([fake]))

    def test_explicit_device_wins(self):
        other = mon(r"\\.\DISPLAY7", (5760, 0, 7680, 1080), False, "Some Panel")
        self.assertEqual(pick_virtual([REAL, VIRTUAL, other], device=r"\\.\display7"), other)
        self.assertIsNone(pick_virtual([REAL, VIRTUAL], device=r"\\.\DISPLAY9"))

    def test_single_secondary_monitor_is_the_fallback(self):
        odd = mon(r"\\.\DISPLAY3", (3840, 0, 5760, 1080), False, "Unknown Adapter")
        self.assertEqual(pick_virtual([REAL, odd]), odd)

    def test_ambiguous_secondaries_return_none(self):
        a = mon(r"\\.\DISPLAY3", (3840, 0, 5760, 1080), False, "Panel A")
        b = mon(r"\\.\DISPLAY4", (5760, 0, 7680, 1080), False, "Panel B")
        self.assertIsNone(pick_virtual([REAL, a, b]))

    def test_two_named_virtual_monitors_are_ambiguous(self):
        v2 = mon(r"\\.\DISPLAY6", (5760, 0, 7680, 1080), False, "Virtual Display Driver")
        self.assertIsNone(pick_virtual([REAL, VIRTUAL, v2]))


class PlacementTests(unittest.TestCase):
    def test_window_is_shrunk_to_fit_and_stays_inside(self):
        src_area = Rect(0, 0, 3840, 2304)
        dst_area = Rect(3840, 0, 5760, 1032)
        new = target_rect_for(Rect(392, 392, 3272, 2084), src_area, dst_area)
        self.assertLessEqual(new.width, dst_area.width)
        self.assertLessEqual(new.height, dst_area.height)
        self.assertTrue(dst_area.left <= new.left and new.right <= dst_area.right)
        self.assertTrue(dst_area.top <= new.top and new.top < dst_area.bottom)

    def test_small_window_keeps_its_size_and_relative_position(self):
        src_area = Rect(0, 0, 3840, 2304)
        dst_area = Rect(3840, 0, 5760, 1032)
        new = target_rect_for(Rect(0, 0, 800, 600), src_area, dst_area)
        self.assertEqual((new.width, new.height), (800, 600))
        self.assertEqual((new.left, new.top), (3840, 0))  # top-left stays top-left
        far = target_rect_for(Rect(3040, 1704, 3840, 2304), src_area, dst_area)
        self.assertEqual(far.right, 5760)  # bottom-right stays bottom-right (x)

    def test_title_bar_stays_reachable_for_tall_windows(self):
        src_area = Rect(0, 0, 3840, 2304)
        dst_area = Rect(3840, 0, 5760, 1032)
        new = target_rect_for(Rect(100, 1900, 1100, 2300), src_area, dst_area)
        self.assertLess(new.top, dst_area.bottom - 30)


class RealSystemSmoke(unittest.TestCase):
    def test_monitor_enumeration_reports_a_primary(self):
        mons = bl_win.list_monitors()
        self.assertTrue(mons)
        self.assertEqual(sum(1 for m in mons if m.primary), 1)

    def test_rect_helpers(self):
        r = Rect(10, 20, 110, 220)
        self.assertEqual((r.width, r.height), (100, 200))
        self.assertTrue(r.contains(10, 20))
        self.assertFalse(r.contains(110, 20))  # right edge is exclusive


if __name__ == "__main__":
    unittest.main()
