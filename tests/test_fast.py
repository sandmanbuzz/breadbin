"""The fast module (src/mod/fast.s): whole-block transfer with code uploaded to a stock 1541.

With a stock drive ROM the module must install its drive code (checked in the drive's RAM), carry
the blocks of a copy in both directions (the copies are compared byte for byte on the host) and
let go again on unload. With a JiffyDOS drive ROM it may refuse the drive; the copies must be
exact either way. BREADBIN_FAST_BENCH=1 runs at real speed and prints emulated times, with the
module and without.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402
import mkimage  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")
MOD = os.path.join(ROOT, "build", "mod")
JIFFY_DRIVE = "JiffyDOS_1541" in os.environ.get("BREADBIN_VICE_ARGS", "")
BENCH = bool(os.environ.get("BREADBIN_FAST_BENCH"))
PAL_HZ = 985248
DRV = 0x0400


def blob():
    """The drive code as the module holds it (None when the module is not built)."""
    try:
        with open(os.path.join(MOD, "fast.lbl")) as f:
            lbl = {m.group(2): int(m.group(1), 16)
                   for m in (re.match(r"al ([0-9A-F]{6}) \.(\S+)", ln) for ln in f) if m}
        with open(os.path.join(MOD, "fast.0"), "rb") as f:
            img = f.read()
    except OSError:
        return None
    return img[lbl["blob"]:lbl["blob"] + lbl["d_end"] - DRV]


def labels():
    with open(os.path.join(MOD, "fast.lbl")) as f:
        return {m.group(2): int(m.group(1), 16)
                for m in (re.match(r"al ([0-9A-F]{6}) \.(\S+)", ln) for ln in f) if m}


def cycles(v):
    out = v._cmd("sw")
    v._cmd("x")
    return int(re.search(r"Stopwatch:\s*(\d+)", out).group(1))


def drive_mem(v, start, end):
    out = v._cmd("m 8:%04x 8:%04x" % (start, end), wait=0.3)
    v._cmd("x")
    mem = {}
    for ln in out.split("\n"):
        m = re.match(r"^>8:([0-9a-f]{4})\s+((?:[0-9a-f]{2}\s+){1,16})", ln)
        if m:
            for i, h in enumerate(m.group(2).split()):
                mem[int(m.group(1), 16) + i] = int(h, 16)
    return bytes(mem.get(a, 0x100) & 0xff for a in range(start, end + 1)) if len(mem) > end - start else None


@unittest.skipIf(blob() is None, "the fast module is not built (JIFFY=0)")
class Fast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_fast.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = Vice(cls.img, warp=not BENCH)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def timed(self, what, cmd):
        t0 = cycles(self.v)
        out = self.v.run(cmd, timeout=900)
        if BENCH:
            print(f"\n{what}: {cmd}: {(cycles(self.v) - t0) / PAL_HZ:.1f} emulated s", file=sys.stderr)
        return out

    def test_1_copies_are_exact_and_the_drive_code_is_used(self):
        v = self.v
        if BENCH:
            self.timed("standard", "wc /bin/as")
            self.timed("standard", "cp /bin/basic /home/f0")
        self.assertEqual(v.run("mod load /lib/km/fast"), "")
        self.assertEqual(self.timed("fast", "wc /bin/as").split()[:1], v.run("wc /bin/as").split()[:1])
        code = blob()
        got = drive_mem(v, DRV, DRV + len(code) - 1)
        self.assertIsNotNone(got, "drive memory dump")
        # the self-modified operands and the variables differ; the first 32 bytes hold neither
        installed = got[:6] == code[:6]
        if not JIFFY_DRIVE:
            self.assertTrue(installed, "the drive code is not in the stock drive's RAM")
        print(f"\nfast: drive code installed: {installed} (JiffyDOS drive ROM: {JIFFY_DRIVE})", file=sys.stderr)
        self.assertEqual(self.timed("fast", "cp /bin/basic /home/f1"), "")
        self.assertEqual(v.run("cp /home/f1 /home/f2", timeout=900), "")
        self.assertEqual(v.run("rm /home/f1"), "")              # frees and rewrites metadata
        self.assertEqual(v.run("cp /home/f2 /home/f3", timeout=900), "")
        ls = v.run("mod ls")
        self.assertIn("fast", ls)
        # the module's counters: every block went the fast way, none fell back
        lbl, base = labels(), int(re.search(r"page (\d+)", ls).group(1)) << 8
        nf = v.mem(base + lbl["ft_nf"], base + lbl["ft_nf"])[0]
        ng = v.mem(base + lbl["ft_ng"], base + lbl["ft_ng"] + 1)
        ng = ng[0] | ng[1] << 8
        state = v.mem(base + lbl["state"], base + lbl["state"])[0]
        print(f"fast: state {state:#x}, blocks carried {ng}, fallen back {nf}", file=sys.stderr)
        if installed:
            self.assertEqual((state, nf), (1, 0))
            self.assertGreater(ng, 300)
        else:
            self.assertEqual((state, ng), (0x80, 0))
        slot = re.search(r"slot (\d+):[^\n]*fast", ls).group(1)
        self.assertEqual(v.run("mod unload " + slot), "")
        self.assertNotIn("fast", v.run("mod ls"))
        self.assertEqual(v.run("cp /home/f3 /home/f4", timeout=900), "")     # the standard path again
        v.close()
        fs = mkimage.FS(mkimage.load(self.img))
        want = fs.read_file(fs.lookup("/bin/basic"))
        for name in ("f2", "f3", "f4"):
            self.assertEqual(fs.read_file(fs.lookup("/home/" + name)), want, name)
        with self.assertRaises(FileNotFoundError):
            fs.lookup("/home/f1")
