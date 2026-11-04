"""edit's at_end (src/bin/edit.s): Z set exactly when p - text == tlen, for every position of a
file that ends past a page boundary. The routine is taken from the source, assembled with ca65
and run under py65, so the test follows the code in the tree.

    python3 -m unittest discover -s tools -p 'test_edit_at_end.py'

EDIT_SRC=path overrides the source (used to check that the test fails on the old routine).
Skips when ca65/ld65 or py65 are missing.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get("EDIT_SRC", os.path.join(ROOT, "src", "bin", "edit.s"))
ORG = 0x0800
try:
    from py65.devices.mpu6502 import MPU
    from py65.memory import ObservableMemory
except ImportError:
    MPU = None
TOOLS = all(shutil.which(t) for t in ("ca65", "ld65"))
SKIP = "py65 not installed" if MPU is None else ("cc65 not installed" if not TOOLS else None)


def routine_source():
    lines = open(SRC).read().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("at_end:"))
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("status:"))
    body = [l for l in lines[start:end] if l.strip()]
    return "\n".join(body)


DRIVER = """
.export p, tlen, stop, at_end
.segment "CODE"
        jsr at_end
stop:   nop
{routine}
p:      .res 2
tlen:   .res 2
text = {text}
"""


def build(text, tmp):
    """Assemble the routine with `text` at a chosen address; return (code, labels)."""
    src = os.path.join(tmp, "driver-%04x.s" % text)
    with open(src, "w") as f:
        f.write(DRIVER.replace("{routine}", routine_source()).replace("{text}", "$%04X" % text))
    obj, bin_, lbl = (os.path.join(tmp, "driver-%04x.%s" % (text, e)) for e in ("o", "bin", "lbl"))
    subprocess.run(["ca65", src, "-o", obj], check=True)
    subprocess.run(["ld65", "-t", "none", "-S", hex(ORG), "-Ln", lbl, "-o", bin_, obj], check=True)
    sym = {}
    for line in open(lbl):
        m = re.match(r"al ([0-9A-F]+) \.(\w+)$", line.strip())
        if m:
            sym[m.group(2)] = int(m.group(1), 16)
    return open(bin_, "rb").read(), sym


def run_at_end(code, sym, p, tlen):
    mem = ObservableMemory()
    for i, b in enumerate(code):
        mem[ORG + i] = b
    mem[sym["p"]], mem[sym["p"] + 1] = p & 0xFF, p >> 8
    mem[sym["tlen"]], mem[sym["tlen"] + 1] = tlen & 0xFF, tlen >> 8
    cpu = MPU(memory=mem, pc=ORG)
    cpu.sp = 0xFF
    for _ in range(10000):
        if cpu.pc == sym["stop"]:
            return bool(cpu.p & 0x02)
        cpu.step()
    raise AssertionError("at_end did not return")


@unittest.skipIf(SKIP, SKIP)
class AtEnd(unittest.TestCase):
    def test_z_is_set_exactly_at_the_end_for_files_past_a_page(self):
        tmp = tempfile.mkdtemp()
        # the text buffer at several low bytes: the borrow between the two bytes depends on them
        for text in (0x0E00, 0x0E37, 0x0EFF, 0x0F80):
            code, sym = build(text, tmp)
            mismatches = []
            for tlen in range(0, 600):
                for delta in (-1, 0, 1):              # just before, at, and just past the end
                    got = run_at_end(code, sym, text + tlen + delta, tlen)
                    if got != (delta == 0):
                        mismatches.append((hex(text), tlen, delta, got))
            self.assertEqual(mismatches[:5], [], "at_end wrong: %d cases, first five (text, tlen, delta, Z)" % len(mismatches))


if __name__ == "__main__":
    unittest.main()
