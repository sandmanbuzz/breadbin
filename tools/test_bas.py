"""bas (src/pc/bas.c), the compiled BASIC, slice L3b (docs/design/basic.md section 5): built from
the mini C with cc.py --pcode, run under py65 (tools/asim.py) with /lib/pvm. Needs ca65, ld65 and
py65 (the container image has them)."""
import os
import random
import re
import tempfile
import unittest

import asim
import pvmlink
import test_bas_rt
import test_cc_pcode
import test_pvm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "pc", "bas.c")
RT = os.path.join(ROOT, "src", "pc", "bas-rt.s")
_built = {}
FREE = "16384 BYTES FREE\n"
LINE = ":".join(['?"A";'] * 20)       # 119 bytes stored (? is one token), 143 of code with the line's rt_ln
LISTED = LINE.replace("?", "PRINT")


def BIG(n):
    return "".join("%d %s\n" % (i, LINE) for i in range(1, n + 1))


def binary():
    if "path" not in _built:
        _built["dir"] = tempfile.TemporaryDirectory(prefix="bas-")
        with open(SRC) as f, open(RT) as g:
            _built["path"] = test_cc_pcode.build(f.read(), _built["dir"].name, natives=g.read())
    return _built["path"]


def bas(text, tty=False, limit=40_000_000, brk=64):
    """bas with text on stdin: (output as str, exit status)."""
    r = asim.run("bas", [], path=binary(), libs={pvmlink.LIBPATH: os.path.join(test_pvm.lib_dir(), "pvm")},
                 stdin=text.encode("latin-1"), tty=tty, limit=limit, brk=brk)
    return r.out.decode("latin-1"), r.exit


