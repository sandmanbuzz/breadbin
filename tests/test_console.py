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
from vicetest import make_target  # noqa: E402

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
        cls.v = make_target(cls.img)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def wait_lines(self, done, timeout=30):
        """The non-empty screen lines once done(lines) holds: a command that loads a
        program from disk takes seconds on a real drive, so do not sleep and hope."""
        end = time.time() + timeout
        while True:
            lines = [l for l in self.v.screen_lines() if l]
            if done(lines) or time.time() > end:
                return lines
            time.sleep(0.2)

    def ls_bin(self, timeout=90):
        """Type `ls -l /bin` and return the screen lines once the whole listing has been drawn: the
        screen has changed from before (or, when the same listing repeats and finishes before the first
        look, 4 s have passed: the shell has long since taken the line), the last row is the prompt, the listing's last entry is
        on screen and the screen has held still for a second (a disk read can pause the listing)."""
        before = self.v.screen_lines()
        self.v.type("ls -l /bin\n")
        start = time.time()
        end = start + timeout
        stable = None
        while time.time() < end:
            time.sleep(0.5)
            lines = self.v.screen_lines()
            done = ((lines != before or time.time() - start > 4) and lines[24] == "/ $" and any("whoami" in l for l in lines))
            if done and lines == stable:
                return lines
            stable = lines if done else None
        raise TimeoutError("ls -l /bin did not finish:\n" + "\n".join(lines))

    def byte(self, addr):
        return self.v.mem(addr, addr)[0]

    def test_clear_homes_the_cursor(self):
        self.v.type("clear\n")
        lines = self.wait_lines(lambda l: l == ["/ $"])
        self.assertEqual(lines, ["/ $"])
        self.assertEqual((self.byte(ROW), self.byte(COL)), (0, 4))

    def test_long_line_wraps_at_column_40(self):
        # the command line wraps too, so read the screen rather than use run()
        self.v.type("clear\n")
        self.wait_lines(lambda l: l == ["/ $"])
        self.v.type("echo " + "x" * 50 + "\n")
        lines = self.wait_lines(lambda l: "x" * 40 in l and l[-1] == "/ $")
        i = lines.index("x" * 40)                 # the echoed output, not the command line
        self.assertEqual(lines[i + 1], "x" * 10)
        self.assertEqual(lines[-1], "/ $")

    def test_backspace_erases(self):
        self.v.type("clear\n")
        self.wait_lines(lambda l: l == ["/ $"])
        self.v.type("echo abcd")
        self.v.keybuf(b"\x14\x14")        # DEL DEL
        time.sleep(1)
        self.v.type("\n")
        lines = self.wait_lines(lambda l: "ab" in l and l[-1] == "/ $")
        self.assertEqual(lines[0], "/ $ echo ab")
        self.assertEqual(lines[1], "ab")

    def test_scrolls_at_the_bottom(self):
        self.v.type("clear\n")
        self.v.wait_for("/ $")
        lines = self.ls_bin()
        self.assertEqual(lines[24], "/ $")                 # prompt back on the last row
        self.assertNotEqual(lines[0], "/ $ clear")          # the top has scrolled away
        self.assertTrue(any("whoami" in l for l in lines))  # the end of the listing is there
        self.assertEqual(self.byte(ROW), 24)

    def test_scroll_flood_keeps_every_row_distinct(self):
        """Many scrolls in a row: each screen row is a whole line of the listing and no
        row repeats its neighbour (a torn or half-done copy shows as a doubled row).
        Screen RAM only: the beam itself is not visible to the emulator's memory dump."""
        self.v.type("clear\n")
        self.v.wait_for("/ $")
        for _ in range(6):
            lines = self.ls_bin()
        self.assertEqual(lines[24], "/ $")
        body = [l for l in lines[:24] if l]
        self.assertGreaterEqual(len(body), 20)
        names = {l.split()[-1] for l in body if not l.startswith("/ $")}
        for a, b in zip(body, body[1:]):
            self.assertNotEqual(a, b, "doubled row: " + repr(lines))
        listing = [l for l in body if not l.startswith("/ $")]
        self.assertTrue(all(len(l.split()) >= 2 for l in listing), listing)
        self.assertTrue(names)

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
        self.v.keybuf(b"\x0f")                                  # ^O save
        self.v.wait_for(" saved")
        self.v.keybuf(b"\x18")                                  # ^X quit
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
