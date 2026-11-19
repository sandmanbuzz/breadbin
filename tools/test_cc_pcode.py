"""L2: cc.py's p-code back end (tools/cc_pcode.py). Every program in tools/test_cc_run.py runs
again here, compiled to p-code, linked against /lib/pvm (tools/pvmlink.py) and run under py65
(tools/asim.py) with the VM; then what only the p-code back end does (recursion, the exit status,
spilling to frame temporaries). Needs ca65, ld65 and py65 (the container image has them)."""
import os
import re
import tempfile
import unittest

import cc
import cc_pcode
import pvmlink
import test_cc_run
import test_pvm
from asim import run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAVE_TOOLS = test_pvm.HAVE_TOOLS


def build(src, d, fstack=cc_pcode.FSTACK):
    """The CX file for src, built in directory d."""
    s = os.path.join(d, "p.s")
    with open(s, "w") as f:
        f.write(cc_pcode.compile_pcode(src, fstack))
    pvmlink.sh("ca65", "-I", os.path.join(ROOT, "include"), "-I", os.path.join(ROOT, "src", "pvm"),
               "-o", os.path.join(d, "p.o"), s)
    return pvmlink.link_prog(os.path.join(d, "p.cx"), test_pvm.lib_dir(), [os.path.join(d, "p.o")])


def run_full(src, fstack=cc_pcode.FSTACK):
    with tempfile.TemporaryDirectory(prefix="ccp-") as d:
        path = build(src, d, fstack)
        r = run("p", [], path=path, libs={pvmlink.LIBPATH: os.path.join(test_pvm.lib_dir(), "pvm")})
        r.size = os.path.getsize(path)
    return r


def run_pcode(src, steps=None):
    """What test_cc_run's run_c gives: the bytes written. The program must exit 0 (every one
    there returns 0 from main; a VM trap exits 12)."""
    r = run_full(src)
    if r.exit != 0:
        raise AssertionError(f"exit status {r.exit}, output {r.out!r}")
    return r.out


# every class of programs in test_cc_run, on this back end
for _name, _cls in vars(test_cc_run).items():
    if isinstance(_cls, type) and issubclass(_cls, test_cc_run.Case) and _cls is not test_cc_run.Case:
        globals()["P" + _name] = unittest.skipUnless(HAVE_TOOLS, "needs ca65, ld65 and py65")(
            type("P" + _name, (_cls,), {"run_c": staticmethod(run_pcode), "__module__": __name__}))


class Abi(unittest.TestCase):
    def test_eval_stack_addresses_agree_with_the_vm(self):
        vm = open(os.path.join(ROOT, "src", "pvm", "pvm.s")).read()
        inc = open(os.path.join(ROOT, "src", "pvm", "pvm.inc")).read()
        esh = int(re.search(r"^ESTKH\s*=\s*\$([0-9A-F]+)", vm, re.M).group(1), 16)
        depth = int(re.search(r"^ESDEPTH\s*=\s*(\d+)", vm, re.M).group(1))
        self.assertIn("ESTKL   = ESTKH + ESDEPTH", vm)
        self.assertEqual(int(re.search(r"^P_ESTKH\s*=\s*\$([0-9A-F]+)", inc, re.M).group(1), 16), esh)
        self.assertEqual(int(re.search(r"^P_ESTKL\s*=\s*\$([0-9A-F]+)", inc, re.M).group(1), 16), esh + depth)


class Refused(unittest.TestCase):
    def fails(self, src, msg):
        with self.assertRaises(cc.CompileError) as cm:
            cc_pcode.compile_pcode(src)
        self.assertIn(msg, str(cm.exception))

    def test_a_frame_past_255_bytes(self):
        self.fails("int main() { char a[200]; char b[60]; return 0; }", "the limit is 255")

    def test_more_than_eight_arguments(self):
        params = ", ".join("int a%d" % i for i in range(9))
        self.fails("int f(%s) { return 0; }\nint main() { return f(1,2,3,4,5,6,7,8,9); }" % params,
                   "at most 8 fit")

    def test_the_type_rules_are_the_native_ones(self):
        self.fails("int main() { int *p; int x; x = p; return 0; }", "a pointer where a number is needed")

    def test_a_body_that_never_runs_is_still_checked(self):
        self.fails("int main() { while (0) { nothere(); } return 0; }", "nothere")
        self.fails("int main() { while (0) { int *p; int x; x = p; } return 0; }",
                   "a pointer where a number is needed")


