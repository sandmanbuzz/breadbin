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
from vicetest import make_target, real_keys_available  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")

KEYSHF = 0x028D     # SHIFT 1, C= 2, CTRL 4
JIFFY = 0x00A0      # $A0-$A2, big-endian


@unittest.skipUnless(real_keys_available() or os.environ.get("BREADBIN_TARGET") == "ultimate",
                     "needs xdotool and a display (xvfb-run), or an Ultimate")
class Keyboard(unittest.TestCase):
    """Real keystrokes need real time. X key events arrive on wall-clock time; in
    VICE's warp mode the emulated machine runs a varying number of times faster
    than that, so a key can be pressed and released between two keyboard scans
    (lost), or held for half a second of emulated time (repeats). So this class
    runs VICE at real speed, where a 60 ms key hold is 60 ms for the machine
    too, and waits for screen state instead of sleeping: commands load from
    the disk in real time."""

    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_kbd.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = make_target(cls.img, warp=False)
        cls.v.wait_shell(timeout=240)
        cls.v.focus()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def until(self, pred, timeout=40, what="the screen to show it"):
        """Poll the screen's non-empty lines until pred(lines) is true."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            lines = [l for l in self.v.screen_lines() if l]
            if pred(lines):
                return lines
            time.sleep(0.4)
        self.fail("timed out waiting for %s:\n%s" % (what, self.v.screen()))

    def tearDown(self):
        # a test that fails must not leave a job running for the next one
        self.v.keybuf(b"\x03")
        time.sleep(1)

    def setUp(self):
        self.v.type("clear\n")
        self.until(lambda l: l == ["/ $"], what="a cleared screen")

    def test_typing(self):
        self.v.xtype("echo abc 0123\n")
        self.until(lambda l: "abc 0123" in l, what="the echoed text")

    def test_shift_and_control_flags(self):
        for key, flag in (("Shift_L", 1), ("Shift_R", 1), ("Control_L", 4)):
            self.v.xdown(key)
            deadline = time.time() + 5
            while self.v.mem(KEYSHF, KEYSHF)[0] != flag and time.time() < deadline:
                time.sleep(0.1)
            seen = self.v.mem(KEYSHF, KEYSHF)[0]
            self.v.xup(key)
            self.assertEqual(seen, flag, key)
            deadline = time.time() + 5
            while self.v.mem(KEYSHF, KEYSHF)[0] != 0 and time.time() < deadline:
                time.sleep(0.1)
        self.assertEqual(self.v.mem(KEYSHF, KEYSHF)[0], 0)

    def test_shifted_symbol(self):
        self.v.xtype("echo ")
        self.v.xkey("exclam", "Return")
        self.until(lambda l: "!" in l, what="the shifted symbol")

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
        # 'a' repeats while alone, then the newer key 's' takes over: a run of
        # a's followed by a run of s's, and nothing else on the screen can match
        self.until(lambda l: re.search(r"a+s+", "".join(l)), what="a run of a then s")

    def test_repeat(self):
        self.v.xtype("echo ")
        self.v.xdown("b")
        time.sleep(1.5)
        self.v.xup("b")
        self.v.xkey("Return")
        self.until(lambda l: "bbb" in "".join(l), what="repeated b")

    def test_run_stop_key(self):
        self.v.xtype("sleep 100\n")
        time.sleep(25)                  # the command loads from disk first, in real time
        self.v.xkey("Escape")           # VICE maps Escape to RUN/STOP
        self.v.wait_for("/ $", timeout=60, after="sleep 100")
        self.assertEqual(self.v.mem(0x0091, 0x0091)[0] & 0x80, 0x80)   # released again

    def test_jiffy_clock_runs(self):
        a = self.v.mem(JIFFY, JIFFY + 2)
        time.sleep(1)
        b = self.v.mem(JIFFY, JIFFY + 2)
        ja, jb = a[0] << 16 | a[1] << 8 | a[2], b[0] << 16 | b[1] << 8 | b[2]
        self.assertGreater(jb, ja)


if __name__ == "__main__":
    unittest.main()