@unittest.skipUnless(test_pvm.HAVE_TOOLS, "needs ca65, ld65 and py65")
class Bas(unittest.TestCase):
    def out(self, text, **kw):
        out, status = bas(text, **kw)
        self.assertEqual(status, 0, out)
        return out

    def test_the_arena_is_what_the_kernel_grants(self):
        # BYTES FREE follows the pages BRK gives: 64 is 16,384 bytes, 80 is 20,480, and a pool
        # too small for 4096 bytes is refused with a message on stderr, not a crash
        for pages, text in ((64, "16384"), (80, "20480"), (120, "30720"), (200, "30720"), (16, "4096")):
            out, status = bas("", tty=True, brk=pages)
            self.assertEqual((out, status), (text + " BYTES FREE\nREADY.\n", 0), pages)
        r = asim.run("bas", [], path=binary(), libs={pvmlink.LIBPATH: os.path.join(test_pvm.lib_dir(), "pvm")},
                     stdin=b"", tty=True, brk=15)
        self.assertEqual((r.out, r.err, r.exit), (b"", b"bas: out of memory\n", 1))

    def test_hello_end_to_end(self):
        self.assertEqual(self.out('10 PRINT "HELLO, WORLD"\nRUN\n'), "HELLO, WORLD\n")

    def test_print_forms(self):
        # ? is PRINT; ; joins and, last, keeps the line open; strings side by side join; an
        # unclosed string ends at the end of the line; an empty PRINT is a newline
        self.assertEqual(self.out('10 PRINT "A";"B";\n20 ?"C" "D"\n30 PRINT\n40 ? "E\n50 print"F";:print"G"\n'
                                  '60 PRINT "";""\nRUN\n'),
                         "ABCD\n\nE\nFG\n\n")

    def test_immediate_mode_and_after_run(self):
        self.assertEqual(self.out('PRINT "NOW"\n10 PRINT "PROG"\nRUN\n? "AGAIN"\nRUN\n'),
                         "NOW\nPROG\nAGAIN\nPROG\n")

    def test_list_normalises_case_and_spaces_not_strings_or_rem(self):
        out = self.out('20   print   "a  b"  :  rem  Keep  THIS  \n10rem x\n30 ?"q":Rem Q\n40 PRINT "x" : REM\nLIST\n')
        self.assertEqual(out, '10 REM x\n20 PRINT "a  b" : REM  Keep  THIS  \n30 PRINT"q":REM Q\n40 PRINT "x" : REM\n')

    def test_tabs_unclosed_strings_and_spaced_line_numbers(self):
        # a tab is a space outside quotes; an unclosed string keeps its trailing spaces; spaces
        # among a line number's digits are skipped, as MS's CHRGET does
        out = self.out('10\tPRINT\t"A\tB";\n20 PRINT "C   \n1 5 ?"D"\n3 0 REM X \nLIST\nLIST 1 5\nRUN\n')
        self.assertEqual(out, '10 PRINT "A\tB";\n15 PRINT"D"\n20 PRINT "C   \n30 REM X \n15 PRINT"D"\nA\tBD\nC   \n')

    def test_ready_and_errors_start_a_fresh_line(self):
        self.assertEqual(self.out('?"A";\n10 ?"B";\nRUN\n?"C";:FOO\n', tty=True),
                         FREE + "READY.\nA\nREADY.\nB\nREADY.\n?SYNTAX ERROR\nREADY.\n")
        self.assertEqual(self.out('?"A";\nFOO\n'), "A\n?SYNTAX ERROR\n")

    def test_immediate_mode_after_a_large_run(self):
        # 61 lines (125 bytes of text each, with the header, and their code) leave less than
        # another line's worth free (62 do not run at all): a typed line that does not fit after
        # the code is compiled in its place, and RUN still works
        out = self.out(BIG(61) + 'RUN\n?"' + "X" * 110 + '"\nRUN\n', limit=400_000_000)
        self.assertEqual(out, "A" * 20 * 61 + "X" * 110 + "\n" + "A" * 20 * 61)

    def test_line_store_sorts_replaces_and_deletes(self):
        out = self.out('30 ?"C"\n10 ?"A"\n20 ?"B"\n20 ?"BB"\n40 ?"D"\n30\n35\nLIST\nRUN\n')
        self.assertEqual(out, '10 PRINT"A"\n20 PRINT"BB"\n40 PRINT"D"\nA\nBB\nD\n')

    def test_keywords_are_tokens(self):
        # crunched as MS: anywhere outside strings and REM text, the first keyword that matches
        # (so TOTAL is TO TAL and a syntax error, as in MS); LIST spells them out
        self.assertEqual(self.out('10 fora=1to2:?a;:next\n20 IFA=3THENPRINT"TO"\n30 REM print TO\nLIST\nRUN\n'),
                         '10 FORA=1TO2:PRINTA;:NEXT\n20 IFA=3THENPRINT"TO"\n30 REM print TO\n 1  2 TO\n')
        self.assertEqual(self.out("TOTAL=1\nGO TO 5\n10 GO TO 20\n20 ?7\nRUN\n"),
                         "?SYNTAX ERROR\n?UNDEF'D STATEMENT ERROR\n 7 \n")
        self.assertEqual(self.out('PRINT "A\xc1"\nPRINT A\xc1\n10 REM \xc1\nLIST\n'),
                         "A\xc1\n?SYNTAX ERROR\n10 REM \xc1\n")

    def test_token_numbers_match_the_table(self):
        with open(SRC) as f:
            text = f.read()
        table = re.search(r'char kwt\[\] = "([A-Z|]+)";', text).group(1).split("|")[:-1]
        uses = re.findall(r"(\d+) /\* tk ([A-Z]+) \*/", text)
        self.assertGreater(len(uses), 25)
        for n, name in uses:
            self.assertEqual(int(n), 128 + table.index(name), name)
        firsts = [k[0] for k in table]
        self.assertEqual(firsts, sorted(firsts))            # grouped by first letter
        for i, k in enumerate(table):                       # no keyword after its own prefix
            self.assertFalse(any(k.startswith(e) for e in table[:i] if e != k), k)

    def test_new(self):
        self.assertEqual(self.out('10 ?"A"\nNEW\nLIST\nRUN\n20 ?"B"\nRUN\n'), "B\n")

    def test_list_ranges(self):
        prog = "".join('%d ?"%d"\n' % (n, n) for n in (0, 5, 10, 20, 32767, 32768, 40000, 63999))
        def listed(arg):
            return [int(l.split()[0]) for l in self.out(prog + "LIST" + arg + "\n").splitlines()]
        self.assertEqual(listed(""), [0, 5, 10, 20, 32767, 32768, 40000, 63999])
        self.assertEqual(listed(" 10"), [10])
        self.assertEqual(listed(" 10-"), [10, 20, 32767, 32768, 40000, 63999])
        self.assertEqual(listed("-10"), [0, 5, 10])
        self.assertEqual(listed(" 6 - 32768"), [10, 20, 32767, 32768])
        self.assertEqual(listed(" 40000-63999"), [40000, 63999])
        self.assertEqual(listed(" 11"), [])
        self.assertEqual(self.out(prog + "RUN\n"), "0\n5\n10\n20\n32767\n32768\n40000\n63999\n")

    def test_line_numbers_past_63999_are_syntax_errors(self):
        for n in ("64000", "65535", "65536", "99999", "123456"):
            self.assertEqual(self.out(n + ' ?"X"\nLIST\n'), "?SYNTAX ERROR\n", n)
            self.assertEqual(self.out('10 ?"X"\nLIST ' + n + "\n"), "?SYNTAX ERROR\n", n)

    def test_a_compile_error_stops_before_anything_runs(self):
        self.assertEqual(self.out('10 PRINT "A"\n20 PRINT )\n30 PRINT "C"\nRUN\n'), "?SYNTAX ERROR IN 20\n")
        self.assertEqual(self.out('10 PRINT "A" )\nRUN\n'), "?SYNTAX ERROR IN 10\n")
        self.assertEqual(self.out('40000 GOTO 10\nRUN\n'), "?UNDEF'D STATEMENT ERROR IN 40000\n")

    def test_bad_commands(self):
        for line in ("LIST X", "LIST 10-20-30", "NEW 5", "RUN X", "FOO", "LISTX", "PRINT 5)", "X$=1"):
            self.assertEqual(self.out(line + "\n"), "?SYNTAX ERROR\n", line)

    def test_ready_only_on_a_terminal(self):
        self.assertEqual(self.out('?"A"\n10 ?"B"\n\nFOO\n', tty=True), FREE + "READY.\nA\nREADY.\n?SYNTAX ERROR\nREADY.\n")
        self.assertEqual(self.out('?"A"\n', tty=False), "A\n")

    def test_bye_and_end_of_input(self):
        self.assertEqual(self.out('?"A"\nBYE\n?"B"\n'), "A\n")
        self.assertEqual(self.out('?"A"\nSYSTEM\n?"B"\n'), "A\n")
        self.assertEqual(self.out('?"A"'), "A\n")                  # the last line has no newline
        self.assertEqual(self.out('?"A"\r\n?"B"\r\n'), "A\nB\n")
        self.assertEqual(self.out(""), "")

    def test_a_line_too_long(self):
        self.assertEqual(self.out('?"' + "X" * 121 + '"\n'), "X" * 121 + "\n")    # 124 is the most
        self.assertEqual(self.out('?"' + "X" * 122 + '"\n?"OK"\n'), "?LINE TOO LONG ERROR\nOK\n")

    def test_long_strings_and_many_statements(self):
        # CS and CALL each reset the VM's Y, so PRINT's code never runs straight past 240 bytes
        # and room() cannot fire yet: its test comes with L3c's expressions (mutating it now
        # passes this test)
        s = "".join(chr(33 + i % 90).replace('"', "'") for i in range(110))
        prog = "".join('%d ?"%s%d";\n' % (n, s, n) for n in range(1, 11)) + "100 ?\n"
        prog += "200 " + ":".join('?"%s";' % chr(65 + i % 26) for i in range(20)) + "\n210 ?\n"
        want = "".join(s + str(n) for n in range(1, 11)) + "\n" + "".join(chr(65 + i) for i in range(20)) + "\n"
        self.assertEqual(self.out(prog + "RUN\n"), want)

    def test_a_long_line_of_xops_with_operands_runs_straight_on(self):
        # XLDK, XLDV and XSTV carry operand bytes: a line of 8 such statements is over 100 bytes
        # of code (a 124-character line is the most); each op must leave IP renormalised
        parts = ["A=A+%d.5:B=A*2" % i for i in range(8)]
        out = self.out("10 " + ":".join(parts) + "\n20 ?A;B\nRUN\n")
        a = sum(i + 0.5 for i in range(8))
        self.assertEqual(out, " %g  %g \n" % (a, a * 2))

    def test_out_of_memory(self):
        # text, code and variables share the 16384-byte arena. The text: a line of 110 Ys is 119
        # bytes (2 + 1 + 2 of header, 113 of text, a 0), so 137 fit; the rest are refused and the store is unhurt
        prog = "".join('%d ?"%s"\n' % (n, "Y" * 110) for n in range(1, 150))
        out = self.out(prog + "LIST 1\nLIST 137\nLIST 138\n", limit=400_000_000)
        self.assertEqual(out, "?OUT OF MEMORY ERROR\n" * 12 + '1 PRINT"' + "Y" * 110 + '"\n137 PRINT"' + "Y" * 110 + '"\n')

    def test_out_of_memory_compiling(self):
        # the code: 80 lines leave room for 45 lines' code; the error names the line being
        # compiled, and a typed line still runs
        out = self.out(BIG(80) + 'RUN\n?"STILL"\nLIST 80\n', limit=400_000_000)
        self.assertEqual(out, "?OUT OF MEMORY ERROR IN 46\nSTILL\n80 " + LISTED + "\n")
        # the variables: 61 lines leave too little (60 leave enough) for 20 new variables (6 bytes each) and their
        # assignments (5 bytes of code each: a constant, then XSTV)
        out = self.out(BIG(61) + "62 " + ":".join("A%s=0" % chr(65 + i) for i in range(20)) + "\nRUN\n",
                       limit=400_000_000)
        self.assertEqual(out, "?OUT OF MEMORY ERROR IN 62\n")

    def test_opcode_numbers_agree_with_the_vm(self):
        inc = open(os.path.join(ROOT, "src", "pvm", "pvm.inc")).read()
        ops = {m.group(1): int(m.group(2), 16) for m in re.finditer(r"^(PO_\w+)\s*=\s*\$([0-9A-F]+)", inc, re.M)}
        src = open(SRC).read()
        used = re.findall(r"(\d+) /\* (PO_\w+)( \d+)? \*/", src)
        self.assertGreaterEqual(len(used), 6)
        for num, name, arg in used:
            want = 2 * int(arg) if name == "PO_CN" else ops[name]
            self.assertEqual(int(num), want, name)


