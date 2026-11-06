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
        """One scroll with a scripted $D012: values below $FB first, then $FB. The copy
        (first write to screen RAM) must come after the read that returned $FB, and the
        wait must not have ended on an earlier, lower read."""
        sim = Sim()
        sim.write(1, b"\x0c" + b"\n" * 24)                 # cursor on row 24: the next LF scrolls
        script = [0x0A, 0x64, 0xC8, 0xFA, 0xFB, 0xFC]
        events = []
        M = type(sim.mem)
        real_get, real_set = M.__getitem__, M.__setitem__

        def get(m, a):
            if a == 0xD012:
                v = script[min(len([e for e in events if e[0] == "r"]), len(script) - 1)]
                events.append(("r", v))
                return v
            return real_get(m, a)

        def put(m, a, v):
            if SCREEN <= a < SCREEN + 1000:
                events.append(("w", a))
            real_set(m, a, v)
        M.__getitem__, M.__setitem__ = get, put
        try:
            sim.write(1, b"\n")
        finally:
            M.__getitem__, M.__setitem__ = real_get, real_set
        kinds = [e[0] for e in events]
        first_w = kinds.index("w")
        reads_before = [e[1] for e in events[:first_w]]
        self.assertTrue(reads_before, "no $D012 read before the first screen write")
        self.assertEqual(reads_before, script[:5])         # polled up to the first $FB, no further
        self.assertNotIn("r", kinds[first_w:])


if __name__ == "__main__":
    unittest.main()
