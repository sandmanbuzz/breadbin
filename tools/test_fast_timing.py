"""Cycle counts of the two timed loops in src/mod/fast.s, from the built module.

The fast block transfer has no clock line. After the host's "go" edge the drive's d_send and
d_recv touch the serial port ($1800) at fixed cycles, and the host reads and writes at its own
fixed times. This test walks the drive code in build/mod/fast.0 from each loop's cmp (cycle 0 is
the cmp's last cycle, its read of the port) and checks the cycle at which every port access ends
against SK1..SK5 and RK1..RK5 below. It also checks the two 16-byte nibble tables against their
definitions, and the page layout. The timed ranges are straight-line code: a branch, jump or call
inside one fails the test. Skips when build/mod/fast.0 or its label file is not built.

FAST_SK and FAST_RK (comma-separated) replace the schedule for margin experiments, e.g.
  FAST_SK=6,17,28,38,49 python3 -m unittest tools/test_fast_timing.py   (must fail)
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "build", "mod")
SRC = os.path.join(ROOT, "src", "mod", "fast.s")
PB = 0x1800             # the drive's serial port (VIA 1 port B)
DRV = 0x0300            # where the drive code runs

# Write (send) and read (receive) cycles; they mirror SK1..SK5 and RK1..RK5 in src/mod/fast.s
# (RK5 is the one port write of d_recv). test_constants_mirror_source keeps them in step.
SK = [6, 17, 27, 38, 49]
RK = [13, 26, 37, 50, 62]

# opcode: (bytes, cycles, port access for an absolute operand). Only what the timed loops use;
# anything else fails the test, which is the point.
OPS = {
    0x8E: (3, 4, "w"),   # stx abs
    0x8D: (3, 4, "w"),   # sta abs
    0xAD: (3, 4, "r"),   # lda abs
    0x0D: (3, 4, "r"),   # ora abs
    0x1D: (3, 4, None),  # ora abs,x (the d_rtab lookup, not the port)
    0xA9: (2, 2, None),  # lda #
    0xA2: (2, 2, None),  # ldx #
    0x29: (2, 2, None),  # and #
    0x0A: (1, 2, None),  # asl a
    0xAA: (1, 2, None),  # tax
    0x24: (2, 3, None),  # bit zp (the 3-cycle filler)
    0xEA: (1, 2, None),  # nop
}
CMP_ABS, BEQ = 0xCD, 0xF0


def schedule(name, default):
    v = os.environ.get(name)
    if not v:
        return default
    return [int(x, 0) for x in v.split(",")]


def walk(mem, pc, end, cyc):
    """Port accesses in the straight-line code from pc up to end: (kind, cycle its last cycle ends on)."""
    out = []
    while pc < end:
        op = mem(pc)
        if op not in OPS:
            raise AssertionError(f"opcode ${op:02X} at ${pc:04X} is not in the cycle table "
                                 "(a branch, jump or call is not allowed in a timed range)")
        size, c, acc = OPS[op]
        cyc += c
        if size == 3 and (mem(pc + 1) | mem(pc + 2) << 8) == PB:
            assert acc is not None, f"unexpected use of the port at ${pc:04X}"
            out.append((acc, cyc))
        pc += size
    assert pc == end, f"the timed range ends at ${pc:04X}, not at ${end:04X}"
    return out


def load():
    try:
        with open(os.path.join(MOD, "fast.lbl")) as f:
            lbl = {m.group(2): int(m.group(1), 16)
                   for m in (re.match(r"al ([0-9A-Fa-f]+) \.(\S+)$", ln.strip()) for ln in f) if m}
        with open(os.path.join(MOD, "fast.0"), "rb") as f:
            img = f.read()
    except OSError:
        return None, None
    return lbl, img


class Timing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lbl, cls.img = load()
        if cls.lbl is None or "blob" not in cls.lbl:
            raise unittest.SkipTest("module not built (make)")

    def mem(self, a):
        """The drive byte at drive address a: the module image holds the code from label blob."""
        i = self.lbl["blob"] + a - DRV
        assert 0 <= i < len(self.img), f"drive ${a:04X} is outside the module image"
        return self.img[i]

    def table(self, name):
        return [self.mem(self.lbl[name] + n) for n in range(16)]

    def loop_body(self, loop):
        """Start of the straight-line code after the loop's cmp PB / beq (the beq is not taken)."""
        pc = self.lbl[loop]
        self.assertEqual(self.mem(pc), CMP_ABS, f"{loop} does not start with cmp abs")
        self.assertEqual(self.mem(pc + 1) | self.mem(pc + 2) << 8, PB, f"{loop} does not compare the port")
        self.assertEqual(self.mem(pc + 3), BEQ, f"{loop} has no beq after its cmp")
        rel = self.mem(pc + 4)
        self.assertEqual(pc + 5 + (rel - 256 if rel >= 128 else rel), pc, f"{loop}: the beq does not loop")
        return pc + 5           # the beq took its 2 cycles: cycle 2 is the first cycle after it

    def test_constants_mirror_source(self):
        with open(SRC) as f:
            src = dict(re.findall(r"^(SK\d|RK\d) = (\d+)", f.read(), re.M))
        for i, v in enumerate(SK, 1):
            self.assertEqual(int(src[f"SK{i}"]), v, f"SK{i} in fast.s")
        for i, v in enumerate(RK, 1):
            self.assertEqual(int(src[f"RK{i}"]), v, f"RK{i} in fast.s")

    def test_send_port_writes_at_their_cycles(self):
        sk = schedule("FAST_SK", SK)
        self.assertEqual(len(sk), 5, "FAST_SK needs five values")
        got = walk(self.mem, self.loop_body("d_sw"), self.lbl["d_send_end"], 2)
        self.assertEqual(got, [("w", c) for c in sk])

    def test_receive_port_accesses_at_their_cycles(self):
        rk = schedule("FAST_RK", RK)
        self.assertEqual(len(rk), 5, "FAST_RK needs five values")
        got = walk(self.mem, self.loop_body("d_rw"), self.lbl["d_recv_end"], 2)
        self.assertEqual(got, [("r", c) for c in rk[:4]] + [("w", rk[4])])

    def test_stab_matches_definition_and_semantics(self):
        got = self.table("d_stab")
        want = [((~n & 1) << 3) | (~n & 4) | (~n & 2) | ((~n & 8) >> 3) for n in range(16)]
        self.assertEqual(got, want)
        self.assertTrue(all(v <= 0x0F for v in got))
        for n in range(16):
            v = got[n]
            v1 = (v << 1) & 0x0F
            self.assertEqual((v >> 3) & 1, 1 - (n & 1), f"n={n}: CLK bit")
            self.assertEqual((v >> 1) & 1, 1 - ((n >> 1) & 1), f"n={n}: DATA bit")
            self.assertEqual((v1 >> 3) & 1, 1 - ((n >> 2) & 1), f"n={n}: CLK bit, next pair")
            self.assertEqual((v1 >> 1) & 1, 1 - ((n >> 3) & 1), f"n={n}: DATA bit, next pair")

    def test_rtab_matches_definition(self):
        want = [((n & 8) << 1) | ((n & 4) << 4) | ((n & 2) << 4) | ((n & 1) << 7) for n in range(16)]
        self.assertEqual(self.table("d_rtab"), want)

    def test_receive_nibbles_rebuild_every_byte(self):
        rtab = self.table("d_rtab")
        bit = lambda b, k: (b >> k) & 1
        for b in range(256):
            read1 = bit(b, 4) << 2 | bit(b, 5)
            read2 = bit(b, 6) << 2 | bit(b, 7)
            read3 = bit(b, 3) << 2 | bit(b, 1)
            read4 = bit(b, 2) << 2 | bit(b, 0)
            x = ((read1 << 1) | read2) & 0x0F
            lo = ((read3 << 1) | read4) & 0x0F
            self.assertEqual(lo | rtab[x], b, f"byte ${b:02X}")

    def test_layout(self):
        l = self.lbl
        self.assertEqual(l["d_send"], DRV)
        for lo, hi in (("d_sw", "d_send_end"), ("d_rw", "d_recv_end")):
            self.assertEqual(l[lo] >> 8, (l[hi] - 1) >> 8, f"{lo}..{hi} crosses a page")
        for t in ("d_stab", "d_rtab"):
            self.assertEqual(l[t] >> 8, (l[t] + 15) >> 8, f"{t} crosses a page")
        self.assertEqual((l["d_end"] - DRV) % 32, 0)
        self.assertLessEqual(l["d_end"] - DRV, 0x200)


if __name__ == "__main__":
    unittest.main()
