"""Host test: the soft80 model's byte tricks equal the obvious per-pixel drawing."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soft80_render as m  # noqa: E402


def synth_font(seed=7):
    r = random.Random(seed)
    return bytes(((n := r.randrange(16)) << 4) | n for _ in range(256 * 8))


def ref_screen(font, grid):
    """Per-pixel reference: grid[row][col] = code or None."""
    px = [[0] * 320 for _ in range(200)]
    for row, line in enumerate(grid):
        for col, code in enumerate(line):
            if code is None:
                continue
            for y in range(8):
                for x in range(4):
                    px[row * 8 + y][col * 4 + x] = (font[code * 8 + y] >> (7 - x)) & 1
    return px


def pixels(s):
    return [[s.pixel(x, y) for x in range(320)] for y in range(200)]


class Soft80(unittest.TestCase):
    def setUp(self):
        self.font = synth_font()
        self.rnd = random.Random(1)

    def test_put_matches_reference_any_order(self):
        s = m.Soft80(self.font)
        grid = [[None] * 80 for _ in range(25)]
        for _ in range(1500):
            c, r, code = self.rnd.randrange(80), self.rnd.randrange(25), self.rnd.randrange(256)
            s.put(c, r, code)
            grid[r][c] = code
        self.assertEqual(pixels(s), ref_screen(self.font, grid))

    def test_put_string_equals_put_and_saves_reads(self):
        a, b = m.Soft80(self.font), m.Soft80(self.font)
        for _ in range(200):
            c, r = self.rnd.randrange(60), self.rnd.randrange(25)
            codes = [self.rnd.randrange(256) for _ in range(self.rnd.randrange(1, 20))]
            a.put_string(c, r, codes)
            for i, code in enumerate(codes):
                b.put(c + i, r, code)
        self.assertEqual(a.bitmap, b.bitmap)
        self.assertEqual(a.lastpos, b.lastpos)
        self.assertLess(a.reads, b.reads // 2)

    def test_reverse_is_inverted_glyph(self):
        s = m.Soft80(self.font)
        s.put(3, 2, 65, reverse=True)
        s.put(3, 2, 65)
        plain = pixels(s)
        s.put(3, 2, 65, reverse=True)
        for y in range(16, 24):
            for x in range(12, 16):
                self.assertEqual(s.pixel(x, y), 1 - plain[y][x])

    def test_scroll_with_high_water_equals_full_copy(self):
        s = m.Soft80(self.font)
        text = "".join("x" * self.rnd.randrange(0, 80) + "\n" for _ in range(60))
        s.write(text)
        full = bytearray(s.bitmap)
        # full-copy reference: scroll the final bitmap once by hand
        n = 3
        ref = bytearray(8000)
        ref[:(25 - n) * 320] = full[n * 320:]
        s.scroll_up(n)
        self.assertEqual(s.bitmap, ref)

    def test_lookahead_scroll_one_pass(self):
        a, b = m.Soft80(self.font), m.Soft80(self.font)
        a.write("hi\n" * 24 + "\n\n\n\n")
        for ch in "hi\n" * 24 + "\n\n\n\n":
            b.write(ch)
        self.assertEqual(a.bitmap, b.bitmap)
        self.assertLess(a.reads + a.writes, b.reads + b.writes)

    def test_font_validation(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as f:
            f.write(bytes(2048)); f.flush()
            self.assertEqual(len(m.load_font(f.name)), 2048)
        with tempfile.NamedTemporaryFile() as f:
            f.write(bytes([0x10]) * 2048); f.flush()
            with self.assertRaises(ValueError):
                m.load_font(f.name)


if __name__ == "__main__":
    unittest.main()
