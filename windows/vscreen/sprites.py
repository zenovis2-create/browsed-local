"""Pure-Python cursor sprites and click/wheel effects (no Win32, no third-party packages).

All pixel buffers are premultiplied BGRA, the format `UpdateLayeredWindow` wants.
"""
from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass

Point = tuple[float, float]

# --------------------------------------------------------------------------- geometry
# Shapes are drawn in "design units" (an arrow is about 12 x 20) and scaled at render time.
# A shape is a list of groups; a group is a list of rings combined with the even-odd rule
# (so a ring with a hole is [outer, inner]).

_ARROW: list[Point] = [(0, 0), (0, 17), (4.2, 13.2), (7.2, 20), (9.8, 18.9), (6.9, 12.3), (12.4, 12.3)]


def _rot(pts: list[Point], deg: float, cx: float, cy: float) -> list[Point]:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in pts]


def _circle(cx: float, cy: float, r: float, n: int = 28) -> list[Point]:
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


_DBL_V: list[Point] = [(5, 0), (10, 6), (7, 6), (7, 18), (10, 18), (5, 24), (0, 18), (3, 18), (3, 6), (0, 6)]
_DBL_H: list[Point] = [(y, x) for x, y in _DBL_V]

SHAPES: dict[str, tuple[list[list[list[Point]]], Point]] = {
    "arrow": ([[_ARROW]], (0.0, 0.0)),
    "ibeam": ([[[(5, 2), (8, 2), (8, 22), (5, 22)]], [[(1.5, 0), (11.5, 0), (11.5, 2.5), (1.5, 2.5)]], [[(1.5, 21.5), (11.5, 21.5), (11.5, 24), (1.5, 24)]]], (6.5, 12.0)),
    "hand": ([[[(3, 0), (6.5, 0), (6.5, 10), (3, 10)]], [[(0, 10), (13, 10), (13, 17), (10, 22), (3, 22), (0, 17)]], [[(0, 10), (3, 10), (3, 14), (0, 13)]]], (4.7, 0.0)),
    "cross": ([[[(0, 10), (20, 10), (20, 12), (0, 12)]], [[(9, 0), (11, 0), (11, 22), (9, 22)]]], (10.0, 11.0)),
    "wait": ([[[(2, 0), (16, 0), (9, 11)]], [[(9, 11), (2, 22), (16, 22)]]], (9.0, 11.0)),
    "appstarting": ([[_ARROW], [[(13, 12), (21, 12), (17, 17)]], [[(17, 17), (13, 22), (21, 22)]]], (0.0, 0.0)),
    "no": ([[_circle(10, 10, 10), _circle(10, 10, 7)], [[(3.3, 5.6), (5.6, 3.3), (16.7, 14.4), (14.4, 16.7)]]], (10.0, 10.0)),
    "size_ns": ([[_DBL_V]], (5.0, 12.0)),
    "size_we": ([[_DBL_H]], (12.0, 5.0)),
    "size_nwse": ([[_rot(_DBL_V, 45, 5, 12)]], (5.0, 12.0)),
    "size_nesw": ([[_rot(_DBL_V, -45, 5, 12)]], (5.0, 12.0)),
    # both arrows centred on (12, 12) so they cross like a plus
    "size_all": ([[[(x + 7, y) for x, y in _DBL_V]], [[(x, y + 7) for x, y in _DBL_H]]], (12.0, 12.0)),
}

PAD = 3  # transparent border around a sprite so the outline never clips
CANVAS = 96  # every pointer sprite is padded into a CANVAS x CANVAS buffer


@dataclass(frozen=True)
class Sprite:
    hx: int  # hotspot inside the CANVAS x CANVAS buffer
    hy: int
    data: bytes  # CANVAS * CANVAS * 4, premultiplied BGRA


