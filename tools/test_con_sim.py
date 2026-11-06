"""The console scroll, run on the real kernel image in py65 (tools/uci_sim.py): no emulator, no
interrupts, no beam. A flood of distinct lines must leave exactly the last 24 lines on rows 0-23
and the cursor row blank. The first scr_scroll interleaved three copy streams and doubled the
rows at the page boundaries of screen RAM (rows 5-6, 11-12, 18-19).

    python -m unittest tools.test_con_sim -v     (needs py65 and a built build/breadbin.prg)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import py65  # noqa: F401
    from uci_sim import Sim, BUILD
    HAVE = os.path.exists(os.path.join(BUILD, "breadbin.prg"))
except ImportError:
    HAVE = False

SCREEN = 0x0400


def text(codes):
    out = ""
    for c in codes:
        c &= 0x7F
        out += chr(c + 96) if 1 <= c <= 26 else chr(c)
    return out.rstrip()


@unittest.skipUnless(HAVE, "needs py65 and a built kernel image")
class Scroll(unittest.TestCase):
    def rows(self, sim):
        raw = sim.mem.b[SCREEN:SCREEN + 1000]
        return [text(raw[i * 40:(i + 1) * 40]) for i in range(25)]

    def test_flood_keeps_every_row(self):
        sim = Sim()
        sim.write(1, b"\x0c")                               # clear
        lines = ["line %02d %s" % (i, "abcdefghijklmnopqrstuvwxyz"[i % 26] * (i * 7 % 29))
                 for i in range(100)]
        for l in lines:
            sim.write(1, (l + "\n").encode())               # the last write leaves the cursor on row 24
        rows = self.rows(sim)
        self.assertEqual(rows[:24], [l.rstrip() for l in lines[-24:]])
        self.assertEqual(rows[24], "")

    def test_scroll_waits_for_the_raster(self):
        sim = Sim()
        sim.write(1, b"\x0c")
        reads = []
        real = type(sim.mem).__getitem__

        def spy(m, a):
            if a == 0xD012:
                reads.append(1)
            return real(m, a)
        type(sim.mem).__getitem__ = spy
        try:
            for i in range(30):
                sim.write(1, b"x\n")
        finally:
            type(sim.mem).__getitem__ = real
        self.assertGreater(len(reads), 5)                   # the six scrolls polled $D012


if __name__ == "__main__":
    unittest.main()
