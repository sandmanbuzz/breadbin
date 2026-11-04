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
        pairs = [(0, 0), (0, 1), (1, 0), (5, 5), (0x7FFF, 0x8000), (0x8000, 0x7FFF), (0xFFFF, 1), (1, 0xFFFF),
                 (0x0100, 0x0000), (0x0001, 0x0101)]   # equal low bytes, unequal high bytes
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


@unittest.skipUnless(HAVE_TOOLS, "needs ca65, ld65 and py65")
class ExecutedSlice2(unittest.TestCase):
    def check(self, src, want=b"Y"):
        self.assertEqual(run_c(src), want, src)

    def test_char_is_zero_extended_and_keeps_the_low_byte(self):
        self.check('int main() { char c = 321; if (c == 65) puts("Y"); else puts("N"); return 0; }')

    def test_char_arithmetic_promotes(self):
        self.check('int main() { char c = 200; char d = 100; if (c + d == 300) puts("Y"); else puts("N"); return 0; }')

    def test_parameters_are_passed_in_order(self):
        self.check("int sub(int a, int b) { return a - b; }\n"
                   'int main() { if (sub(10, 3) == 7) puts("Y"); else puts("N"); return 0; }')

    def test_nested_calls_with_arguments(self):
        self.check("int add(int a, int b) { return a + b; }\n"
                   'int main() { if (add(add(1, 2), add(3, 4)) == 10) puts("Y"); else puts("N"); return 0; }')

    def test_a_char_parameter_keeps_the_low_byte(self):
        self.check("int lo(char c) { return c; }\n"
                   'int main() { if (lo(321) == 65) puts("Y"); else puts("N"); return 0; }')

    def test_for_counts(self):
        self.check('int main() { int i; int s = 0; for (i = 0; i < 5; i = i + 1) s = s + i; '
                   'if (s == 10) puts("Y"); else puts("N"); return 0; }')

    def test_pointer_reads_and_writes_an_int(self):
        self.check('int main() { int x = 5; int *p; p = &x; *p = 9; '
                   'if (x == 9) puts("Y"); else puts("N"); return 0; }')

    def test_pointer_reads_a_char(self):
        self.check('int main() { char c = 7; char *q; q = &c; *q = 8; '
                   'if (c == 8) puts("Y"); else puts("N"); return 0; }')

    def test_array_stores_and_loads_ints(self):
        self.check('int main() { int a[5]; int i; for (i = 0; i < 5; i = i + 1) a[i] = i + 1; '
                   'if (a[0] + a[4] == 6) puts("Y"); else puts("N"); return 0; }')

    def test_parameters_are_not_swapped(self):
        # a program that always printed Y would pass the tests above; this one must print N
        self.check("int sub(int a, int b) { return a - b; }\n"
                   'int main() { if (sub(3, 10) == 7) puts("Y"); else puts("N"); return 0; }', b"N")

    def test_array_elements_are_two_bytes_apart(self):
        self.check('int main() { int a[4]; int *p; a[2] = 77; p = a; '
                   'if (*(p + 2) == 77) puts("Y"); else puts("N"); return 0; }')

    def test_char_array_is_one_byte_apart(self):
        self.check('int main() { char s[4]; char *p; s[0] = 1; s[1] = 2; s[2] = 3; p = s; '
                   'if (*(p + 2) == 3) puts("Y"); else puts("N"); return 0; }')

    def test_an_array_is_passed_as_a_pointer(self):
        self.check("int sum3(int *p) { return p[0] + p[1] + p[2]; }\n"
                   'int main() { int a[3]; a[0] = 1; a[1] = 2; a[2] = 3; '
                   'if (sum3(a) == 6) puts("Y"); else puts("N"); return 0; }')

    def test_pointer_arithmetic_scales_by_the_element(self):
        self.check('int main() { int a[3]; int *p; a[1] = 5; p = a + 1; '
                   'if (*p == 5) puts("Y"); else puts("N"); return 0; }')


@unittest.skipUnless(HAVE_TOOLS, "needs ca65, ld65 and py65")
class ExecutedSlice3(unittest.TestCase):
    def check(self, src, want=b"Y"):
        self.assertEqual(run_c(src), want, src)

    def test_a_global_is_shared_by_functions(self):
        self.check("int g = 5;\nint bump() { g = g + 1; return 0; }\n"
                   'int main() { bump(); if (g == 6) puts("Y"); else puts("N"); return 0; }')

    def test_a_local_shadows_a_global(self):
        self.check("int g = 5;\n"
                   'int main() { int g = 2; if (g == 2) puts("Y"); else puts("N"); return 0; }')

    def test_a_global_char_array_takes_a_string(self):
        self.check('char msg[] = "abc";\nint main() { if (msg[1] == 98) puts("Y"); else puts("N"); return 0; }')

    def test_a_local_char_array_takes_a_string_each_call(self):
        self.check('int f() { char s[] = "hi"; s[0] = s[0] + 1; return s[0]; }\n'
                   'int main() { f(); if (f() == 105) puts("Y"); else puts("N"); return 0; }')

    def test_a_char_pointer_points_at_a_string_literal(self):
        self.check('int main() { char *p = "xyz"; if (*(p + 1) == 121) puts("Y"); else puts("N"); return 0; }')

    def test_a_string_literal_can_be_assigned_to_a_char_pointer(self):
        self.check('int main() { char *p; p = "ab"; if (*p == 97) puts("Y"); else puts("N"); return 0; }')

    def test_multiplication_wraps_at_16_bits(self):
        self.check('int main() { if (300 * 300 == 24464) puts("Y"); else puts("N"); return 0; }')

    def test_multiplication_and_division(self):
        self.check('int main() { if (7 * 6 == 42) if (42 / 6 == 7) if (7 / 2 == 3) puts("Y"); '
                   'else puts("N"); else puts("N"); else puts("N"); return 0; }')

    def test_division_of_a_large_number(self):
        self.check('int main() { if (65535 / 3 == 21845) puts("Y"); else puts("N"); return 0; }')

    def test_precedence_of_the_multiplicative_level(self):
        self.check('int main() { if (2 + 3 * 4 == 14) if ((2 + 3) * 4 == 20) if (20 / 4 / 5 == 1) puts("Y"); '
                   'else puts("N"); else puts("N"); else puts("N"); return 0; }')

    def test_division_by_zero_gives_65535(self):
        self.check('int main() { int z = 0; if (9 / z == 65535) puts("Y"); else puts("N"); return 0; }')

    def test_a_multiplication_in_a_loop_and_a_global(self):
        self.check("int acc = 1;\n"
                   'int main() { int i; for (i = 1; i < 6; i = i + 1) acc = acc * i; '
                   'if (acc == 120) puts("Y"); else puts("N"); return 0; }')


if __name__ == "__main__":
    unittest.main()
