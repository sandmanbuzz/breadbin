"""Cycle counts of the two JiffyDOS windows in src/kernel/iec.s, from the built kernel.

The protocol has no clock line: after the "go" edge each side reads or writes the two lines at
fixed times, so one instruction added inside a window breaks every transfer silently. This test
walks the machine code from the go store and checks the cycle (counted from the end of that
store) at which every later access to $DD00 ends, against the C64 column of the tables in
Michael Steil's "Commodore Peripheral Bus, Part 7: JiffyDOS". The windows are straight-line
code; a branch inside one fails the test. Skips when the kernel is not built or has JIFFY=0.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
PORT = 0xDD00

# opcode: (bytes, cycles, port access for an absolute operand). Only what the windows use;
# an opcode that is not here fails the test, which is the point.
OPS = {
    0x8E: (3, 4, "w"),   # stx abs
    0x8C: (3, 4, "w"),   # sty abs
    0x8F: (3, 4, "w"),   # sax abs (undocumented, stable)
    0xAD: (3, 4, "r"),   # lda abs
    0x4D: (3, 4, "r"),   # eor abs
    0x2C: (3, 4, "r"),   # bit abs
    0x24: (2, 3, None),  # bit zp
    0x4A: (1, 2, None),  # lsr a
    0xEA: (1, 2, None),  # nop
    0x09: (2, 2, None),  # ora #
    0x48: (1, 3, None),  # pha
    0x68: (1, 4, None),  # pla
}
JSR, RTS = 0x20, 0x60

RX = [("r", 16), ("r", 26), ("r", 37), ("r", 48), ("r", 59), ("w", 63)]
TX = [("w", 11), ("w", 24), ("w", 35), ("w", 48), ("w", 61), ("r", 80)]


def load():
    try:
        with open(os.path.join(BUILD, "kernel.lbl")) as f:
            lbl = {m.group(2): int(m.group(1), 16)
                   for m in (re.match(r"al ([0-9A-F]+) \.(\S+)$", ln.strip()) for ln in f) if m}
        with open(os.path.join(BUILD, "kernel.map")) as f:
            seg = re.search(r"^IECBUS\s+([0-9A-F]+)\s+([0-9A-F]+)\s+([0-9A-F]+)", f.read(), re.M)
        with open(os.path.join(BUILD, "breadbin.prg"), "rb") as f:
            prg = f.read()
    except OSError:
        return None, None
    if seg is None:
        return None, None
    # the segment runs at seg.start; its bytes follow the stub in the file
    stub_end = lbl.get("__IECBUS_LOAD__")
    return lbl, (prg, int(seg.group(1), 16), int(seg.group(3), 16), stub_end)


def trace(mem, pc, n):
    """Accesses to the port after the instruction at pc (the go store), as (kind, cycle)."""
    op = mem(pc)
    assert op in (0x8E, 0x8C) and mem(pc + 1) | mem(pc + 2) << 8 == PORT, "go is not a store to the port"
    pc += 3
    cyc, out, ret = 0, [], None
    while len(out) < n:
        op = mem(pc)
        if op == JSR and ret is None:           # jsr to a bare rts: 12 cycles
            target = mem(pc + 1) | mem(pc + 2) << 8
            assert mem(target) == RTS, "jsr inside a window to something that is not an rts"
            cyc += 12
            pc += 3
            continue
        assert op in OPS, f"opcode ${op:02X} at ${pc:04X} is not allowed inside a window"
        size, c, acc = OPS[op]
        cyc += c
        if size == 3:
            assert mem(pc + 1) | mem(pc + 2) << 8 == PORT or acc != "w", "a store to something else"
            if mem(pc + 1) | mem(pc + 2) << 8 == PORT:
                out.append((acc, cyc))
        pc += size
    return out


class Windows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lbl, img = load()
        if cls.lbl is None:
            raise unittest.SkipTest("kernel not built (make)")
        if "jif_rx_go" not in cls.lbl:
            raise unittest.SkipTest("kernel built with JIFFY=0")
        prg, run, size, _ = img
        base = cls.lbl["__IECBUS_LOAD__"] - (prg[0] | prg[1] << 8) + 2
        cls.mem = staticmethod(lambda a: prg[base + a - run])
        cls.end = run + size

    def test_receive(self):
        self.assertEqual(trace(self.mem, self.lbl["jif_rx_go"], len(RX)), RX)

    def test_send(self):
        self.assertEqual(trace(self.mem, self.lbl["jif_tx_go"], len(TX)), TX)

    def test_send_table(self):
        """jif_tab: low nibble -> bit 3 at CLK out, bit 1 at DATA out, bits 2 and 0 two above; bits 0-3 set."""
        t = self.lbl["jif_tab"]
        for n in range(16):
            v = self.mem(t + n)
            self.assertEqual(v & 0x0F, 0x0F)
            self.assertEqual(((v >> 4) & 1, (v >> 5) & 1, (v >> 6) & 1, (v >> 7) & 1),
                             ((n >> 3) & 1, (n >> 1) & 1, (n >> 2) & 1, n & 1))


if __name__ == "__main__":
    unittest.main()
