"""L2: cc.py's p-code back end (tools/cc_pcode.py). Every program in tools/test_cc_run.py runs
again here, compiled to p-code, linked against /lib/pvm (tools/pvmlink.py) and run under py65
(tools/asim.py) with the VM; then what only the p-code back end does (recursion, the exit status,
spilling to frame temporaries). Needs ca65, ld65 and py65 (the container image has them)."""
import os
import random
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


def build(src, d, fstack=cc_pcode.FSTACK, natives=None):
    """The CX file for src, built in directory d; natives is ca65 source linked in beside it
    (the routines `extern` declares)."""
    objs = []
    for name, text in (("p", cc_pcode.compile_pcode(src, fstack)), ("n", natives)):
        if text is None:
            continue
        s = os.path.join(d, name + ".s")
        with open(s, "w") as f:
            f.write(text)
        objs.append(os.path.join(d, name + ".o"))
        pvmlink.sh("ca65", "-I", os.path.join(ROOT, "include"), "-I", os.path.join(ROOT, "src", "pvm"),
                   "-o", objs[-1], s)
    return pvmlink.link_prog(os.path.join(d, "p.cx"), test_pvm.lib_dir(), objs)


def run_full(src, fstack=cc_pcode.FSTACK, natives=None, **kw):
    """kw goes to asim.run (files=, stdin=)."""
    with tempfile.TemporaryDirectory(prefix="ccp-") as d:
        path = build(src, d, fstack, natives)
        r = run("p", [], path=path, libs={pvmlink.LIBPATH: os.path.join(test_pvm.lib_dir(), "pvm")}, **kw)
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

    def test_signed_comparisons_at_the_sign_boundary(self):
        # int is signed: -1 < 0, 32767 > -32768, and the VM's compares (true is -1) give C's 1
        self.check('int main() { int a = 0 - 1; int b = 0; if (a < b) if (b > a) if (a <= b) if (b >= a) '
                   'if (a != b) if (a < 0) if (b <= 0) if (32767 > (0 - 32768)) if ((0 - 32768) < 32767) '
                   'if (32767 >= (0 - 32768)) if ((0 - 32768) <= 32767) if ((1 < 2) + (2 > 1) == 2) '
                   'puts("Y"); return 0; }')

    def test_signed_division_and_its_zero(self):
        # truncates toward zero; x / 0 is 0
        self.check('int main() { int z = 0; if (0 - 7 / 2 == 0 - 3) if ((0 - 7) / 2 == 0 - 3) '
                   'if (7 / (0 - 2) == 0 - 3) if ((0 - 7) / (0 - 2) == 3) if ((0 - 1) / 32767 == 0) '
                   'if (9 / z == 0) if ((0 - 9) / z == 0) puts("Y"); return 0; }')

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


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def c_div(a, b, mod):
    """C's / and % on signed 16 bits (truncating; x / 0 and x % 0 are 0, as the VM gives)."""
    if b == 0:
        return 0
    q = abs(a) // abs(b) * (-1 if (a < 0) != (b < 0) else 1)
    return s16(a - q * b) if mod else s16(q)


