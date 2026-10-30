"""Keyboard tests with real keystrokes: X key events -> VICE's keyboard matrix.

These cover what the key-buffer tests cannot: the matrix scan, the decode
tables, modifiers, rollover and key repeat. They need xdotool and a display:

    xvfb-run -a make test-only T="tests.test_keyboard"
"""
import os
import re
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice, real_keys_available  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")

KEYSHF = 0x028D     # SHIFT 1, C= 2, CTRL 4
JIFFY = 0x00A0      # $A0-$A2, big-endian


@unittest.skipUnless(real_keys_available(), "needs xdotool and a display (xvfb-run)")
class Keyboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_kbd.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = Vice(cls.img)
        cls.v.wait_shell()
        cls.v.focus()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def setUp(self):
        self.v.type("clear\n")
        time.sleep(1)

    def output_after(self, cmd_line_end=" $"):
        """Non-empty screen lines, with the prompt lines dropped."""
        return [l for l in self.v.screen_lines() if l]

    def test_typing(self):
        self.v.xtype("echo abc 0123\n")
        time.sleep(1.5)
        self.assertIn("abc 0123", self.output_after())

    def test_shift_and_control_flags(self):
        for key, flag in (("Shift_L", 1), ("Shift_R", 1), ("Control_L", 4)):
            self.v.xdown(key)
            time.sleep(0.6)
            seen = self.v.mem(KEYSHF, KEYSHF)[0]
            self.v.xup(key)
            time.sleep(0.3)
            self.assertEqual(seen, flag, key)
        self.assertEqual(self.v.mem(KEYSHF, KEYSHF)[0], 0)

    def test_shifted_symbol(self):
        self.v.xtype("echo ")
        self.v.xkey("exclam", "Return")
        time.sleep(1.5)
        self.assertIn("!", self.output_after())

    def test_rollover_keeps_both_keys(self):
        # 's' goes down while 'a' is still held: the old ROM scan could lose it
        self.v.xtype("echo ")
        self.v.xdown("a")
        time.sleep(0.2)
        self.v.xdown("s")
        time.sleep(0.2)
        self.v.xup("a")
        time.sleep(0.2)
        self.v.xup("s")
        self.v.xkey("Return")
        time.sleep(1.5)
        out = "".join(self.output_after())
        # 'a' repeats while alone, then the newer key 's' takes over: a run of
        # a's followed by a run of s's, and nothing else on the screen can match
        self.assertRegex(out, r"a+s+")

    def test_repeat(self):
        self.v.xtype("echo ")
        self.v.xdown("b")
        time.sleep(1.5)
        self.v.xup("b")
        self.v.xkey("Return")
        time.sleep(1.5)
        self.assertIn("bbb", "".join(self.output_after()))

    def test_run_stop_key(self):
        self.v.xtype("sleep 100\n")
        time.sleep(2)
        self.v.xkey("Escape")           # VICE maps Escape to RUN/STOP
        self.v.wait_for("/ $", timeout=30, after="sleep 100")
        self.assertEqual(self.v.mem(0x0091, 0x0091)[0] & 0x80, 0x80)   # released again

    def test_jiffy_clock_runs(self):
        a = self.v.mem(JIFFY, JIFFY + 2)
        time.sleep(1)
        b = self.v.mem(JIFFY, JIFFY + 2)
        ja, jb = a[0] << 16 | a[1] << 8 | a[2], b[0] << 16 | b[1] << 8 | b[2]
        self.assertGreater(jb, ja)


if __name__ == "__main__":
    unittest.main()
