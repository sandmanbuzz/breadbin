"""The JiffyDOS byte protocol in the kernel's serial driver (src/kernel/iec.s).

The same test runs with either drive ROM: a JiffyDOS drive (BREADBIN_CI_JIFFY, docs/testing.md)
must answer the probe and carry every byte over the fast protocol, a stock drive must not answer
and nothing may change. Either way a file copied on the machine is compared byte for byte on the
host, which checks both directions (the read of the source, the write of the copy).
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
JIFFY_DRIVE = "JiffyDOS_1541" in os.environ.get("BREADBIN_VICE_ARGS", "")
# BREADBIN_JIFFY_BENCH=1 runs the emulator at real speed and prints the emulated time of the
# copy: in warp the harness polls the screen too coarsely (tens of emulated seconds) to time it.
BENCH = bool(os.environ.get("BREADBIN_JIFFY_BENCH"))
PAL_HZ = 985248


def label(name):
    with open(os.path.join(ROOT, "build", "kernel.lbl")) as lbl:
        for ln in lbl:
            f = ln.split()
            if len(f) == 3 and f[2] == "." + name:
                return int(f[1], 16)
    return None


def cycles(v):
    """The emulator's cycle counter (the monitor's stopwatch)."""
    out = v._cmd("sw")
    v._cmd("x")
    return int(re.search(r"Stopwatch:\s*(\d+)", out).group(1))


class Jiffy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_jiffy.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = Vice(cls.img, warp=not BENCH)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def test_1_probe_matches_the_drive(self):
        a = label("io_jif")
        if a is None:
            self.skipTest("kernel built with JIFFY=0")
        self.v.run("ls /bin")       # a session with the drive
        jif = self.v.mem(a, a)[0] & 0x80 == 0
        self.assertEqual(jif, JIFFY_DRIVE, "probe result does not match the drive ROM")

    def test_1b_sprites_on_keep_the_standard_protocol(self):
        """A sprite steals cycles from the timed windows: with one on at the start of a
        session the driver stays on the standard protocol, even with a JiffyDOS drive."""
        a = label("io_jif")
        if a is None:
            self.skipTest("kernel built with JIFFY=0")
        try:
            self.v._cmd(">d015 01")
            self.v._cmd("x")
            self.v.run("ls /bin")
            self.assertTrue(self.v.mem(a, a)[0] & 0x80, "a sprite was on and the probe still ran")
        finally:
            self.v._cmd(">d015 00")
            self.v._cmd("x")
        self.v.run("ls /bin")
        self.assertEqual(self.v.mem(a, a)[0] & 0x80 == 0, JIFFY_DRIVE)

    def test_2_copy_is_exact(self):
        rom = "JiffyDOS" if JIFFY_DRIVE else "stock"
        if BENCH:
            t0 = cycles(self.v)
            self.v.run("wc /bin/as", clear=False, timeout=900)
            print(f"\nwc /bin/as: {(cycles(self.v) - t0) / PAL_HZ:.1f} emulated s ({rom} drive ROM)", file=sys.stderr)
        t0 = cycles(self.v)
        self.v.run("cp /bin/basic /home/j1", timeout=900)
        if BENCH:
            print(f"cp /bin/basic: {(cycles(self.v) - t0) / PAL_HZ:.1f} emulated s ({rom} drive ROM)", file=sys.stderr)
        self.v.run("cp /home/j1 /home/j2", timeout=900)
        self.v.close()
        fs = mkimage.FS(mkimage.load(self.img))
        want = fs.read_file(fs.lookup("/bin/basic"))
        self.assertEqual(fs.read_file(fs.lookup("/home/j1")), want)
        self.assertEqual(fs.read_file(fs.lookup("/home/j2")), want)
