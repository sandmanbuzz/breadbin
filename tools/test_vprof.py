"""Host tests for tools/vprof.py: the trace parser and the phase arithmetic (no emulator)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vprof  # noqa: E402

SAMPLE = (
    "(C:$c466) \n"
    "#1 (Trace  exec ed07)  105/$069,  28/$1c\n"
    ".C:ed07  EE 64 E6    INC $E664      - A:08 X:00 Y:00 SP:eb ..-....C  1000000\n"
    "#2 (Trace  exec c010)  238/$0ee,  29/$1d\n"
    ".C:c010  A9 00       LDA #$00       - A:08 X:00 Y:00 SP:eb ..-....C  1098525\n"
    "Executing: sw\nStopwatch:  1098525\n"
    "#1 (Trace  exec ed07)  298/$12a,  31/$1f\n"
    ".C:ed07  EE 64 E6    INC $E664      - A:08 X:00 Y:00 SP:eb ..-....C  1295575\n"
    "(C:$a3f0) "
)


class Parse(unittest.TestCase):
    def test_events(self):
        self.assertEqual(vprof.parse_trace(SAMPLE),
                         [(1000000, 0xed07), (1098525, 0xc010), (1295575, 0xed07)])

    def test_phases(self):
        ev = vprof.parse_trace(SAMPLE)
        r = vprof.phases(ev, {0xed07: "iec_read", 0xc010: "ft_good"}, "iec_read")
        self.assertEqual(r["anchors"], 2)
        by = {(p["from"], p["to"]): p for p in r["phases"]}
        # 98525 and 197050 cycles over 2 anchors, in ms
        self.assertAlmostEqual(by[("iec_read", "ft_good")]["ms_per_anchor"], 98525 / 985248 * 1000 / 2, 1)
        self.assertAlmostEqual(by[("ft_good", "iec_read")]["ms_per_anchor"], 197050 / 985248 * 1000 / 2, 1)
        # the phases cover the window exactly
        self.assertAlmostEqual(sum(p["ms_per_anchor"] for p in r["phases"]), r["window_ms_per_anchor"], 0)

    def test_empty(self):
        self.assertEqual(vprof.phases([], {}, "x")["phases"], [])

    def test_resolve_offset(self):
        a, n = vprof.resolve("iec_read+3", lambda m: 0)
        b, _ = vprof.resolve("iec_read", lambda m: 0)
        self.assertEqual((a, n), (b + 3, "iec_read+3"))


if __name__ == "__main__":
    unittest.main()
