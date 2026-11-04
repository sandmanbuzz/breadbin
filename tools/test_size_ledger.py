"""Host-only tests for tools/size_ledger.py: the figures are parsed from `make size` text, KSTART from k.inc,
and each run appends one line (with the header once). No build, no emulator.

    python3 -m unittest discover -s tools -p 'test_size_ledger.py'
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import size_ledger  # noqa: E402

# make size on main 45eacff (2026-11-03), copied from the output; the figures the ledger must read back
SIZE = """uci              0      12      48      76       0       1     137
khash            0       2       0       0       0       0       2
total        10498     600      68    2069    1141    6103   20479
INIT (boot-only, runs from the load area and is then released to the user pool): 1141 bytes

code and data end at $CD9D; room below $CF00: 354 bytes
BSS and CODEHI end at $FFEB; room below $FFFA: 14 bytes
largest programs: as 6116, basic 5150, sh 3682, passwd 2339, edit 2099, format 1973
"""

K_INC = "KSTART  = $A200     ; must match KRAM in kernel.cfg: the user pool is $0800-KSTART-1\n"


class Parse(unittest.TestCase):
    def test_figures_from_make_size(self):
        fig = size_ledger.parse_size(SIZE)
        self.assertEqual(fig["code_end"], 0xCD9D)
        self.assertEqual(fig["room_below_cf00"], 354)
        self.assertEqual(fig["bss_codehi_end"], 0xFFEB)
        self.assertEqual(fig["room_below_fffa"], 14)
        self.assertEqual(fig["modules_total"], 20479)
        self.assertEqual(fig["init"], 1141)
        self.assertEqual(fig["bss"], 6103)

    def test_kstart_from_k_inc(self):
        self.assertEqual(size_ledger.parse_kstart(K_INC), 0xA200)

    def test_missing_total_row_is_an_error(self):
        with self.assertRaises(ValueError):
            size_ledger.parse_size("code and data end at $CD9D; room below $CF00: 354 bytes\n")

    def test_missing_code_end_line_is_an_error(self):
        with self.assertRaises(ValueError):
            size_ledger.parse_size("total        10498     600      68    2069    1141    6103   20479\n")

    def test_missing_kstart_is_an_error(self):
        with self.assertRaises(ValueError):
            size_ledger.parse_kstart("KRAM = 1\n")


class Ledger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ledger = os.path.join(self.dir, "size-ledger.tsv")
        self.inc = os.path.join(self.dir, "k.inc")
        open(self.inc, "w").write(K_INC)
        self.size = os.path.join(self.dir, "size.txt")
        open(self.size, "w").write(SIZE)

    def run_tool(self, commit):
        size_ledger.main(["--commit", commit, "--size-file", self.size, "--ledger", self.ledger,
                          "--kernel-inc", self.inc])

    def test_first_run_writes_header_and_one_line(self):
        self.run_tool("45eacff")
        rows = open(self.ledger).read().splitlines()
        self.assertEqual(rows[0].split("\t"), size_ledger.HEADER)
        self.assertEqual(len(rows), 2)
        cols = dict(zip(size_ledger.HEADER, rows[1].split("\t")))
        self.assertEqual(cols["commit"], "45eacff")
        self.assertEqual(cols["kstart"], "$A200")
        self.assertEqual(cols["code_end"], "$CD9D")
        self.assertEqual(cols["room_below_cf00"], "354")
        self.assertEqual(cols["bss_codehi_end"], "$FFEB")
        self.assertEqual(cols["room_below_fffa"], "14")
        self.assertEqual(cols["modules_total"], "20479")

    def test_second_run_appends_without_a_second_header(self):
        self.run_tool("45eacff")
        self.run_tool("0123456")
        rows = open(self.ledger).read().splitlines()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].split("\t"), size_ledger.HEADER)
        self.assertEqual(rows[2].split("\t")[0], "0123456")

    def test_a_size_change_shows_in_the_new_row(self):
        self.run_tool("45eacff")
        open(self.size, "w").write(SIZE.replace("room below $CF00: 354", "room below $CF00: 340"))
        self.run_tool("ffff000")
        rows = open(self.ledger).read().splitlines()
        self.assertEqual(rows[1].split("\t")[3], "354")
        self.assertEqual(rows[2].split("\t")[3], "340")


if __name__ == "__main__":
    unittest.main()


class Programs(unittest.TestCase):
    def test_one_row_per_cx_file_with_one_header(self):
        with tempfile.TemporaryDirectory() as d:
            bindir = os.path.join(d, "bin")
            os.mkdir(bindir)
            open(os.path.join(bindir, ".keep"), "w").close()     # a placeholder, not a program
            for name, n in (("sh", 3682), ("as", 6704)):
                with open(os.path.join(bindir, name), "wb") as f:
                    f.write(b"x" * n)
            ledger = os.path.join(d, "programs.tsv")
            rows = size_ledger.append_programs(ledger, "abc1234", bindir)
            self.assertEqual(rows, [("abc1234", "as", 6704), ("abc1234", "sh", 3682)])
            size_ledger.append_programs(ledger, "def5678", bindir)
            lines = open(ledger).read().splitlines()
            self.assertEqual(lines[0], "\t".join(size_ledger.PROGRAM_HEADER))
            self.assertEqual(len(lines), 1 + 4)                  # header once, two rows per run
            self.assertEqual(lines[1], "abc1234\tas\t6704")
            self.assertEqual(lines[4], "def5678\tsh\t3682")

