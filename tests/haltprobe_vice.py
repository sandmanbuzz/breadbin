"""VICE proof for experiments/iec-stall/haltprobe.s (not discovered by the suite: no test_ prefix).

    tools/ci/run.sh test-only T="tests.haltprobe_vice"

Boots the stock KERNAL's BASIC with no disk, loads the probe at $C000 through the monitor, runs it
with a time limit (LIMIT units of 65536 cycles) and prints the results block: screen on, screen
blanked, and, with an REU, REU mode. VICE's timing is cycle exact, so the expected shape is:
blanked -> every loop in the quiet bucket; on -> stolen cycles up to the badline (~40-43) and a
few more; REU -> a 256-byte transfer shows as a gap of about 256+ cycles.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(root, "tools"))
sys.path.insert(0, os.path.join(root, "experiments", "iec-stall"))
import haltprobe as hp  # noqa: E402
import vicetest  # noqa: E402


class Bare(vicetest.Vice):
    """VICE at BASIC with no disk."""

    def __init__(self, reu=False):
        self.image = None
        self.port = vicetest._free_port()
        args = [vicetest.X64, "-default", "+sound", "-minimized", "-warp",
                "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{self.port}"]
        if reu:
            args += ["-reu", "-reusize", "512"]
        self.log = tempfile.NamedTemporaryFile(prefix="vice", suffix=".log", delete=False)
        self.proc = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT)
        self.sock = None
        import socket
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                break
            except OSError:
                time.sleep(0.3)
        if not self.sock:
            raise RuntimeError("could not connect to VICE monitor")
        self._cmd("x")
        self.wait_for("ready.", timeout=30)


def probe(v, mode, limit=300, reuev=1, reulen=0):
    code = hp.assemble()
    f = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
    f.write(b"\x00\xc0" + code)       # the monitor's load takes a PRG header
    f.close()
    v._cmd(f'l "{f.name}" 0 c000')
    v._cmd("x")
    cfg = [mode, 0, limit & 255, limit >> 8, reuev, 0, reulen & 255, reulen >> 8]
    v._cmd("> c800 " + " ".join(f"{b:02x}" for b in cfg))
    v._cmd("x")
    v.type("sys49152\n")
    for _ in range(40):
        time.sleep(0.5)
        if v.mem(hp.RES, hp.RES)[0] == 1:
            break
    else:
        raise TimeoutError("probe did not finish")
    return hp.parse(bytes(v.mem(hp.RES, hp.RES + 0x43)))


def show(name, r):
    b = r["buckets"]
    loops = sum(b)
    elapsed = (0xFFFF - r["timer_b"]) * 65536 + (0xFFFF - r["timer_a_end"])
    print(f"\n== {name}: loops {loops}, elapsed {elapsed} cycles, cycles/loop {elapsed / max(loops, 1):.3f}, "
          f"max delta {r['max']} (stolen {max(r['max'] - r['p'], 0)}), REU present {r['reu_present']}, xfers {r['xfers']}")
    print("   " + "  ".join(f"{l}:{c}" for l, c in zip(hp.LABELS, b)), flush=True)


class Halt(unittest.TestCase):
    def test_1_screen_blanked(self):
        with Bare() as v:
            r = probe(v, hp.FLAG_BLANK)
        show("screen blanked", r)
        self.assertTrue(r["done"])
        self.assertEqual(sum(r["buckets"][1:]), 0)

    def test_2_screen_on(self):
        with Bare() as v:
            r = probe(v, 0)
        show("screen on", r)
        self.assertTrue(r["done"])
        self.assertEqual(sum(r["buckets"][4:]), 0)
        self.assertGreater(sum(r["buckets"][1:4]), 0)

    def test_3_reu_blanked(self):
        with Bare(reu=True) as v:
            r = probe(v, hp.FLAG_BLANK | hp.FLAG_REU)
        show("REU, screen blanked", r)
        self.assertEqual(r["reu_present"], 1)
        self.assertGreater(r["xfers"], 0)
        self.assertGreater(r["buckets"][5], 0)

    def test_3b_injected_halts_land_in_the_right_bucket(self):
        # an REU transfer of N bytes steals about N cycles: the histogram must put N = 150, 256,
        # 600 and 1200 into buckets 101-200, 201-400, 401-800 and 801-1600 respectively
        for n, bucket in ((150, 4), (256, 5), (600, 6), (1200, 7)):
            with Bare(reu=True) as v:
                r = probe(v, hp.FLAG_BLANK | hp.FLAG_REU, reulen=n)
            show(f"injected {n}-byte halt", r)
            b = r["buckets"]
            self.assertGreater(r["xfers"], 3)
            self.assertAlmostEqual(b[bucket], r["xfers"], delta=2, msg=f"bucket {bucket} for {n}")
            self.assertEqual(sum(b[1:]) - b[bucket], 0)
            self.assertTrue(n - 30 <= r["max"] - r["p"] <= n + 60, r["max"])

    def test_4_no_reu_mode_is_inert(self):
        with Bare() as v:
            r = probe(v, hp.FLAG_BLANK | hp.FLAG_REU, limit=100)
        show("REU mode, no REU", r)
        self.assertEqual(r["reu_present"], 0)
        self.assertEqual(r["xfers"], 0)
        self.assertEqual(sum(r["buckets"][1:]), 0)
