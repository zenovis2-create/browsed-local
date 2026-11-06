import unittest

import sprites


class SpriteTests(unittest.TestCase):
    def test_every_shape_renders_inside_the_canvas(self):
        for name in sprites.SHAPES:
            sp = sprites.render_shape(name, 1.8)
            self.assertEqual(len(sp.data), sprites.CANVAS * sprites.CANVAS * 4, name)
            self.assertTrue(0 <= sp.hx < sprites.CANVAS and 0 <= sp.hy < sprites.CANVAS, f"{name} hotspot")
            opaque = sum(1 for i in range(3, len(sp.data), 4) if sp.data[i] > 0)
            self.assertGreater(opaque, 40, f"{name} is empty")

    def test_buffers_are_premultiplied(self):
        sp = sprites.render_shape("arrow", 1.8)
        for i in range(0, len(sp.data), 4):
            b, g, r, a = sp.data[i:i + 4]
            self.assertLessEqual(max(b, g, r), a, "colour channel above alpha is not premultiplied")

    def test_arrow_hotspot_is_the_tip(self):
        sp = sprites.render_shape("arrow", 1.8)
        # the tip is the top-left corner of the arrow, offset only by the padding
        self.assertEqual((sp.hx, sp.hy), (sprites.PAD, sprites.PAD))
        a = sp.data[(sp.hy * sprites.CANVAS + sp.hx) * 4 + 3]
        self.assertGreater(a, 0)

    def test_unknown_shape_falls_back_to_arrow(self):
        self.assertEqual(sprites.render_shape("no-such-shape", 1.8).data, sprites.render_shape("arrow", 1.8).data)

    def test_scale_changes_size(self):
        small = sprites.render_shape("arrow", 1.0).data
        big = sprites.render_shape("arrow", 2.4).data
        count = lambda d: sum(1 for i in range(3, len(d), 4) if d[i] > 0)
        self.assertGreater(count(big), count(small) * 2)


class EffectTests(unittest.TestCase):
    def painted(self, canvas):
        return sum(1 for i in range(3, len(canvas.buf), 4) if canvas.buf[i] > 0)

    def test_ripple_grows_and_fades(self):
        sizes = []
        for t in (0.1, 0.5, 0.95):
            c = sprites.Canvas(sprites.EFFECT_SIZE, sprites.EFFECT_SIZE)
            sprites.draw_ripple(c, 96, 96, t, "left")
            sizes.append(self.painted(c))
        self.assertGreater(sizes[1], sizes[0])
        self.assertGreater(sizes[0], 0)
        c = sprites.Canvas(sprites.EFFECT_SIZE, sprites.EFFECT_SIZE)
        sprites.draw_ripple(c, 96, 96, 1.0, "left")
        self.assertEqual(self.painted(c), 0, "a finished ripple must vanish")

    def test_each_wheel_direction_draws_a_badge_beside_the_pointer(self):
        for d in ("up", "down", "left", "right"):
            c = sprites.Canvas(sprites.EFFECT_SIZE, sprites.EFFECT_SIZE)
            sprites.draw_wheel(c, 96, 96, d, 0.25, 1.0)
            self.assertGreater(self.painted(c), 300, d)
            # nothing is drawn on top of the pointer's own spot (left of the badge)
            self.assertEqual(c.buf[(96 * sprites.EFFECT_SIZE + 90) * 4 + 3], 0, d)

    def test_wheel_fades_out(self):
        c = sprites.Canvas(sprites.EFFECT_SIZE, sprites.EFFECT_SIZE)
        sprites.draw_wheel(c, 96, 96, "up", 0.0, 0.0)
        self.assertEqual(self.painted(c), 0)

    def test_up_lights_the_top_triangle_and_down_the_bottom(self):
        def lit_rows(direction):
            c = sprites.Canvas(sprites.EFFECT_SIZE, sprites.EFFECT_SIZE)
            sprites.draw_wheel(c, 96, 96, direction, 0.0, 1.0)
            ys = [y for y in range(sprites.EFFECT_SIZE) for x in range(sprites.EFFECT_SIZE)
                  if c.buf[(y * sprites.EFFECT_SIZE + x) * 4 + 2] > 200 and c.buf[(y * sprites.EFFECT_SIZE + x) * 4] < 80]
            return ys
        up, down = lit_rows("up"), lit_rows("down")
        self.assertTrue(up and down)
        self.assertLess(sum(up) / len(up), 96)  # amber pixels in the upper half
        self.assertGreater(sum(down) / len(down), 96)  # amber pixels in the lower half

    def test_png_encoder_and_preview(self):
        w, h, px = sprites.preview_sheet()
        png = sprites.png_bytes(w, h, px)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(len(px), w * h * 4)


if __name__ == "__main__":
    unittest.main()
