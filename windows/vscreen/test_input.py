import unittest

import bl_input
from bl_win import MonitorInfo, Rect

V = MonitorInfo(r"\\.\DISPLAY5", Rect(3840, 0, 5760, 1080), Rect(3840, 0, 5760, 1032), False, "Virtual Display Driver")


class ComboTests(unittest.TestCase):
    def test_parse_combo(self):
        self.assertEqual(bl_input.parse_combo("ctrl+shift+t"), [0x11, 0x10, 0x54])
        self.assertEqual(bl_input.parse_combo("Enter"), [0x0D])
        self.assertEqual(bl_input.parse_combo("alt + f4"), [0x12, 0x73])
        self.assertEqual(bl_input.parse_combo("win+7"), [0x5B, ord("7")])

    def test_unknown_or_empty_names_are_rejected(self):
        for bad in ("ctrl+", "nonsense", "ctrl++x", ""):
            with self.assertRaises(ValueError, msg=bad):
                bl_input.parse_combo(bad)

    def test_function_keys(self):
        self.assertEqual(bl_input.parse_combo("f1"), [0x70])
        self.assertEqual(bl_input.parse_combo("f12"), [0x7B])


class CoordinateTests(unittest.TestCase):
    def test_stream_pixels_map_onto_the_virtual_monitor(self):
        self.assertEqual(bl_input.to_screen(V, 0, 0), (3840, 0))
        self.assertEqual(bl_input.to_screen(V, 960, 540), (4800, 540))
        self.assertEqual(bl_input.to_screen(V, 1919, 1079), (5759, 1079))

    def test_out_of_range_is_clamped_never_leaks_to_the_real_monitor(self):
        self.assertEqual(bl_input.to_screen(V, -50, -9), (3840, 0))
        self.assertEqual(bl_input.to_screen(V, 99999, 99999), (5759, 1079))


class StructTests(unittest.TestCase):
    def test_input_struct_size_matches_windows(self):
        import ctypes
        self.assertEqual(ctypes.sizeof(bl_input.INPUT), 40)  # x64 SendInput contract


if __name__ == "__main__":
    unittest.main()
