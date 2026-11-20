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

SRC = os.path.join(ROOT, "experiments", "con80", "con80.s")
FONT, BMP, CODE = 0x4000, 0x2000, 0x4800
CFG = """MEMORY { M: start = $4800, size = $1000, file = %O; B: start = $5800, size = $400, file = ""; }
SEGMENTS { CODE: load = M, type = ro; RODATA: load = M, type = ro; BSS: load = B, type = bss; }
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
        s.mem.b[0x5800:0x5C00] = bytes(0x400)
        s.mem.b[FONT:FONT + 2048] = m.planar(self.font)
        s.lbl.update(self.lab)
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
        pieces = ["\n" * 30, "x" * 160, "\x1b", "\f", "ab\n" * 12, "z" * 79, "\n", "q" * rnd.randrange(200, 400)]
        for _ in range(40):
            self.feed("".join(rnd.choice(pieces) for _ in range(rnd.randrange(1, 6))))
            self.same()

    def test_one_byte_writes(self):
        self.feed("abc\ndef\n" * 20, chunk=1)
        self.same()


if __name__ == "__main__":
    unittest.main()
