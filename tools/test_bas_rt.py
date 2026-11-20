"""bas's native number core (src/pc/bas-rt.s, docs/design/basic.md section 3) against a Python
model: random and edge operands through the c_ routines, called from a mini C harness under py65
(tools/asim.py). Needs ca65, ld65 and py65."""
import os
import random
import tempfile
import unittest

import asim
import pvmlink
import test_cc_pcode
import test_pvm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RT = os.path.join(ROOT, "src", "pc", "bas-rt.s")
MAX = 2**31 - 1
SCALE = 10000
ERRS = {2: "OOM", 4: "OVF", 5: "DIV0", 6: "ILQ"}


class Err(Exception):
    pass


def fit(r):
    if abs(r) > MAX:
        raise Err("OVF")
    return r


def sgn(v):
    return -1 if v < 0 else 1


def model(op, a, b=None):
    """The raw result (or "ERR"), the text c_fmt gives for a number, or an int."""
    if op == "add":
        return fit(a + b)
    if op == "sub":
        return fit(a - b)
    if op == "mul":
        return fit(sgn(a) * sgn(b) * ((abs(a) * abs(b) + SCALE // 2) // SCALE))
    if op == "div":
        if b == 0:
            raise Err("DIV0")
        return fit(sgn(a) * sgn(b) * ((abs(a) * SCALE + abs(b) // 2) // abs(b)))
    if op == "int":
        return fit((a // SCALE) * SCALE)
    if op == "fromi":
        return a * SCALE
    if op == "toi":
        q = abs(a) // SCALE * sgn(a)
        if not -32768 <= q <= 32767:
            raise Err("ILQ")
        return q
    if op == "cmp":
        return (a > b) - (a < b)
    raise ValueError(op)


def fmt(v):
    w, f = divmod(abs(v), SCALE)
    s = "-" if v < 0 else " "
    if f:
        return s + (str(w) if w else "") + "." + ("%04d" % f).rstrip("0")
    return s + str(w)


HARNESS = r"""
extern int rt_mark();
extern int c_ldv(char *p);
extern int c_stv(char *p);
extern int c_add();
extern int c_sub();
extern int c_mul();
extern int c_div();
extern int c_int();
extern int c_fromi(int i);
extern int c_toi();
extern int c_cmp();
extern int c_fmt(char *buf);
extern int c_err();
extern int c_mac(int d);
char v[4];
char nl[1];
char *src;              /* bas.c's globals that bas-rt.s's scanner and emitter use */
int si;
char *mem;
int msz;
int cend;
int vbot;
int straight;
int err;
int ld(int lo, int hi) { v[0] = lo; v[1] = lo >> 8; v[2] = hi; v[3] = hi >> 8; return c_ldv(v); }
int str(char *p) { int n; n = 0; while (p[n]) n = n + 1; write(1, p, n); return 0; }
int num(int i) { char b[8]; int n; n = 7; if (i == 0 - 32767 - 1) { write(1, "-32768", 6); return 0; }
  if (i < 0) { write(1, "-", 1); i = 0 - i; }
  while (1) { n = n - 1; b[n] = '0' + i %% 10; i = i / 10; if (!i) break; } write(1, b + n, 7 - n); return 0; }
int end() { write(1, "\n", 1); return 0; }
int show() { char b[12]; write(1, b, c_fmt(b)); return 0; }
int fail() { write(1, "E", 1); num(c_err()); return end(); }
%s
int main() {
%s
  return 0; }
"""


def lohi(r):
    u = r & 0xFFFFFFFF
    return "%d, %d" % (u & 0xFFFF if u & 0xFFFF < 0x8000 else (u & 0xFFFF) - 0x10000,
                       u >> 16 if u >> 16 < 0x8000 else (u >> 16) - 0x10000)


def case_c(i, op, a, b):
    """One case: a function that prints the result (or E and the error number)."""
    body = "ld(%s); " % lohi(a) if op != "fromi" else ""
    if op in ("add", "sub", "mul", "div", "cmp"):
        body += "ld(%s); " % lohi(b)
    if op == "fromi":
        body += "c_fromi(%d); show(); " % a
    elif op == "toi":
        body += "num(c_toi()); "
    elif op == "cmp":
        body += "num(c_cmp()); "
    else:
        body += "c_%s(); show(); " % op
    return "int t%d() { if (rt_mark()) return fail(); %sreturn end(); }" % (i, body)


def expect(op, a, b):
    try:
        r = model(op, a, b)
    except Err as e:
        return "E%d" % {v: k for k, v in ERRS.items()}[str(e)]
    return str(r) if op in ("toi", "cmp") else fmt(r)


def run_cases(cases):
    src = HARNESS % ("\n".join(case_c(i, *c) for i, c in enumerate(cases)),
                     "\n".join("  t%d();" % i for i in range(len(cases))))
    with open(RT) as f:
        natives = f.read()
    with tempfile.TemporaryDirectory(prefix="basrt-") as d:
        path = test_cc_pcode.build(src, d, natives=natives)
        r = asim.run("p", [], path=path, libs={pvmlink.LIBPATH: os.path.join(test_pvm.lib_dir(), "pvm")},
                     limit=400_000_000)
    return r


EDGE = [0, 1, -1, 5000, -5000, 9999, -9999, 10000, -10000, 15000, -15000, 25000, -25000,
        MAX, -MAX, MAX - 1, 2**16, 2**24 + 3, 327670000, -327680000, 327679999, -327689999,
        10**8, 46341 * 10000 // 100]


def operand(rnd):
    k = rnd.random()
    if k < 0.3:
        return rnd.choice(EDGE)
    if k < 0.6:
        return rnd.randint(-10**6, 10**6)
    if k < 0.8:
        return rnd.randint(-10**9, 10**9)
    return rnd.randint(-MAX, MAX)


@unittest.skipUnless(test_pvm.HAVE_TOOLS, "needs ca65, ld65 and py65")
class Numbers(unittest.TestCase):
    def check(self, cases):
        r = run_cases(cases)
        self.assertEqual(r.exit, 0, r.out)
        got = r.out.decode("latin-1").split("\n")[:-1]
        self.assertEqual(len(got), len(cases), r.out)
        for c, g in zip(cases, got):
            self.assertEqual(g, expect(*c), c)

    def test_edges(self):
        cases = []
        for op in ("add", "sub", "mul", "div", "cmp"):
            for a in EDGE:
                for b in (0, 1, -1, 5000, -10000, 15000, MAX, -MAX, 3):
                    cases.append((op, a, b))
        for a in EDGE + [4, -4, 32767 * 10000, -32768 * 10000, 32768 * 10000, -32769 * 10000 + 1]:
            for op in ("int", "toi"):
                cases.append((op, a, None))
        for i in (0, 1, -1, 32767, -32768, 12345, -100):
            cases.append(("fromi", i, None))
        for i in range(0, len(cases), 120):
            self.check(cases[i:i + 120])

    def test_random(self):
        rnd = random.Random(1978)
        cases = []
        for _ in range(240):
            op = rnd.choice(("add", "sub", "mul", "mul", "div", "div", "cmp", "int", "toi"))
            cases.append((op, operand(rnd), operand(rnd) if op in ("add", "sub", "mul", "div", "cmp") else None))
        for i in range(0, len(cases), 120):
            self.check(cases[i:i + 120])

    def test_a_carry_out_of_the_fifth_byte_ripples_on(self):
        # addb once lost the carry past acc+4 (cpy cleared it): these are cases that hit it
        self.check([("mul", 1048575, 1048577), ("mul", 4926, 1116028854), ("div", 769607180, 2023841514),
                    ("div", 1869112831, 2110801679)])

    def run_main(self, defs, body, extra=""):
        with open(RT) as f:
            natives = f.read() + extra
        with tempfile.TemporaryDirectory(prefix="basrt-") as d:
            path = test_cc_pcode.build(HARNESS % (defs, body), d, natives=natives)
            r = asim.run("p", [], path=path, libs={pvmlink.LIBPATH: os.path.join(test_pvm.lib_dir(), "pvm")})
        self.assertEqual(r.exit, 0, r.out)
        return r.out.decode("latin-1")

    # tk(f) is shaped like compiled BASIC: bytecode with no frame of its own that marks, then
    # calls f; on an error it gives 100 + the error number
    TK = """
.export tk
tk:     P_FUNC
        P_W PO_CALL, rt_mark
        P_BR PO_BRTRU, @err
        P_OP PO_ICAL
        P_OP PO_RET
@err:   P_OP PO_DROP
        P_W PO_CALL, c_err
        P_B PO_ADDI, 100
        P_OP PO_RET
"""

    def test_a_throw_restores_the_frames_and_the_eval_stack(self):
        # the error comes from four calls down, each with a frame of its own; the caller's
        # pending sums sit on the eval stack under tk, where the ENTERs spill and reuse them
        defs = """extern int tk(char *f);
int g(int a, int b, int c) { ld(a, 0); ld(0, 0); c_div(); return a + b + c; }
int h(int n) { int x; x = n * 2; if (n) return 1 + (2 + (3 + h(n - 1))); return g(x, x, x); }
int h3() { return h(3); }
int ok() { return 5; }"""
        out = self.run_main(defs, "  num(1 + (2 + (3 + (4 + (5 + (6 + (7 + tk(&h3)))))))); end();"
                                  "  num(1 + (2 + (3 + (4 + (5 + (6 + (7 + tk(&ok)))))))); end();", self.TK)
        self.assertEqual(out, "%d\n%d\n" % (28 + 105, 28 + 5))

    def test_mac_reads_constants_and_flags_overflow(self):
        # c_mac(d): top = top * 10 + d in raw units
        defs = """int mac(char *s) { int n; int o; n = 0; o = 0; ld(0, 0);
  while (s[n]) { o = o | c_mac(s[n] - '0'); n = n + 1; } num(o); write(1, " ", 1); show(); return end(); }"""
        out = self.run_main(defs, '  mac("12345"); mac("2147483647"); mac("2147483648"); mac("0000150000");')
        lines = out.split("\n")
        self.assertEqual([lines[0], lines[1], lines[2][:2], lines[3], lines[4]], ["0  1.2345", "0  214748.3647", "1 ", "0  15", ""])

    def test_the_number_stack_is_bounded(self):
        defs = """int t() { int i; i = 0; if (rt_mark()) { num(i); write(1, " ", 1); return num(c_err()); }
  while (1) { ld(i, 0); i = i + 1; } return 0; }"""
        self.assertEqual(self.run_main(defs, "  t(); end();"), "16 2\n")

    def test_format(self):
        for v, s in ((0, " 0"), (5000, " .5"), (-5000, "-.5"), (10000, " 1"), (12500, " 1.25"),
                     (1, " .0001"), (MAX, " 214748.3647"), (-MAX, "-214748.3647"), (100, " .01")):
            self.assertEqual(fmt(v), s)
        self.check([("add", v, 0) for v in (0, 5000, -5000, 1, 100, MAX, -MAX, 10**8 + 50)])


if __name__ == "__main__":
    unittest.main()
