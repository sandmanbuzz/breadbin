"""The 6502 soft 80-column core (experiments/con80/con80.s) against the host model
(tools/soft80_render.py), in py65 on the real kernel image: same text in, same bitmap,
high-water marks and cursor out.

    python -m unittest tools.test_con80_sim -v   (needs py65, cc65 and a built build/breadbin.prg)
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import py65  # noqa: F401
    from uci_sim import Sim, BUILD, ROOT
    HAVE = os.path.exists(os.path.join(BUILD, "breadbin.prg")) and shutil.which("ca65") and shutil.which("ld65")
except ImportError:
    HAVE = False
import soft80_render as m  # noqa: E402

SRC = os.path.join(ROOT, "src", "mod", "con80.inc")
FONT, BMP, CODE = 0x4000, 0x2000, 0x4800
CFG = """MEMORY { M: start = $4800, size = $1000, file = %O; }
SEGMENTS { CODE: load = M, type = ro; RODATA: load = M, type = ro; }
"""
SYMS = ("p1", "p2", "p3", "p4", "tmp0", "tmp1", "tmp2", "tmp3", "to_screen")


def build(sim, tmp):
    with open(os.path.join(tmp, "kernel_syms.inc"), "w") as f:
        f.write("r0 = $02\nr1 = $04\n")
        for n in SYMS:
            f.write("%s = $%04X\n" % (n, sim.lbl[n]))
    cfg, obj, out, lbl = (os.path.join(tmp, x) for x in ("c.cfg", "c.o", "c.bin", "c.lbl"))
    with open(cfg, "w") as f:
        f.write(CFG)
    subprocess.run(["ca65", "-I", tmp, "-o", obj, SRC], check=True)
    subprocess.run(["ld65", "-C", cfg, "-Ln", lbl, "-o", out, obj], check=True)
    labels = {}
    with open(lbl) as f:
        for line in f:
            _, addr, name = line.split()
            labels[name.lstrip(".")] = int(addr, 16)
    with open(out, "rb") as f:
        return f.read(), labels


@unittest.skipUnless(HAVE, "needs py65, cc65 and a built kernel image")
class Con80(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.sim = Sim()
        cls.bin, cls.lab = build(cls.sim, cls.tmp)
        # a synthetic doubled-nibble font: the point is that model and 6502 agree, not the look
        r = random.Random(5)
        cls.font = bytes(((n := r.randrange(16)) << 4) | n for _ in range(2048))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def setUp(self):
        s = self.sim
        s.mem.b[CODE:CODE + len(self.bin)] = self.bin
        s.mem.b[FONT:FONT + m.NGLYPH * 4] = m.glyphs(self.font)
        s.lbl.update(self.lab)
        s.mem.b[0x286], s.mem.b[0xD021], s.mem.b[0xC7], s.mem.b[0xD020] = 1, 6, 0, 0
        s.call("c80_init")
        self.model = m.Soft80(self.font)

    def feed(self, text, chunk=None):
        s, rnd = self.sim, random.Random(2)
        i = 0
        while i < len(text):
            n = chunk or rnd.randrange(1, 300)
            part = text[i:i + n]
            i += n
            s.put(s.SCRATCH, part.encode("latin-1"))
            s.mem.b[2:4] = bytes([s.SCRATCH & 255, s.SCRATCH >> 8])
            s.mem.b[4:6] = bytes([len(part) & 255, len(part) >> 8])
            s.call("c80_write", limit=3_000_000)
            self.model.write(part)

    def same(self):
        b, mod = self.sim.mem.b, self.model
        self.assertEqual(bytes(b[BMP:BMP + 8000]), bytes(mod.bitmap))
        L = self.lab["lastpos"]
        self.assertEqual(list(b[L:L + 25]), mod.lastpos)
        self.assertEqual((b[0xD3], b[0xD6]), (mod.cx, mod.cy))
        self.assertEqual((b[0xC7], b[self.lab["esc_st"]]), (mod.rev, mod.esc))
        self.assertEqual(bytes(b[0x400:0x400 + 1000]), mod.colour)
        self.assertEqual(b[0xD020], mod.border)

    def test_short_text(self):
        self.feed("hello, world\nsecond line\n")
        self.same()

    def test_every_alignment_and_length(self):
        for col in range(4):
            self.feed("\f" + " " * col + "".join(chr(0x21 + i) for i in range(1, 30)) + "\n")
            self.same()

    def test_wrap_at_80_and_scroll(self):
        self.feed(("x" * 79 + "\n") * 3 + "y" * 200 + "\n" * 2)
        self.same()

    def test_flood_with_look_ahead(self):
        rnd = random.Random(9)
        text = "".join("".join(chr(rnd.randrange(0x20, 0x7F)) for _ in range(rnd.randrange(0, 90)))
                       + "\n" * rnd.choice((1, 1, 1, 2, 5, 30)) for _ in range(60))
        self.feed(text)
        self.same()

    def test_controls_tab_ff_and_skips(self):
        self.feed("a\tb\x01\x02`c\x7f{|~\fafter clear\n\n\nmore")
        self.same()

    def test_look_ahead_edges(self):
        rnd = random.Random(4)
        pieces = ["\n" * 30, "x" * 160, "\x1b", "\f", "\n\b\n", "\b", "ab\n" * 12, "z" * 79, "\n", "q" * rnd.randrange(200, 400)]
        for _ in range(40):
            self.feed("".join(rnd.choice(pieces) for _ in range(rnd.randrange(1, 6))))
            self.same()

    def test_reverse_bs_and_escapes(self):
        self.feed("plain \x1bRrev\x1br back\x1bR rev wrap\nnext line is plain\n")
        self.same()
        self.feed("abc\b\bX\x08\x08\x08\x08\x08\nline\n\b\b\b\bq\b\b\b\b\b\b\bzz")
        self.same()
        self.feed("\f\x1b=%'at 5,7\x1b=  home\x1b=~~clamped\x1b=\x1f\x1fbelow-range")
        self.same()

    def test_clear_to_end_of_line(self):
        for col in range(0, 12):
            self.feed("\f" + "0123456789ab\n" * 3 + "\x1b=%d%d" % (32 + 1, 32 + col) + "\x1bK\x1bR!")
            self.same()
        self.feed("\f" + "x" * 79 + "\x1b=  \x1bKshort")      # row drawn to 79 then cleared from 0
        self.same()
        self.feed("\x1b=\x2f\x70\x1bK")                     # K at a column past the drawn part
        self.same()

    def test_bs_ends_the_look_ahead(self):
        self.feed(("row\n") * 30 + "last")            # cursor on the bottom row
        self.same()
        self.feed("\n\b\n\b\n" + "z" * 5 + "\n\n\b")
        self.same()

    def test_clear_to_end_stays_in_the_row(self):
        self.feed("\f" + ("w" * 79 + "\n") * 5 + "\x1b=#\x5c\x1bK")    # row 3, column 60
        self.same()

    def test_colours(self):
        self.feed("hi\x1bC\x2a\x2b\x2cthere\x1bC\x31\x32\x33")
        self.same()

    def test_escape_split_across_writes(self):
        for chunk in (1, 2, 3):
            self.feed("\f\x1b=#%dabc\x1bR rev\x1b=  \x1bK\x1bCabc" * 3 + "\x1br\x1bQz\x1b", chunk=chunk)
            self.same()

    def test_braces_bar_tilde_glyphs(self):
        # { | } ~ print their own glyphs ($65-$68), not '?'; the 6502 (sc80) and the model agree
        self.feed("\f" + "{|}~ x{}~|")
        self.same()
        self.assertEqual([m.screen_code(c) for c in '{|}~?'], [0x65, 0x66, 0x67, 0x68, 0x3F])

    def test_stray_cur_vis_toggles_once(self):
        # c40_show and c40_hide test cur_vis for nonzero (drawn); a stray nonzero value must not make
        # show toggle a cursor that is already drawn, and hide must leave it canonical 0
        s, cv = self.sim, self.lab["lastpos"] + 114   # standalone cur_vis: an equate after lastpos (con80.inc BSS tail)
        self.feed("\f" + "ab")
        s.call("c80_curshow"); self.model.cursor(); self.same()
        s.mem.b[cv] = 0x02
        s.call("c80_curshow"); self.same()                     # already drawn: no toggle
        s.call("c80_curhide"); self.model.cursor(); self.same()
        self.assertEqual(s.mem.b[cv], 0)

    def test_cursor_is_xor_of_the_half_cell(self):
        s = self.sim
        for text in ("", "ab", "abc", "\n\n\x1b=\x2f\x70xyz"):
            self.feed("\f" + text)
            before = bytes(self.sim.mem.b[BMP:BMP + 8000])
            s.call("c80_curshow"); s.call("c80_curshow"); self.model.cursor()      # idempotent
            self.same()
            s.call("c80_curhide"); s.call("c80_curhide"); self.model.cursor()
            self.same()
            for _ in range(2):
                s.call("c80_curshow"); self.model.cursor()
                self.same()
                s.call("c80_curshow"); s.call("c80_curhide"); self.model.cursor()
                self.same()
            s.call("c80_curshow"); self.model.cursor()
            self.feed("!")                      # a write hides it first
            self.same()
            self.assertEqual(self.model.cur, 0)
            del before

    def test_flood_with_everything(self):
        rnd = random.Random(21)
        pieces = ["abc", "x" * 90, "\n", "\n\n\n", "\b", "\x1bR", "\x1br", "\x1bK", "\x1b=\x25\x30", "\t", "\f",
                  "\x1bC\x25\x26\x27", "\x1b=\x39\x20", "\x1b", "q"]
        for _ in range(60):
            self.feed("".join(rnd.choice(pieces) for _ in range(rnd.randrange(1, 12))))
            self.same()

    def test_one_byte_writes(self):
        self.feed("abc\ndef\n" * 20, chunk=1)
        self.same()


if __name__ == "__main__":
    unittest.main()