@unittest.skipUnless(HAVE_TOOLS, "needs ca65, ld65 and py65")
class PCodeOnly(unittest.TestCase):
    def check(self, src, want=b"Y", status=0):
        r = run_full(src)
        self.assertEqual((r.out, r.exit), (want, status), src)
        return r

    def test_recursion(self):
        self.check("int fact(int n) { if (n == 0) return 1; return n * fact(n - 1); }\n"
                   "int fib(int n) { if (n < 2) return n; return fib(n - 1) + fib(n - 2); }\n"
                   'int main() { if (fact(7) == 5040) if (fib(15) == 610) puts("Y"); return 0; }')

    def test_mutual_recursion(self):
        self.check("int even(int n) { if (n == 0) return 1; return odd(n - 1); }\n"
                   "int odd(int n) { if (n == 0) return 0; return even(n - 1); }\n"
                   'int main() { if (even(40)) if (odd(41)) if (even(41) == 0) puts("Y"); return 0; }')

    def test_each_call_has_its_own_locals(self):
        # a local array and a char local per level: the native back end's statics would be shared
        self.check("int f(int n) { int a[3]; char c; a[1] = n; c = n + 1; if (n) f(n - 1);\n"
                   "  if (a[1] != n) return 1; if (c != n + 1) return 1; if (n) return f(n - 1); return 0; }\n"
                   'int main() { if (f(6) == 0) puts("Y"); return 0; }')

    def test_pending_values_survive_a_call(self):
        self.check("int g(int x) { return x + 1; }\n"
                   'int main() { if (1 + (2 + (3 + (4 + (5 + (6 + (7 + g(8))))))) == 37) puts("Y"); return 0; }')

    def test_deep_recursion_exits_with_enomem(self):
        self.check("int f(int n) { return f(n + 1) + 1; }\nint main() { f(0); puts(\"N\"); return 0; }",
                   b"", 12)

    def test_main_returns_the_exit_status(self):
        self.check('int main() { puts("Y"); return 300; }', b"Y", 44)

    def test_spilled_operands_keep_their_order(self):
        # the right sides need more than the eval stack has above the pending left values
        deep = "(1+" * 9 + "1" + ")" * 9            # 10
        self.check('int main() { if (100 - %s == 90) if (%s - 100 == 65446) if (55 / %s == 5) '
                   'if (%s < 11) puts("Y"); return 0; }' % (deep, deep, deep, deep))

    def test_calls_whose_arguments_do_not_fit(self):
        deep = "(1+" * 9 + "1" + ")" * 9
        self.check("int f(int a, int b, int c, int d, int e, int g, int h, int i) "
                   "{ return a - b + c - d + e - g + h - i; }\n"
                   "int main() { if (f(%s, 1, 2, 3, 4, 5, 6, %s) == 3) puts(\"Y\"); return 0; }"
                   % (deep, deep))

    def test_a_store_whose_address_does_not_fit(self):
        deep = "(1+" * 9 + "1" + ")" * 9
        self.check('int main() { int a[12]; a[%s - 1] = 7; if (a[9] == 7) puts("Y"); return 0; }' % deep)

    def test_comparison_values_are_one_and_zero(self):
        self.check('int main() { if ((3 == 3) + (3 != 4) + (1 < 2) + (2 > 1) + (2 <= 2) + (2 >= 3) == 5) '
                   'puts("Y"); return 0; }')

    def test_unsigned_comparisons_at_the_sign_boundary(self):
        self.check('int main() { int a = 32768; int b = 32767; if (a > b) if (b < a) if (a >= b) '
                   'if (b <= a) if (65535 / 32768 == 1) if (65535 / 65535 == 1) if (40000 / 300 == 133) '
                   'puts("Y"); return 0; }')

    def test_fused_operands_every_kind(self):
        # x + v and a[v] carry v in the op (ADDLW ADDLB ADDAW ADDAB, IDXLW IDXLB IDXAW IDXAB,
        # ADDI SUBI): locals and globals, int and char, scaled and not
        self.check("int g = 3; char gc = 2; int ga[6]; char gs[6];\n"
                       "int main() { int *p; char *q; int i = 4; char c = 1;\n"
                       "  ga[g] = 30; ga[gc] = 20; gs[g] = 7; gs[gc] = 8; ga[i] = 40; ga[c] = 10; gs[i] = 9; gs[c] = 6;\n"
                       "  p = ga + 5; q = gs + 5; p = p - 2; q = q - 3;\n"
                       "  if (*p == 30) if (*q == 8) if (ga[2] + ga[1] + ga[4] == 70) if (gs[3] + gs[4] + gs[1] == 22)\n"
                       "  if (i + g + gc + c == 10) if (300 + gc == 302) if (i - 5 == 65535) if (c + 127 == 128)\n"
                       "  if (*(ga + i) == 40) if (*(gs + c) == 6) puts(\"Y\"); return 0; }")

    def test_straight_line_past_the_ip_window(self):
        # 1,200 bytes with no branch or call: the compiler inserts renormalising branches
        body = "".join("  n = n + %d;\n" % (i % 7) for i in range(200))
        self.check("int main() { int n = 0;\n%s  if (n == %d) puts(\"Y\"); return 0; }"
                   % (body, sum(i % 7 for i in range(200))))

    def test_while_zero_never_runs(self):
        self.check('int main() { int n = 0; while (0) { n = 1; } if (n == 0) puts("Y"); return 0; }')

    def test_smallest_program_is_small(self):
        r = self.check('int main() { puts("Y"); return 0; }')
        self.assertLess(r.size, 1400)       # 1 KB of it is the frame stack's BSS, not in the file


if __name__ == "__main__":
    unittest.main()
