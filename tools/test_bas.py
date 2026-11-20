"""bas (src/pc/bas.c), the compiled BASIC, slice L3b (docs/design/basic.md section 5): built from
the mini C with cc.py --pcode, run under py65 (tools/asim.py) with /lib/pvm. Needs ca65, ld65 and
py65 (the container image has them)."""
import os
import re
import tempfile
import unittest

import asim
import pvmlink
import test_cc_pcode
import test_pvm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "pc", "bas.c")
_built = {}


def binary():
    if "path" not in _built:
        _built["dir"] = tempfile.TemporaryDirectory(prefix="bas-")
        with open(SRC) as f:
            _built["path"] = test_cc_pcode.build(f.read(), _built["dir"].name)
    return _built["path"]


def bas(text, tty=False, limit=40_000_000):
    """bas with text on stdin: (output as str, exit status)."""
    r = asim.run("bas", [], path=binary(), libs={pvmlink.LIBPATH: os.path.join(test_pvm.lib_dir(), "pvm")},
                 stdin=text.encode("latin-1"), tty=tty, limit=limit)
    return r.out.decode("latin-1"), r.exit


@unittest.skipUnless(test_pvm.HAVE_TOOLS, "needs ca65, ld65 and py65")
class Bas(unittest.TestCase):
    def out(self, text, **kw):
        out, status = bas(text, **kw)
        self.assertEqual(status, 0, out)
        return out

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
        self.assertEqual(out, '10 REM x\n20 PRINT "a  b" : REM  Keep  THIS  \n30 ?"q":REM Q\n40 PRINT "x" : REM\n')

    def test_tabs_unclosed_strings_and_spaced_line_numbers(self):
        # a tab is a space outside quotes; an unclosed string keeps its trailing spaces; spaces
        # among a line number's digits are skipped, as MS's CHRGET does
        out = self.out('10\tPRINT\t"A\tB";\n20 PRINT "C   \n1 5 ?"D"\n3 0 REM X \nLIST\nLIST 1 5\nRUN\n')
        self.assertEqual(out, '10 PRINT "A\tB";\n15 ?"D"\n20 PRINT "C   \n30 REM X \n15 ?"D"\nA\tBD\nC   \n')

    def test_ready_and_errors_start_a_fresh_line(self):
        self.assertEqual(self.out('?"A";\n10 ?"B";\nRUN\n?"C";:FOO\n', tty=True),
                         "READY.\nA\nREADY.\nB\nREADY.\n?SYNTAX ERROR\nREADY.\n")
        self.assertEqual(self.out('?"A";\nFOO\n'), "A\n?SYNTAX ERROR\n")

    def test_immediate_mode_after_a_large_run(self):
        # the program's code fills most of the buffer; a typed line that does not fit after it
        # is compiled at the start instead, and RUN still works
        line = ":".join(['?"A";'] * 26)
        prog = "".join("%d %s\n" % (n, line) for n in range(1, 12)) + "12 ?\n"
        out = self.out(prog + 'RUN\n?"' + "X" * 150 + '"\nRUN\n')
        self.assertEqual(out, "A" * 286 + "\n" + "X" * 150 + "\n" + "A" * 286 + "\n")

    def test_line_store_sorts_replaces_and_deletes(self):
        out = self.out('30 ?"C"\n10 ?"A"\n20 ?"B"\n20 ?"BB"\n40 ?"D"\n30\n35\nLIST\nRUN\n')
        self.assertEqual(out, '10 ?"A"\n20 ?"BB"\n40 ?"D"\nA\nBB\nD\n')

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
        self.assertEqual(self.out('10 PRINT "A"\n20 PRINT X\n30 PRINT "C"\nRUN\n'), "?SYNTAX ERROR IN 20\n")
        self.assertEqual(self.out('10 PRINT "A" X\nRUN\n'), "?SYNTAX ERROR IN 10\n")
        self.assertEqual(self.out('40000 GOTO 10\nRUN\n'), "?SYNTAX ERROR IN 40000\n")

    def test_bad_commands(self):
        for line in ("LIST X", "LIST 10-20-30", "NEW 5", "RUN X", "FOO", "PRINT 5", "LISTX"):
            self.assertEqual(self.out(line + "\n"), "?SYNTAX ERROR\n", line)

    def test_ready_only_on_a_terminal(self):
        self.assertEqual(self.out('?"A"\n10 ?"B"\n\nFOO\n', tty=True), "READY.\nA\nREADY.\n?SYNTAX ERROR\nREADY.\n")
        self.assertEqual(self.out('?"A"\n', tty=False), "A\n")

    def test_bye_and_end_of_input(self):
        self.assertEqual(self.out('?"A"\nBYE\n?"B"\n'), "A\n")
        self.assertEqual(self.out('?"A"\nSYSTEM\n?"B"\n'), "A\n")
        self.assertEqual(self.out('?"A"'), "A\n")                  # the last line has no newline
        self.assertEqual(self.out('?"A"\r\n?"B"\r\n'), "A\nB\n")
        self.assertEqual(self.out(""), "")

    def test_a_line_too_long(self):
        self.assertEqual(self.out('?"' + "X" * 157 + '"\n'), "X" * 157 + "\n")    # 160 is the most
        self.assertEqual(self.out('?"' + "X" * 158 + '"\n?"OK"\n'), "?LINE TOO LONG ERROR\nOK\n")

    def test_long_strings_and_many_statements(self):
        # CS and CALL each reset the VM's Y, so PRINT's code never runs straight past 240 bytes
        # and room() cannot fire yet: its test comes with L3c's expressions (mutating it now
        # passes this test)
        s = "".join(chr(33 + i % 90).replace('"', "'") for i in range(150))
        prog = "".join('%d ?"%s%d";\n' % (n, s, n) for n in range(1, 11)) + "100 ?\n"
        prog += "200 " + ":".join('?"%s";' % chr(65 + i % 26) for i in range(26)) + "\n210 ?\n"
        want = "".join(s + str(n) for n in range(1, 11)) + "\n" + "".join(chr(65 + i) for i in range(26)) + "\n"
        self.assertEqual(self.out(prog + "RUN\n"), want)

    def test_out_of_memory(self):
        # the program store (4096 bytes)
        prog = "".join('%d ?"%s"\n' % (n, "Y" * 60) for n in range(1, 70))
        out = self.out(prog + 'LIST 1\n')
        self.assertIn("?OUT OF MEMORY ERROR\n", out)
        self.assertTrue(out.endswith('1 ?"' + "Y" * 60 + '"\n'))
        # the code buffer (2048 bytes): ?"A"; is 5 bytes of text and 7 of code; the error names
        # the line being compiled, and the store is unhurt
        line = ":".join(['?"A";'] * 26)
        prog = "".join("%d %s\n" % (n, line) for n in range(1, 25))
        self.assertEqual(self.out(prog + 'RUN\n?"STILL"\nLIST 24\n'),
                         "?OUT OF MEMORY ERROR IN 12\nSTILL\n24 " + line + "\n")

    def test_opcode_numbers_agree_with_the_vm(self):
        inc = open(os.path.join(ROOT, "src", "pvm", "pvm.inc")).read()
        ops = {m.group(1): int(m.group(2), 16) for m in re.finditer(r"^(PO_\w+)\s*=\s*\$([0-9A-F]+)", inc, re.M)}
        src = open(SRC).read()
        used = re.findall(r"(\d+) /\* (PO_\w+)( \d+)? \*/", src)
        self.assertGreaterEqual(len(used), 6)
        for num, name, arg in used:
            want = 2 * int(arg) if name == "PO_CN" else ops[name]
            self.assertEqual(int(num), want, name)


if __name__ == "__main__":
    unittest.main()
