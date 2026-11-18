"""The kernel's 1541 geometry (blk_to_ts, ts_block in src/kernel/blk.s) under py65.

Every block of a 1541 disk maps to its track and sector and back; blocks past 682 stay on
track 35 with sector = block - 666 (format's 1541/1581 probe relies on 700 -> 35/34 and
720 -> 35/54, sectors no drive has). Skips when py65 is missing or the kernel is not built.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import uci_sim
    from uci_sim import Sim
except ImportError:
    uci_sim = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
BUILT = all(os.path.exists(os.path.join(BUILD, f)) for f in ("breadbin.prg", "kernel.lbl", "breadbin.d64"))
SKIP = "py65 not installed" if uci_sim is None else ("kernel not built (make)" if not BUILT else None)


def spt(track):
    return 21 if track <= 17 else 19 if track <= 24 else 18 if track <= 30 else 17


def first_block(track):
    return sum(spt(t) for t in range(1, track))


def model_ts(blk):
    t = 1
    while t < 35 and blk >= spt(t):
        blk -= spt(t)
        t += 1
    return t, blk


@unittest.skipIf(SKIP, SKIP)
class Geometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Sim(None)

    def test_blocks_to_track_and_sector(self):
        s, L = self.s, self.s.lbl
        m = s.mem.b
        for blk in range(0, 666 + 256):              # the sector must still fit a byte
            m[L["rq_lo"]], m[L["rq_hi"]] = blk & 0xFF, blk >> 8
            s.call("blk_to_ts")
            self.assertEqual((m[L["trk"]], m[L["sct"]]), model_ts(blk), f"block {blk}")
        m[L["rq_lo"]], m[L["rq_hi"]] = 700 & 0xFF, 700 >> 8
        s.call("blk_to_ts")
        self.assertEqual((m[L["trk"]], m[L["sct"]]), (35, 34))
        m[L["rq_lo"]], m[L["rq_hi"]] = 720 & 0xFF, 720 >> 8
        s.call("blk_to_ts")
        self.assertEqual((m[L["trk"]], m[L["sct"]]), (35, 54))

    def test_track_and_sector_to_block(self):
        for t in range(1, 36):
            for sec in range(spt(t)):
                _, _, x, y = self.s.call("ts_block", a=t, x=sec)
                self.assertEqual(x | y << 8, first_block(t) + sec, f"{t}/{sec}")


if __name__ == "__main__":
    unittest.main()