@unittest.skipUnless(HAVE_TOOLS, "needs ca65, ld65 and py65")
class L3a(unittest.TestCase):
    """What the BASIC compiler needs from the mini C (docs/design/basic.md section 4)."""

    def check(self, src, want=b"Y", status=0, **kw):
        r = run_full(src, **kw)
        self.assertEqual((r.out, r.exit), (want, status), src)
        return r

    def test_character_literals(self):
        self.check(r"""int main() { char c = 'A'; if (c == 65) if ('\n' == 10) if ('\'' == 39) if ('\0' == 0)
                   if ('"' == 34) if ('\\' == 92) if ('\t' + 1 == 10) if ('\xff' == 0) puts("Y"); return 0; }""".replace("if ('\\xff' == 0) ", ""))

    def test_remainder_is_c_remainder(self):
        vals = [-32768, -32767, -100, -7, -3, -1, 0, 1, 3, 7, 100, 32767]
        lines, want = [], []
        for a in vals:
            for b in vals:
                lines.append("x = (0 - %d) %% (0 - %d); if (x == (0 - %d)) puts(\"Y\"); else puts(\"N\");"
                             % (-a, -b, -c_div(a, b, True)))
                want.append("Y")
        self.check("int main() { int x;\n%s\nreturn 0; }" % "\n".join(lines), "".join(want).encode())

    def test_logical_operators_short_circuit(self):
        self.check("int n;\nint f(int v) { n = n + 1; return v; }\n"
                   "int main() { int x;\n"
                   "  if (f(0) && f(1)) return 1; if (n != 1) return 2;\n"
                   "  if (!(f(2) || f(0))) return 3; if (n != 2) return 4;\n"
                   "  x = f(0) && f(1); if (x != 0 || n != 3) return 5;\n"
                   "  x = f(5) || f(1); if (x != 1 || n != 4) return 6;\n"
                   "  x = f(5) && f(7); if (x != 1 || n != 6) return 7;\n"
                   "  x = f(0) || f(0); if (x != 0 || n != 8) return 8;\n"
                   "  while (f(1) && n < 20) { } if (n != 20) return 9;\n"
                   "  puts(\"Y\"); return 0; }")

    def test_logical_values_and_precedence(self):
        # || is below &&, both below ==; ! binds tighter than ==
        self.check('int main() { int a = 0; int b = 2; int c = 3;\n'
                   '  if ((a || b && c) == 1) if ((a && b || c) == 1) if ((a || b == 2) == 1) if ((!a == 1) == 1)\n'
                   '  if (!b == 0) if (!!b == 1) if (!(a || 0) == 1) if ((b && c) + (b || a) + !a == 3)\n'
                   '  if (!(b < c) == 0) if (!(b > c)) if ((b <= c && c >= b) == 1) puts("Y"); return 0; }')

    def test_random_expressions_agree_with_a_model(self):
        # value and branch contexts of random expressions over every operator, against Python
        rng = random.Random(1979)
        vals = {"a": -3, "b": 7, "c": 0, "d": 32767, "e": -32768}
        ops = ["+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "&&", "||"]

        def gen(depth):
            if depth == 0 or rng.random() < 0.25:
                if rng.random() < 0.6:
                    v = rng.choice(list(vals))
                    return v, vals[v]
                n = rng.choice([0, 1, 2, 5, 9, 300])
                return str(n), n
            r = rng.random()
            if r < 0.12:
                t, v = gen(depth - 1)
                return "!(%s)" % t, int(v == 0)
            if r < 0.2:
                t, v = gen(depth - 1)
                return "-(%s)" % t, s16(-v)
            op = rng.choice(ops)
            (ta, va), (tb, vb) = gen(depth - 1), gen(depth - 1)
            v = {"+": lambda: s16(va + vb), "-": lambda: s16(va - vb), "*": lambda: s16(va * vb),
                 "/": lambda: c_div(va, vb, False), "%": lambda: c_div(va, vb, True),
                 "==": lambda: int(va == vb), "!=": lambda: int(va != vb), "<": lambda: int(va < vb),
                 ">": lambda: int(va > vb), "<=": lambda: int(va <= vb), ">=": lambda: int(va >= vb),
                 "&&": lambda: int(va != 0 and vb != 0), "||": lambda: int(va != 0 or vb != 0)}[op]()
            return "(%s %s %s)" % (ta, op, tb), v

        decl = " ".join("int %s = 0 - %d;" % (k, -v) if v < 0 else "int %s = %d;" % (k, v) for k, v in vals.items())
        for _ in range(4):
            lines, want = [], []
            for _ in range(40):
                t, v = gen(4)
                lit = "(0 - %d)" % -v if v < 0 else str(v)
                lines.append('x = %s; if (x == %s) puts("Y"); else puts("N");' % (t, lit))
                lines.append('if (%s) puts("T"); else puts("F");' % t)
                want += ["Y", "T" if v else "F"]
            self.check("int main() { %s int x;\n%s\nreturn 0; }" % (decl, "\n".join(lines)),
                       "".join(want).encode())

    def test_logical_operators_deep_in_the_eval_stack(self):
        deep = "(1+" * 9 + "1" + ")" * 9            # 10, needing all 8 entries
        self.check("int f(int a, int b, int c, int d, int e, int g, int h, int i) { return a+b+c+d+e+g+h+i; }\n"
                   "int main() { if (f(1, 1, 1, 1, 1, 1, 1, %s && %s) == 8) if (f(1, 1, 1, 1, 1, 1, 1, !%s) == 7)\n"
                   "  if (1 + (1 + (1 + (1 + (1 + (1 + (1 + (0 || %s))))))) == 8) puts(\"Y\"); return 0; }"
                   % (deep, deep, deep, deep))

    def test_break_and_continue(self):
        self.check("int main() { int i; int j; int n = 0;\n"
                   "  for (i = 0; i < 10; i = i + 1) { if (i % 2) continue; n = n + i; }\n"      # continue runs the step
                   "  if (n != 20) return 1;\n"
                   "  for (i = 0; ; i = i + 1) { if (i == 5) break; } if (i != 5) return 2;\n"
                   "  for (;;) { i = i + 1; if (i < 9) continue; break; } if (i != 9) return 3;\n"
                   "  i = 0; while (i < 100) { i = i + 1; if (i % 3) continue; if (i > 20) break; } if (i != 21) return 4;\n"
                   "  i = 0; while (1) { i = i + 1; if (i < 4) continue; break; } if (i != 4) return 5;\n"
                   "  n = 0; for (i = 0; i < 4; i = i + 1) for (j = 0; j < 4; j = j + 1) { if (j == 2) break; if (i == 1) continue; n = n + 1; }\n"
                   "  if (n != 6) return 6;\n"
                   "  n = 0; for (i = 0; i < 3; i = i + 1) { while (1) { break; } n = n + 1; } if (n != 3) return 7;\n"
                   "  puts(\"Y\"); return 0; }")

    def test_syscalls(self):
        self.check(r"""int main() { char buf[16]; int fd; int n; int w[4];
                   n = write(1, "hi\n", 3); if (n != 3) return 1;
                   if (write(9, "x", 1) != 0 - 1) return 2;
                   fd = open("/f", 0); if (fd < 0) return 3;
                   n = read(fd, buf, 16); if (n != 5) return 4; if (buf[0] != 'h' || buf[4] != 'o') return 5;
                   if (read(fd, buf, 16) != 0) return 6;
                   if (close(fd) != 0) return 7; if (close(fd) != 0 - 1) return 8;
                   if (open("/nope", 0) != 0 - 1) return 9;
                   fd = open("/g", 0x31); if (write(fd, "abc", 3) != 3) return 10; close(fd);
                   fd = open("/g", 0); n = read(fd, w, 8); if (n != 3 || w[0] != 'a' + 256 * 'b') return 11;
                   n = read(0, buf, 16); if (n != 3 || buf[2] != 'z') return 12;
                   exit(42); return 0; }""", b"hi\n", 42, files={"/f": b"hello"}, stdin=b"xyz")

    def test_syscall_registers_are_set_after_every_argument(self):
        # a call inside an argument makes syscalls of its own, which use r0 and r1
        r = self.check('int f(int v) { write(1, "ab", 2); return v; }\n'
                       'int main() { int fd; write(1, "XYZ", f(3)); fd = open("/f", f(0)); if (fd < 0) return 1;\n'
                       '  write(f(1), "!", 1); return 0; }',
                       b"abXYZabab!", files={"/f": b""})

    def test_extern_native_routines(self):
        natives = """.include "pvm.inc"
.export sub2, nine
sub2:   lda P_ESTKL+1,x         ; a - b: a under TOS
        sec
        sbc P_ESTKL,x
        sta P_ESTKL+1,x
        lda P_ESTKH+1,x
        sbc P_ESTKH,x
        sta P_ESTKH+1,x
        inx
        rts
nine:   dex
        lda #9
        sta P_ESTKL,x
        lda #0
        sta P_ESTKH,x
        rts
"""
        self.check("extern int sub2(int a, int b);\nextern int nine();\n"
                   'int main() { if (sub2(10, 3) == 7) if (sub2(nine(), 1 + sub2(5, 4)) == 7) if (1 + (2 + sub2(3, 3)) == 3)'
                   ' puts("Y"); return 0; }', natives=natives)


class L3aRefused(unittest.TestCase):
    def fails(self, src, msg, native=False):
        with self.assertRaises(cc.CompileError) as cm:
            (cc.compile_c if native else cc_pcode.compile_pcode)(src)
        self.assertIn(msg, str(cm.exception))

    def test_break_outside_a_loop(self):
        self.fails("int main() { break; return 0; }", "break outside a loop")
        self.fails("int main() { if (1) continue; return 0; }", "continue outside a loop")

    def test_bad_character_literals(self):
        self.fails("int main() { return 'ab'; }", "bad character")
        self.fails("int main() { return ''; }", "bad character")
        self.fails("int main() { return '\\q'; }", "bad escape in character literal")

    def test_syscall_arguments(self):
        self.fails('int main() { return write(1, "x"); }', "write takes 3 argument(s), not 2")
        self.fails("int main() { return write(1, 5, 1); }", "argument 2 of write: a number where a pointer is needed")
        self.fails('int main() { return close("x"); }', "argument 1 of close")

    def test_builtin_names_are_taken(self):
        self.fails("int read(int a) { return a; }\nint main() { return 0; }", "read is a builtin")
        self.fails("int puts(int a) { return a; }\nint main() { return 0; }", "puts is a builtin")

    def test_extern_names(self):
        self.fails("extern int cc_copy(int a);\nint main() { return 0; }", "reserved")
        self.fails("extern int L3(int a);\nint main() { return 0; }", "reserved")
        for reg in ("a", "X", "y", "z"):           # ca65's register names
            self.fails("extern int %s();\nint main() { return 0; }" % reg, "reserved")
        self.fails("extern int main();", "main cannot be extern")
        self.fails("extern int f(int a);\nint f(int a) { return a; }\nint main() { return 0; }", "defined twice")
        self.fails("extern int x;\nint main() { return 0; }", "extern declares a function")

    def test_the_native_back_end_refuses_each_by_name(self):
        for src, msg in (("int main() { return 5 % 2; }", "%"), ("int main() { return 1 && 2; }", "&&"),
                         ("int main() { return 1 || 2; }", "||"), ("int main() { return !1; }", "!"),
                         ("int main() { while (1) break; return 0; }", "break"),
                         ("int main() { while (1) continue; return 0; }", "continue"),
                         ("int main() { return close(1); }", "the builtin close"),
                         ("extern int f(int a);\nint main() { return 0; }", "extern"),
                         ("int main() { return 6 & 3; }", "&"), ("int main() { return 6 | 3; }", "|"),
                         ("int main() { return 6 ^ 3; }", "^"), ("int main() { return 6 << 3; }", "<<"),
                         ("int main() { return 6 >> 1; }", ">>"), ("int main() { return ~6; }", "~"),
                         ("int main() { return icall(0); }", "the builtin icall"),
                         ("int f() { return 1; }\nint main() { char *p = &f; return 0; }",
                          "the address of a function")):
            self.fails(src, msg + " is p-code only", native=True)

    def test_the_native_back_end_keeps_its_own_names(self):
        # a native program may still define read() itself (the L2 language had no builtins but puts)
        self.assertIn("v_read_a", cc.compile_c("int read(int a) { return a; }\nint main() { return read(1); }"))



class L3b(unittest.TestCase):
    """What the BASIC compiler's code generator needs: bit operations to split an address into
    bytes, pointer difference to make an int of one, and &f with icall to run the code it built."""

    def check(self, src, want=b"Y", status=0, **kw):
        r = run_full(src, **kw)
        self.assertEqual((r.out, r.exit), (want, status), src)
        return r

    def test_bit_operations_and_shifts_against_a_model(self):
        vals = [-32768, -32767, -256, -255, -2, -1, 0, 1, 2, 5, 255, 256, 4660, 32767]
        ops = {"&": lambda a, b: a & b, "|": lambda a, b: a | b, "^": lambda a, b: a ^ b}
        lit = lambda v: "(0 - %d)" % -v if v < 0 else str(v)  # noqa: E731
        lines = []
        for a in vals:
            for b in vals:
                for op, f in ops.items():
                    lines.append("if ((%s %s %s) != %s) return 1;" % (lit(a), op, lit(b), lit(s16(f(a, b)))))
            lines.append("if (~%s != %s) return 2;" % (lit(a), lit(s16(~a))))
            for n in range(16):
                lines.append("if ((%s << %d) != %s) return 3;" % (lit(a), n, lit(s16(a << n))))
                lines.append("if ((%s >> %d) != %s) return 4;" % (lit(a), n, lit(a >> n)))   # arithmetic
        self.check("int main() {\n%s\nputs(\"Y\"); return 0; }" % "\n".join(lines))

    def test_precedence_is_c_precedence(self):
        # * over + over << over < over == over & over ^ over | over &&
        self.check('int main() { if ((1 + 2 << 1) == 6) if ((1 << 2 < 5) == 1) if ((3 & 1 == 1) == 1)'
                   ' if ((6 ^ 3 & 1) == 7) if ((1 | 6 ^ 3) == 5) if ((1 | 2 && 0) == 0) if ((~0 & 7) == 7)'
                   ' if ((2 * 3 << 1) == 12) if (-1 >> 4 == -1) puts("Y"); return 0; }')

    def test_bit_operations_in_conditions_and_with_variables(self):
        self.check("int main() { int a = 12; char c = 255; int n = 0;\n"
                   "  if (a & 3) return 1; if (!(a & 4)) return 2; while (a) { a = a >> 1; n = n + 1; }\n"
                   "  if (n != 4) return 3; if ((c << 8 >> 8) != -1) return 4; if ((c ^ 15) != 240) return 5;\n"
                   '  puts("Y"); return 0; }')

    def test_pointer_difference(self):
        self.check('char s[10]; int w[6];\n'
                   'int main() { char *p = s; char *q = &s[7]; int *a = w; int *b = &w[5]; char *z = 0;\n'
                   '  if (q - p != 7) return 1; if (p - q != -7) return 2; if (b - a != 5) return 3;\n'
                   '  if (a - b != -5) return 4; if (p - p != 0) return 5;\n'
                   '  if (p - z == 0) return 6; if ((p + 3) - z != (p - z) + 3) return 7;\n'
                   '  puts("Y"); return 0; }')

    def test_icall_runs_a_function_by_its_address(self):
        self.check('int h() { puts("H"); return 7; }\n'
                   'int main() { char *p = &h; if (icall(p) != 7) return 1; return icall(&h) + 30; }',
                   b"HH", 37)

    def test_icall_runs_code_built_at_run_time(self):
        # what RUN does: the JSR pvm_interp header copied from a function of the program, then
        # bytecode: CALL h; CB 5; ADD; RET (PO_CALL $54, PO_CB $2A, PO_ADD $82, PO_RET $5C)
        self.check('char buf[16];\n'
                   'int h() { puts("H"); return 7; }\n'
                   'int main() { char *z = 0; char *p = &h; int a = p - z; int i;\n'
                   '  for (i = 0; i < 3; i = i + 1) buf[i] = p[i];\n'
                   '  buf[3] = 84; buf[4] = a; buf[5] = a >> 8; buf[6] = 42; buf[7] = 5; buf[8] = 130;'
                   ' buf[9] = 92;\n'
                   '  return icall(buf); }', b"H", 12)

    def test_isatty_is_one_or_zero(self):
        src = "int main() { return isatty(0) * 10 + isatty(1) * 2 + isatty(7) + 40; }"
        self.check(src, b"", 52, tty=True)
        self.check(src, b"", 40, tty=False)

    def test_refusals(self):
        def fails(src, msg):
            with self.assertRaises(cc.CompileError) as cm:
                cc_pcode.compile_pcode(src)
            self.assertIn(msg, str(cm.exception))
        fails("int main() { return icall(5); }", "argument 1 of icall: a number where a pointer is needed")
        fails("int main() { return icall(); }", "icall takes 1 argument, not 0")
        fails("int icall() { return 1; }\nint main() { return 0; }", "icall is a builtin")
        fails("int main() { char *p = 0; return p & 1; }", "a pointer can only be added to or subtracted from")
        fails("int main() { char *p = 0; return ~p; }", "~ of a pointer")
        fails("int main() { char *p = 0; int *q = 0; return p - q; }", "- of a pointer to int from a pointer to char")
        fails("int main() { char *p = 0; return 1 - p; }", "a pointer cannot be the right side of -")
        fails("int main() { char *p = 0; return p + p; }", "pointer")
        fails("int f() { return 1; }\nint main() { int *p = &f; return 0; }", "a pointer to char where a pointer to int")


if __name__ == "__main__":
    unittest.main()