def _inside(px: float, py: float, ring: list[Point]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _coverage(w: int, h: int, groups: list[list[list[Point]]], ox: float, oy: float, scale: float, ss: int = 3) -> list[float]:
    """Antialiased coverage (0..1) of the union of the groups, supersampled ss x ss."""
    cov = [0.0] * (w * h)
    for group in groups:
        rings = [[(ox + x * scale, oy + y * scale) for x, y in ring] for ring in group]
        xs = [p[0] for r in rings for p in r]
        ys = [p[1] for r in rings for p in r]
        x0, x1 = max(0, int(min(xs)) - 1), min(w - 1, int(max(xs)) + 1)
        y0, y1 = max(0, int(min(ys)) - 1), min(h - 1, int(max(ys)) + 1)
        step = 1.0 / ss
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                hit = 0
                for sy in range(ss):
                    for sx in range(ss):
                        px = x + (sx + 0.5) * step
                        py = y + (sy + 0.5) * step
                        n = 0
                        for r in rings:
                            if _inside(px, py, r):
                                n += 1
                        if n & 1:
                            hit += 1
                c = hit / (ss * ss)
                i = y * w + x
                if c > cov[i]:
                    cov[i] = c
    return cov


def _dilate(cov: list[float], w: int, h: int, radius: float) -> list[float]:
    r = int(math.ceil(radius))
    offs = [(dx, dy) for dy in range(-r, r + 1) for dx in range(-r, r + 1) if dx * dx + dy * dy <= radius * radius + 0.25]
    out = [0.0] * (w * h)
    for y in range(h):
        for x in range(w):
            best = 0.0
            for dx, dy in offs:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    v = cov[ny * w + nx]
                    if v > best:
                        best = v
                        if best >= 1.0:
                            break
            out[y * w + x] = best
    return out


_cache: dict[tuple[str, float], Sprite] = {}


def render_shape(name: str, scale: float = 1.8) -> Sprite:
    """A white pointer with a dark outline, padded into a CANVAS x CANVAS premultiplied buffer."""
    key = (name, round(scale, 3))
    if key in _cache:
        return _cache[key]
    groups, (hx, hy) = SHAPES.get(name, SHAPES["arrow"])
    pts = [p for g in groups for ring in g for p in ring]
    minx = min(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    maxx = max(p[0] for p in pts)
    maxy = max(p[1] for p in pts)
    ox, oy = PAD - minx * scale, PAD - miny * scale
    w = min(CANVAS, int(math.ceil((maxx - minx) * scale)) + 2 * PAD + 1)
    h = min(CANVAS, int(math.ceil((maxy - miny) * scale)) + 2 * PAD + 1)
    fill = _coverage(w, h, groups, ox, oy, scale)
    edge = _dilate(fill, w, h, max(1.3, 0.9 * scale))
    buf = bytearray(CANVAS * CANVAS * 4)
    for y in range(h):
        for x in range(w):
            fa = fill[y * w + x]
            oa = edge[y * w + x]
            a = fa + oa * (1.0 - fa)
            if a <= 0.003:
                continue
            c = int(round(255 * fa))  # white fill over black edge, premultiplied
            i = (y * CANVAS + x) * 4
            buf[i] = buf[i + 1] = buf[i + 2] = c
            buf[i + 3] = int(round(255 * min(1.0, a)))
    sp = Sprite(int(round(ox + hx * scale)), int(round(oy + hy * scale)), bytes(buf))
    _cache[key] = sp
    return sp


# --------------------------------------------------------------------------- effects canvas

EFFECT_SIZE = 192


class Canvas:
    """A premultiplied-BGRA buffer with a few antialiased drawing helpers."""

    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.buf = bytearray(w * h * 4)

    def clear(self) -> None:
        self.buf[:] = bytes(len(self.buf))

    def over(self, x: int, y: int, rgb: tuple[int, int, int], a: float) -> None:
        if a <= 0.004 or x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        a = min(1.0, a)
        i = (y * self.w + x) * 4
        inv = 1.0 - a
        b = self.buf
        b[i] = int(rgb[2] * a + b[i] * inv + 0.5)
        b[i + 1] = int(rgb[1] * a + b[i + 1] * inv + 0.5)
        b[i + 2] = int(rgb[0] * a + b[i + 2] * inv + 0.5)
        b[i + 3] = int(255 * a + b[i + 3] * inv + 0.5)

    def ring(self, cx: float, cy: float, radius: float, thickness: float, rgb: tuple[int, int, int], alpha: float) -> None:
        r0 = int(radius + thickness + 2)
        for y in range(int(cy) - r0, int(cy) + r0 + 1):
            for x in range(int(cx) - r0, int(cx) + r0 + 1):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                cov = thickness / 2 + 0.5 - abs(d - radius)
                if cov > 0:
                    self.over(x, y, rgb, alpha * min(1.0, cov))

    def disc(self, cx: float, cy: float, radius: float, rgb: tuple[int, int, int], alpha: float) -> None:
        r0 = int(radius + 2)
        for y in range(int(cy) - r0, int(cy) + r0 + 1):
            for x in range(int(cx) - r0, int(cx) + r0 + 1):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                cov = radius + 0.5 - d
                if cov > 0:
                    self.over(x, y, rgb, alpha * min(1.0, cov))

    def round_rect(self, x0: float, y0: float, x1: float, y1: float, radius: float, rgb: tuple[int, int, int], alpha: float) -> None:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
        for y in range(int(y0) - 1, int(y1) + 2):
            for x in range(int(x0) - 1, int(x1) + 2):
                qx = abs(x + 0.5 - cx) - (hw - radius)
                qy = abs(y + 0.5 - cy) - (hh - radius)
                d = math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - radius
                cov = 0.5 - d
                if cov > 0:
                    self.over(x, y, rgb, alpha * min(1.0, cov))

    def polygon(self, pts: list[Point], rgb: tuple[int, int, int], alpha: float, ss: int = 3) -> None:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        step = 1.0 / ss
        for y in range(int(min(ys)) - 1, int(max(ys)) + 2):
            for x in range(int(min(xs)) - 1, int(max(xs)) + 2):
                hit = 0
                for sy in range(ss):
                    for sx in range(ss):
                        if _inside(x + (sx + 0.5) * step, y + (sy + 0.5) * step, pts):
                            hit += 1
                if hit:
                    self.over(x, y, rgb, alpha * hit / (ss * ss))


BUTTON_COLORS = {"left": (255, 140, 0), "right": (0, 170, 255), "middle": (170, 100, 255)}


def draw_ripple(c: Canvas, cx: float, cy: float, t: float, button: str = "left") -> None:
    """Expanding ring at the click point; t runs 0..1."""
    t = max(0.0, min(1.0, t))
    ease = 1 - (1 - t) ** 3
    rgb = BUTTON_COLORS.get(button, BUTTON_COLORS["left"])
    radius = 8 + 28 * ease
    alpha = 0.9 * (1 - t)
    c.ring(cx, cy, radius, 3.2 - 1.6 * t, rgb, alpha)
    if t < 0.35:
        c.disc(cx, cy, 5, rgb, 0.8 * (1 - t / 0.35))


def draw_wheel(c: Canvas, cx: float, cy: float, direction: str, phase: float, alpha: float) -> None:
    """A small badge beside the pointer: two triangles, the one in the scroll direction lit and
    nudged along it. direction: up | down | left | right."""
    alpha = max(0.0, min(1.0, alpha))
    if alpha <= 0:
        return
    nudge = 3.0 * math.sin(2 * math.pi * phase)
    lit, dim = (255, 196, 0), (170, 170, 170)
    vertical = direction in ("up", "down")
    if vertical:
        x0, y0 = cx + 30, cy - 32
        c.round_rect(x0, y0, x0 + 34, y0 + 64, 17, (15, 15, 15), 0.78 * alpha)
        mx = x0 + 17
        up_c, dn_c = (mx, y0 + 17), (mx, y0 + 47)
        up = [(-9, 6), (9, 6), (0, -6)]
        dn = [(-9, -6), (9, -6), (0, 6)]
        n = -nudge if direction == "up" else nudge
        c.polygon([(up_c[0] + px, up_c[1] + py + (n if direction == "up" else 0)) for px, py in up], lit if direction == "up" else dim, alpha if direction == "up" else 0.45 * alpha)
        c.polygon([(dn_c[0] + px, dn_c[1] + py + (n if direction == "down" else 0)) for px, py in dn], lit if direction == "down" else dim, alpha if direction == "down" else 0.45 * alpha)
    else:
        x0, y0 = cx + 30, cy - 17
        c.round_rect(x0, y0, x0 + 64, y0 + 34, 17, (15, 15, 15), 0.78 * alpha)
        my = y0 + 17
        l_c, r_c = (x0 + 17, my), (x0 + 47, my)
        left = [(6, -9), (6, 9), (-6, 0)]
        right = [(-6, -9), (-6, 9), (6, 0)]
        n = -nudge if direction == "left" else nudge
        c.polygon([(l_c[0] + px + (n if direction == "left" else 0), l_c[1] + py) for px, py in left], lit if direction == "left" else dim, alpha if direction == "left" else 0.45 * alpha)
        c.polygon([(r_c[0] + px + (n if direction == "right" else 0), r_c[1] + py) for px, py in right], lit if direction == "right" else dim, alpha if direction == "right" else 0.45 * alpha)


# --------------------------------------------------------------------------- preview (dev aid)


def png_bytes(w: int, h: int, rgba: bytes) -> bytes:
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _over_bgra(dst: bytearray, dw: int, src: bytes, sw: int, sh: int, ox: int, oy: int, bg_stride: int) -> None:
    for y in range(sh):
        for x in range(sw):
            si = (y * sw + x) * 4
            a = src[si + 3]
            if not a:
                continue
            di = ((oy + y) * dw + (ox + x)) * 4
            inv = 255 - a
            dst[di] = min(255, src[si] + dst[di] * inv // 255)
            dst[di + 1] = min(255, src[si + 1] + dst[di + 1] * inv // 255)
            dst[di + 2] = min(255, src[si + 2] + dst[di + 2] * inv // 255)
            dst[di + 3] = 255


def preview_sheet(scale: float = 1.8) -> tuple[int, int, bytes]:
    """All sprites plus a ripple and both wheel directions on a mid-grey desktop (RGBA)."""
    names = list(SHAPES)
    cell = 96
    cols = 6
    rows = (len(names) + cols - 1) // cols + 1
    w, h = cols * cell, rows * cell
    bgra = bytearray(b"\x70\x66\x5c\xff" * (w * h))  # a desktop-ish blue grey
    for i, n in enumerate(names):
        sp = render_shape(n, scale)
        _over_bgra(bgra, w, sp.data, CANVAS, CANVAS, (i % cols) * cell, (i // cols) * cell, w * 4)
    base_y = ((len(names) + cols - 1) // cols) * cell
    effects = [("ripple", 0.15, "left"), ("ripple", 0.5, "right"), ("wheel", "up"), ("wheel", "down"), ("wheel", "left"), ("wheel", "right")]
    for i, e in enumerate(effects):
        c = Canvas(cell, cell)
        if e[0] == "ripple":
            draw_ripple(c, 30, 48, e[1], e[2])
            sp = render_shape("arrow", scale)
            _over_bgra(c.buf, cell, sp.data, CANVAS, CANVAS, 30 - sp.hx, 48 - sp.hy, 0) if False else None
        else:
            draw_wheel(c, 14, 48, e[1], 0.25, 1.0)
        _over_bgra(bgra, w, bytes(c.buf), cell, cell, i * cell, base_y, w * 4)
    rgba = bytearray(len(bgra))
    for i in range(0, len(bgra), 4):
        rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3] = bgra[i + 2], bgra[i + 1], bgra[i], 255
    return w, h, bytes(rgba)


if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "sprite-preview.png"
    pw, ph, px = preview_sheet()
    with open(out, "wb") as f:
        f.write(png_bytes(pw, ph, px))
    print("wrote", out, pw, ph)
