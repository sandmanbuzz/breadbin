"""Host test: the con80 tech demo PRG (tools/con80_demo.py) run on a bare 6502 in py65 plays its
whole script and leaves the same bitmap as the host model's replay; the VIC setup writes are seen.
The font is synthetic: the point is the player, the encoding and the layout.

    python -m unittest tools.test_con80_demo -v   (needs py65 and cc65)
"""
import os
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from py65.devices.mpu6502 import MPU
    from py65.memory import ObservableMemory
    HAVE = bool(shutil.which("ca65") and shutil.which("ld65"))
except ImportError:
    HAVE = False
import con80_demo as d  # noqa: E402
import soft80_render as m  # noqa: E402


@unittest.skipUnless(HAVE, "needs py65 and cc65")
class Demo(unittest.TestCase):
    def test_script_parse_and_encode(self):
        ops = d.parse("# hi\n$ ls\nabc\ndef\n@each\nx\ny\n@end\n@wait 300\n@clear\n")
        self.assertEqual(ops[0], ("type", 1, "# hi\n"))
        self.assertIn(("write", "abc\ndef\n"), ops)
        self.assertEqual([o for o in ops if o[0] == "write"][-2:], [("write", "x\n"), ("write", "y\n")])
        enc = d.encode(ops)
        self.assertEqual(enc[-1], 0)
        self.assertEqual(enc.count(bytes([d.OP_WAIT, 255])), 1)       # 300 = 255 + 45

    def test_prg_plays_script_like_the_model(self):
        with open(os.path.join(d.SRC, "demo.txt")) as f:
            ops = d.parse(f.read())
        r = random.Random(5)
        font = bytes(((n := r.randrange(16)) << 4) | n for _ in range(2048))
        with tempfile.TemporaryDirectory() as tmp:
            prg = d.build(font, ops, tmp)
        self.assertEqual(prg[:2], b"\x01\x08")
        mem = ObservableMemory()
        raster = [11]

        def d012(addr):
            raster[0] = (raster[0] + 16) & 255
            return raster[0]
        mem.subscribe_to_read([0xD012], d012)
        writes = {}
        mem.subscribe_to_write([0xD011, 0xD018, 0xD020], lambda a, v: writes.__setitem__(a, v))
        body = prg[2:]
        for i, b in enumerate(body):
            mem[0x0801 + i] = b
        cpu = MPU(memory=mem, pc=0x5000)
        last, n = None, 0
        while n < 60_000_000:
            cpu.step()
            n += 1
            if cpu.pc == last:
                break
            last = cpu.pc
        else:
            self.fail("script did not finish")
        self.assertEqual(writes, {0xD011: 0x3B, 0xD018: 0x18, 0xD020: d.BORDER})
        model = d.replay(ops, font)
        got = bytes(mem[0x2000 + i] for i in range(8000))
        self.assertEqual(got, bytes(model.bitmap))
        self.assertTrue(all(mem[0x0400 + i] == d.COLOUR for i in range(1000)))


if __name__ == "__main__":
    unittest.main()
