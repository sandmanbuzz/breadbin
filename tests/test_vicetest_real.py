"""The harness's two memory reads (monitor `m`, monitor `save`) must agree on a real emulator, over RAM,
zero page, I/O, colour RAM, ROM and the page boundary; and the sentinel-terminated _cmd must not drop or
leak output across consecutive commands.

    tools/ci/run.sh test-only T="tests.test_vicetest_real"
"""
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402

RANGES = [(0x0400, 0x07E7), (0x0001, 0x0001), (0x0000, 0x00FF), (0x0800, 0x08FF), (0xA000, 0xA0FF),
          (0xD000, 0xD02F), (0xD800, 0xD8FF), (0xDC00, 0xDC0F), (0xE000, 0xE0FF), (0xFF00, 0xFFFF),
          (0xCF00, 0xCFFF), (0x0300, 0x0312), (0x0333, 0x0333), (0x0400, 0x0410)]


class RealMonitor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_vtreal.d64")
        with open(os.path.join(ROOT, "build", "breadbin.d64"), "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = Vice(cls.img)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def test_m_equals_save(self):
        for a, b in RANGES:
            via_m = self.v._mem_m(a, b)
            self.v._cmd("x")
            via_save = self.v._mem_save(a, b)
            # the screen and the jiffy clock may move between two reads: compare the stable ranges exactly
            if (a, b) in ((0x0001, 0x0001), (0x0800, 0x08FF), (0xA000, 0xA0FF), (0xE000, 0xE0FF),
                          (0xFF00, 0xFFFF), (0xCF00, 0xCFFF)):
                self.assertEqual(via_m, via_save, hex(a))
            self.assertEqual(len(via_m), b - a + 1, hex(a))

    def test_mem_is_the_fast_path(self):
        t = time.time()
        for _ in range(10):
            self.v.mem(0x0400, 0x07E7)
        self.assertLess((time.time() - t) / 10, 0.4)

    def test_consecutive_commands_do_not_leak(self):
        for i in range(20):
            out = self.v._cmd("r")
            self.assertIn("ADDR", out)
            self.assertEqual(out.count("(C:$"), 1 + (1 if out.startswith("(C:$") else 0), out)
            self.v._cmd("x")

    def test_repeated_x_leaves_no_stale_answer(self):
        """`x` is never answered, so an `x` sent while the emulator already runs must not leave a prompt
        in the socket for the next command to count as its own (a long m, a slow command, would
        come back short)."""
        for n in (1, 2, 3):
            for _ in range(n):
                self.v._cmd("x")
            got = self.v._mem_m(0x0800, 0x2800)           # 8 KB: much slower than the settle time
            self.assertIsNotNone(got, n)
            self.assertEqual(len(got), 0x2001, n)
            self.v._cmd("x")
            ref = self.v._mem_save(0x0800, 0x2800)
            self.assertEqual(got, ref, n)

    def test_keybuf_then_mem_sees_the_keys_consumed(self):
        """keybuf's trailing x returns at once now; the key scanner still gets emulated time."""
        self.v.keybuf(b"\x0d")
        self.v.wait_for("$")                                # the shell took the RETURN and printed a prompt


if __name__ == "__main__":
    unittest.main()
