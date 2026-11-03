"""S14 executed on a 6502 simulator: cc.py output is assembled with ca65/ld65 (stand-ins for the
system calls), run in py65, and the bytes written by sys_write are checked. Needs ca65, ld65 and
py65 (the container image has them; the host test run skips without them)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cc  # noqa: E402

try:
    from py65.devices.mpu6502 import MPU
except ImportError:
    MPU = None

HAVE_TOOLS = bool(shutil.which("ca65") and shutil.which("ld65") and MPU)

# stand-ins for the system calls: sys_write appends the byte at r0 to $0400, sys_exit is a BRK
HEADER = """\
        .segment "CODE"
r0 = $f0
r1 = $f2
cc_ptr = $2b
"""
# the program starts at the origin, so the stand-ins for the system calls follow it
STUBS = """\
sys_exit:
        brk
sys_write:
        ldy #0
        lda (r0),y
        ldy $fe
        sta $0400,y
        inc $fe
        rts
"""
CFG = """\
MEMORY { RAM: start = $0800, size = $7000, file = %O; }
SEGMENTS { CODE: load = RAM, type = ro, start = $0800; }
"""
ORG = 0x0800
OUT = 0x0400


def run_c(src, steps=3000000):
    """Compile src, run it, return the bytes it wrote with sys_write."""
    asm = cc.compile_c(src)
    with tempfile.TemporaryDirectory(prefix="cc-run-") as d:
        def path(name):
            return os.path.join(d, name)
        asm = "".join(l + "\n" for l in asm.split("\n") if not l.startswith("cc_ptr = "))
        with open(path("prog.s"), "w", encoding="ascii") as f:
            f.write(HEADER + asm + STUBS)
        with open(path("prog.cfg"), "w") as f:
            f.write(CFG)
        subprocess.run(["ca65", "-o", path("prog.o"), path("prog.s")], check=True, capture_output=True)
        subprocess.run(["ld65", "-C", path("prog.cfg"), "-o", path("prog.bin"), path("prog.o")],
                       check=True, capture_output=True)
        with open(path("prog.bin"), "rb") as f:
            image = f.read()
    mpu = MPU()
    mem = mpu.memory
    for i, b in enumerate(image):
        mem[ORG + i] = b
    mpu.pc = ORG
    mem[0x00fe] = 0
    for _ in range(steps):
        if mem[mpu.pc] == 0x00:            # BRK: sys_exit reached
            break
        mpu.step()
    else:
        raise AssertionError("program did not reach sys_exit")
    return bytes(mem[OUT:OUT + mem[0x00fe]])


def unsigned_ops(a, b):
    return {"==": a == b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}


@unittest.skipUnless(HAVE_TOOLS, "needs ca65, ld65 and py65")
class Executed(unittest.TestCase):
    def test_hello(self):
        src = 'int main() { puts("hello, world!\\n"); return 0; }'
        self.assertEqual(run_c(src), b"hello, world!\n")

    def test_operator_grid_unsigned(self):
        pairs = [(0, 0), (0, 1), (1, 0), (5, 5), (0x7FFF, 0x8000), (0x8000, 0x7FFF), (0xFFFF, 1), (1, 0xFFFF)]
        for a, b in pairs:
            for op in ["==", "!=", "<", ">", "<=", ">="]:
                src = ('int main() { int a = %d; int b = %d; if (a %s b) puts("Y"); else puts("N"); '
                       'return 0; }') % (a, b, op)
                want = b"Y" if unsigned_ops(a, b)[op] else b"N"
                self.assertEqual(run_c(src), want, (a, op, b))

    def test_arithmetic_wraps_at_16_bits(self):
        cases = [("1 + 2", 3), ("7 - 9", 0xFFFE), ("0 - 1", 0xFFFF), ("0xFFFF + 1", 0),
                 ("0 - (5 - 2)", 0xFFFD), ("-5 + 9", 4), ("-(3)", 0xFFFD)]
        for expr, value in cases:
            src = 'int main() { if (%s == %d) puts("Y"); else puts("N"); return 0; }' % (expr, value)
            self.assertEqual(run_c(src), b"Y", expr)

    def test_functions_return_values_through_calls(self):
        src = ("int g() { return 40; }\n"
               "int f() { return g() + 2; }\n"
               "int main() { if (f() == 42) puts(\"Y\"); else puts(\"N\"); return 0; }\n")
        self.assertEqual(run_c(src), b"Y")

    def test_long_string_prints_all_of_it(self):
        text = "the quick brown fox jumps over the lazy dog, twice over and over again\\n"
        want = text.replace("\\n", "\n").encode("latin-1")
        self.assertEqual(run_c('int main() { puts("%s"); return 0; }' % text), want)

    def test_long_loop_body_runs(self):
        body = "".join("    n = n + %d;\n" % (i % 7) for i in range(60))
        src = "int main() { int n = 0; int i = 0; while (i < 3) {\n%s    i = i + 1; }\n" % body
        src += "if (n == %d) puts(\"Y\"); else puts(\"N\"); return 0; }\n" % (3 * sum(i % 7 for i in range(60)))
        self.assertEqual(run_c(src), b"Y")

    def test_deep_expression_within_the_stack(self):
        expr = "1+(" * 30 + "1" + ")" * 30          # 31 values pushed at once: the limit
        src = 'int main() { if (%s == 31) puts("Y"); else puts("N"); return 0; }' % expr
        self.assertEqual(run_c(src), b"Y")


if __name__ == "__main__":
    unittest.main()