MSG = {"OVF": "OVERFLOW", "DIV0": "DIVISION BY ZERO", "ILQ": "ILLEGAL QUANTITY"}


def pow_model(b, e):
    """rt_pow's square-and-multiply, rounding as n_mul and n_div do at each step."""
    m = test_bas_rt.model
    neg, e, r = e < 0, abs(e), 10000
    while e:
        if e & 1:
            r = m("mul", r, b)
        e >>= 1
        if e:
            b = m("mul", b, b)
    return m("div", 10000, r) if neg else r


class Expr:
    """Random expressions as text, with their value under bas's arithmetic (raw units)."""
    def __init__(self, rnd):
        self.rnd = rnd

    def const(self):
        r = self.rnd.random()
        if r < 0.4:
            v = self.rnd.randint(0, 999) * 10000
        elif r < 0.8:
            v = self.rnd.randint(0, 9999999)
        else:
            v = self.rnd.choice([0, 10000, 5000, 1, 99999, 2147483647, 327670000])
        w, f = divmod(v, 10000)
        return (str(w) + ("." + ("%04d" % f).rstrip("0") if f else "")), v

    def gen(self, depth):
        m = test_bas_rt.model
        k = self.rnd.random()
        if depth <= 0 or k < 0.25:
            return self.const()
        if k < 0.35:
            t, v = self.gen(depth - 1)
            return "-(" + t + ")", test_bas_rt.fit(-v)
        if k < 0.42:
            t, v = self.gen(depth - 1)
            e = self.rnd.randint(-3, 4)
            return "(" + t + ")^" + str(e), pow_model(v, e)
        if k < 0.5:
            t1, v1 = self.gen(depth - 1)
            t2, v2 = self.gen(depth - 1)
            op = self.rnd.choice(["<", "=", ">", "<=", ">=", "<>"])
            c = m("cmp", v1, v2)
            hit = {"<": c < 0, "=": c == 0, ">": c > 0, "<=": c <= 0, ">=": c >= 0, "<>": c != 0}[op]
            return "(" + t1 + op + t2 + ")", -10000 if hit else 0
        op = self.rnd.choice("+-*/")
        t1, v1 = self.gen(depth - 1)
        t2, v2 = self.gen(depth - 1)
        return "(" + t1 + op + t2 + ")", m({"+": "add", "-": "sub", "*": "mul", "/": "div"}[op], v1, v2)

    def line(self):
        try:
            t, v = self.gen(3)
        except test_bas_rt.Err as e:
            # the text is regenerated from the same draws to report the error: simpler to retry
            return None
        return t, test_bas_rt.fmt(v) + " \n"


