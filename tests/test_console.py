"""Console driver tests: wrapping, scrolling, backspace, reverse video, cursor
addressing and colours, read back from screen RAM, colour RAM and the VIC.

    xvfb-run -a make test-only T="tests.test_console"
"""
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")

SCREEN = 0x0400
COLRAM = 0xD800
ROW, COL, REVERSE, COLOR = 0xD6, 0xD3, 0xC7, 0x0286


def nibbles(values):
    return {v & 0x0F for v in values}      # colour RAM is 4 bits wide


class Console(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_con.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = Vice(cls.img)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def byte(self, addr):
        return self.v.mem(addr, addr)[0]

    def test_clear_homes_the_cursor(self):
        self.v.type("clear\n")
        self.v.wait_for("/ $")
        time.sleep(1)
        lines = self.v.screen_lines()
        self.assertEqual(lines[0], "/ $")
        self.assertEqual([l for l in lines[1:] if l], [])
        self.assertEqual((self.byte(ROW), self.byte(COL)), (0, 4))

    def test_long_line_wraps_at_column_40(self):
        # the command line wraps too, so read the screen rather than use run()
        self.v.type("clear\n")
        self.v.wait_for("/ $")
        self.v.type("echo " + "x" * 50 + "\n")
        time.sleep(2)
        lines = [l for l in self.v.screen_lines() if l]
        i = lines.index("x" * 40)                 # the echoed output, not the command line
        self.assertEqual(lines[i + 1], "x" * 10)
        self.assertEqual(lines[-1], "/ $")

    def test_backspace_erases(self):
        self.v.type("clear\n")
        self.v.wait_for("/ $")
        self.v.type("echo abcd")
        self.v._cmd("keybuf \\x14\\x14")        # DEL DEL
        self.v._cmd("x")
        time.sleep(1)
        self.v.type("\n")
        time.sleep(1.5)
        lines = [l for l in self.v.screen_lines() if l]
        self.assertEqual(lines[0], "/ $ echo ab")
        self.assertEqual(lines[1], "ab")

    def test_scrolls_at_the_bottom(self):
        self.v.type("clear\n")
        self.v.wait_for("/ $")
        self.v.type("ls -l /bin\n")
        time.sleep(15)
        lines = self.v.screen_lines()
        self.assertEqual(lines[24], "/ $")                 # prompt back on the last row
        self.assertNotEqual(lines[0], "/ $ clear")          # the top has scrolled away
        self.assertTrue(any("whoami" in l for l in lines))  # the end of the listing is there
        self.assertEqual(self.byte(ROW), 24)

    def test_reverse_video_and_cursor_addressing(self):
        self.v.type("clear\n")
        self.v.wait_for("/ $")
        self.v.type("edit /home/c.txt\n")
        self.v.wait_for("edit:", timeout=60)
        time.sleep(1)
        raw = self.v.mem(SCREEN, SCREEN + 999)
        rows = [raw[i * 40:(i + 1) * 40] for i in range(25)]
        reversed_rows = [i for i, r in enumerate(rows) if any(c & 0x80 for c in r)]
        self.assertTrue(reversed_rows, "the editor's status line is drawn in reverse video")
        self.v.type("hello")
        time.sleep(1.5)
        self.assertEqual((self.byte(ROW), self.byte(COL)), (0, 5))   # ESC = put it after the text
        self.v._cmd("keybuf \\x0f")                                  # ^O save
        self.v._cmd("x")
        self.v.wait_for(" saved")
        self.v._cmd("keybuf \\x18")                                  # ^X quit
        self.v._cmd("x")
        self.v.wait_for("/ $", timeout=30, after="edit /home/c.txt")
        self.assertEqual(self.byte(REVERSE), 0)

    def test_theme_colours_the_whole_screen(self):
        for name, fg, bg, border in (("amber", 8, 0, 0), ("c64", 14, 6, 14), ("green", 13, 0, 0)):
            self.v.run("theme " + name)
            time.sleep(1)
            self.assertEqual(self.byte(COLOR), fg, name)
            self.assertEqual(nibbles(self.v.mem(COLRAM, COLRAM + 999)), {fg}, name)
            self.assertEqual(self.byte(0xD021) & 0x0F, bg, name)
            self.assertEqual(self.byte(0xD020) & 0x0F, border, name)


if __name__ == "__main__":
    unittest.main()