@unittest.skipUnless(test_pvm.HAVE_TOOLS, "needs ca65, ld65 and py65")
class Language(unittest.TestCase):
    """L3c: numbers, variables, expressions and control flow (docs/design/basic.md 5)."""
    def out(self, text, **kw):
        out, status = bas(text, limit=kw.pop("limit", 200_000_000), **kw)
        self.assertEqual(status, 0, out)
        return out

    def test_random_expressions_against_the_model(self):
        # errors are left to the targeted tests: a drawn expression that overflows or divides
        # by zero is drawn again
        gen = Expr(random.Random(1979))
        lines = []
        while len(lines) < 60:
            l = gen.line()
            if l and len(l[0]) < 110:
                lines.append(l)
        out = self.out("".join("PRINT " + t + "\n" for t, _ in lines))
        self.assertEqual(out.split("\n"), "".join(w for _, w in lines).split("\n"))

    def test_precedence_and_operators(self):
        self.assertEqual(self.out("PRINT 2+3*4;(2+3)*4;10-3-2;7/2*2;2*3^2;-2^2;2^-2;(-2)^3;0^0\n"),
                         " 14  20  5  7  18 -4  .25 -8  1 \n")
        self.assertEqual(self.out("PRINT 1<2;1=2;2>=2;1<>1;2=<2;3><4;NOT 0;NOT -1;3 AND 5;3 OR 5;1<2 AND 2<3\n"),
                         "-1  0 -1  0 -1 -1 -1  0  1  7 -1 \n")
        self.assertEqual(self.out("PRINT ABS(-3.5);INT(-3.5);INT(2.7);SGN(-2);SGN(0);SGN(.0001);-(1)+ +1\n"),
                         " 3.5 -4  2 -1  0  1  0 \n")

    def test_constants(self):
        # four decimals, the fifth rounds; spaces inside a number are skipped, as MS
        self.assertEqual(self.out("PRINT 1.23456;.00005;.00004;214748.3647;1 000\n"),
                         " 1.2346  .0001  0  214748.3647  1000 \n")
        self.assertEqual(self.out("PRINT 214748.3648\nPRINT 99999999\nPRINT 1\n"),
                         "?OVERFLOW ERROR\n?OVERFLOW ERROR\n 1 \n")

    def test_runtime_errors_name_their_line(self):
        self.assertEqual(self.out("10 A=1\n20 PRINT 1/(A-1)\nRUN\n"), "?DIVISION BY ZERO ERROR IN 20\n")
        self.assertEqual(self.out("10 A=100000\n20 PRINT A*A\nRUN\n"), "?OVERFLOW ERROR IN 20\n")
        self.assertEqual(self.out("10 A%=40000\nRUN\n"), "?ILLEGAL QUANTITY ERROR IN 10\n")
        self.assertEqual(self.out("10 PRINT 2^.5\nRUN\n"), "?ILLEGAL QUANTITY ERROR IN 10\n")
        self.assertEqual(self.out("10 PRINT 1:STOP:PRINT 2\nRUN\n"), " 1 \nBREAK IN 10\n")
        self.assertEqual(self.out("PRINT 1:STOP:PRINT 2\n"), " 1 \nBREAK\n")

    def test_variables(self):
        # two characters count, as MS; % is a separate 16-bit integer variable that truncates
        out = self.out("10 AB=1.5:ABC=ABC+1:A%=7.9:B%=-7.9:A=2\n20 PRINT AB;ABC;A%;B%;A;Z;Z%\n"
                       "30 A%=A%*1000:PRINT A%\nRUN\n")
        self.assertEqual(out, " 2.5  2.5  7 -7  2  0  0 \n 7000 \n")
        # RUN starts from zero; an edit clears the variables, as MS
        self.assertEqual(self.out("10 A=A+1:PRINT A\nRUN\nRUN\nA=5\nPRINT A\n20 REM\nPRINT A\n"),
                         " 1 \n 1 \n 5 \n 0 \n")
        # a name ends where a keyword starts (as MS: FORM is FOR M)
        self.assertEqual(self.out("10 FORM=1TO2:PRINT M;:NEXT\n20 IFX=0THENPRINT\"Z\"\nRUN\n"), " 1  2 Z\n")
        self.assertEqual(self.out("X$=1\n"), "?SYNTAX ERROR\n")

    def test_goto_and_if(self):
        out = self.out('10 GOTO 30\n20 PRINT "NO"\n30 PRINT "YES":IF 1 THEN 50\n40 PRINT "NO"\n'
                       '50 IF 0 THEN PRINT "NO":PRINT "NO"\n60 IF 1 GOTO 80\n70 PRINT "NO"\n'
                       '80 IF 2>1 THEN IF .5 THEN PRINT "A";:IF 0 THEN 10\n90 GO TO 110\n100 END\n'
                       '110 I=I+1:IF I<3 THEN 90\n120 PRINT I\nRUN\n')
        self.assertEqual(out, "YES\nA 3 \n")
        self.assertEqual(self.out("10 GOTO 25\n20 END\n30 END\nRUN\n"), "?UNDEF'D STATEMENT ERROR IN 10\n")
        self.assertEqual(self.out("10 PRINT 1\n20 PRINT 2\nRUN 20\nRUN 15\nGOTO 20\nGOTO 5\n"),
                         " 2 \n?UNDEF'D STATEMENT ERROR\n 2 \n?UNDEF'D STATEMENT ERROR\n")

    def test_gosub_and_return(self):
        out = self.out("10 FOR I=1 TO 3:GOSUB 100:NEXT:GOSUB 200:END\n100 PRINT I;:RETURN\n"
                       "200 FOR J=1 TO 5:IF J=2 THEN RETURN\n210 NEXT\nRUN\n")
        self.assertEqual(out, " 1  2  3 ")
        self.assertEqual(self.out("RETURN\n10 RETURN\nRUN\n"),
                         "?RETURN WITHOUT GOSUB ERROR\n?RETURN WITHOUT GOSUB ERROR IN 10\n")
        self.assertEqual(self.out("10 GOSUB 10\nRUN\n"), "?OUT OF MEMORY ERROR IN 10\n")

    def test_gosub_depth_is_bounded_without_touching_neighbours(self):
        # the control stack holds 64 returns; the 65th GOSUB (N counts it) is OUT OF MEMORY, and bas is intact after it
        self.assertEqual(self.out("10 N=N+1:GOSUB 10\nRUN\nPRINT N\n20 PRINT 7\nGOTO 20\n"),
                         "?OUT OF MEMORY ERROR IN 10\n 65 \n 7 \n")

    def test_the_error_line_follows_a_return_and_a_next(self):
        self.assertEqual(self.out("10 GOSUB 100:PRINT 1/0\n20 END\n100 RETURN\nRUN\n"), "?DIVISION BY ZERO ERROR IN 10\n")
        self.assertEqual(self.out("10 FOR I=1 TO 0 STEP -1:X=1/I\n20 NEXT\nRUN\n"), "?DIVISION BY ZERO ERROR IN 10\n")

    def test_for_and_next(self):
        out = self.out("10 FOR I=3 TO 1 STEP -1:PRINT I;:NEXT:PRINT\n20 FOR J=0 TO 1 STEP .25:PRINT J;:NEXT J\n"
                       "30 PRINT:FOR I=1 TO 2:FOR J=1 TO 2:PRINT I;J;:NEXT J,I\n40 PRINT:FOR I=1 TO 0:PRINT \"ONCE\";I:NEXT:PRINT I\n"
                       "50 FOR I=1 TO 3:FOR I=5 TO 6:PRINT I;:NEXT:PRINT:NEXT I\nRUN\n")
        # a FOR on a variable whose loop is open replaces that loop, as MS: line 50's NEXT I
        # then has none
        self.assertEqual(out, " 3  2  1 \n 0  .25  .5  .75  1 \n 1  1  1  2  2  1  2  2 \nONCE 1 \n 2 \n 5  6 \n"
                         "?NEXT WITHOUT FOR ERROR IN 50\n")
        self.assertEqual(self.out("NEXT\n10 FOR I=1 TO 2\n20 NEXT J\nRUN\nFOR I%=1 TO 2\n"),
                         "?NEXT WITHOUT FOR ERROR\n?NEXT WITHOUT FOR ERROR IN 20\n?SYNTAX ERROR\n")

    def test_print_columns(self):
        self.assertEqual(self.out('PRINT 1,2,"ABCDEFGHIJK",4\nPRINT ,"X"\n'),
                         " 1         2        ABCDEFGHIJK          4 \n          X\n")

    def test_formula_too_complex(self):
        self.assertEqual(self.out("PRINT " + "(" * 11 + "1" + ")" * 11 + "\nPRINT " + "(" * 12 + "1" + ")" * 12 + "\n"),
                         " 1 \n?FORMULA TOO COMPLEX ERROR\n")
        deep = "1+(" * 5 + "1" + ")" * 5
        self.assertEqual(self.out("PRINT " + deep + "\n"), " 6 \n")

    def test_functions_count_toward_nesting(self):
        # each ABS( costs two levels; past 11 is FORMULA TOO COMPLEX, never a frame overflow
        def nest(n):
            return "PRINT " + "ABS(" * n + "1" + ")" * n + "\n"
        self.assertEqual(self.out(nest(5) + nest(6) + "PRINT -INT(-ABS(-SGN(2.5)))\n"),
                         " 1 \n?FORMULA TOO COMPLEX ERROR\n 1 \n")

    def test_the_deepest_nesting_fits_the_frame_stack(self):
        # the frame stack (fstack in bas.c, a measured size) holds: climb counts its frames (a
        # chain of up to 6 per level, one per precedence) and each nested IF counts against the same
        # budget, so any mix of IF THENs, parentheses, ABS(, NOT and unary minus ends in a value or
        # ?FORMULA TOO COMPLEX, never a frame overflow (the process exiting, the stored program lost).
        # The levels cost most when every precedence precedes the ( : the last body here
        for ni in (0, 2, 4, 8):
            if_ = "10 " + "IF 1 THEN " * ni
            for n in range(15):
                for body in ("(", "ABS(", "1+(", "-(", "NOT(", "1OR1AND1<1+1*1^("):
                    o = self.out(if_ + "A=" + body * n + "1" + ")" * n + "\nRUN\n")
                    self.assertTrue(o == "" or "TOO" in o, (ni, n, body, o))   # or LINE TOO LONG
        # a mix found by a fuzz, 68 characters: it overflowed a frame stack sized by parentheses alone
        self.out("10 A=1OR1AND1<1+(1+1*1^(1+1*1^(1+1*1^(NOT(1^(1OR(NOT ABS(1))))))))\nRUN\n")
        self.assertEqual(self.out("10 " + "IF 1 THEN " * 4 + "A=" + "1+(" * 2 + "1" + ")" * 2 + ":PRINT A\nRUN\n"), " 3 \n")

    def test_bytes_free(self):
        self.assertEqual(self.out("", tty=True), FREE + "READY.\n")


if __name__ == "__main__":
    unittest.main()
