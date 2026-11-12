"""Session 5 workloads under VICE (experiments/iec-stall/session5.py): arm W's BASIC program on the stock
KERNAL against an emulated 1541 with a blank disk (and its refusal on a Breadbin disk), and arm B's `wv`
plus arm R's `cksum` and `ls /bin` under the release kernel.

The release tree is taken from .s5tree/ in the repo (untracked; a copy of the built release worktree's
build/{breadbin.prg,breadbin.d64,kernel.lbl,rev.txt,lib/breadbin.lib}, include/, src/prog.cfg,
tools/{cx.py,mkimage.py}); the tests skip without it. Run in the container:

    tools/ci/run.sh test-only T="tests.session5_vice"

Not named test_*.py on purpose: these are long experiment workloads (W and B run 300 cycles each), not
regression tests, so the suite (discover) and the shard list (tools/ci/shards.py) do not pick them up.

Times are measured on the emulated clock (TI for W, the kernel's ticks for B), so warp does not change them.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "experiments", "iec-stall"))
import session5  # noqa: E402
import vicetest  # noqa: E402
from vicetest import Vice  # noqa: E402

TREE = os.path.join(ROOT, ".s5tree")
HAVE_TREE = os.path.exists(os.path.join(TREE, "build", "breadbin.d64"))
HAVE_VICE = shutil.which(vicetest.X64) is not None
W_N = int(os.environ.get("S5_W_N", "300"))          # the protocol's N: the measurement of the cycle time is the point
B_N = int(os.environ.get("S5_B_N", "300"))


def blank_d64(name=b"S5W SCRATCH", disk_id=b"S5"):
    """An empty, formatted 1541 image (664 blocks free)."""
    data = bytearray(174848)
    spt = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
    off = [0]
    for n in spt:
        off.append(off[-1] + n * 256)
    bam = bytearray(256)
    bam[0:4] = bytes([18, 1, 0x41, 0])
    for t in range(1, 36):
        n = spt[t - 1]
        free = (1 << n) - 1
        if t == 18:
            free &= ~0b11                  # the BAM and the first directory sector
            n -= 2
        bam[4 * t:4 * t + 4] = bytes([n, free & 255, (free >> 8) & 255, free >> 16])
    bam[0x90:0xA0] = name.ljust(16, b"\xa0")
    bam[0xA0:0xA2] = b"\xa0\xa0"
    bam[0xA2:0xA4] = disk_id
    bam[0xA4] = 0xA0
    bam[0xA5:0xA7] = b"2A"
    bam[0xA7:0xAB] = b"\xa0" * 4
    data[off[17]:off[17] + 256] = bam
    data[off[17] + 256:off[17] + 512] = bytes([0, 0xFF]) + bytes(254)
    return bytes(data)


class BareVice(Vice):
    """Vice without autostart: drive 8 holds `disk`, the machine sits at READY on the stock KERNAL."""

    def __init__(self, disk, warp=True):
        self.image = disk
        self.port = vicetest._free_port()
        args = [vicetest.X64, "-default", "+sound", "-minimized", "-remotemonitor",
                "-remotemonitoraddress", f"ip4://127.0.0.1:{self.port}", "-drive8type", "1541", "-8", disk]
        if warp:
            args.append("-warp")
        self.log = tempfile.NamedTemporaryFile(prefix="vice", suffix=".log", delete=False)
        self.proc = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT)
        self.sock = None
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                import socket
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                break
            except OSError:
                time.sleep(0.3)
        if not self.sock:
            raise RuntimeError("could not connect to VICE monitor")
        self._cmd("x")

    def poke(self, address, data):
        for i in range(0, len(data), 32):
            chunk = data[i:i + 32]
            self._cmd(f"> {address + i:04x} " + " ".join(f"{b:02x}" for b in chunk), wait=0.05)
        self._cmd("x")


def run_w(disk, n, timeout):
    """W exactly as the driver does it (the program at $0801, the pointers, RUN), on the stock KERNAL."""
    prog, end = session5.tokenize(session5.w_program(n))
    v = BareVice(disk)
    try:
        v.wait_for("ready.", timeout=60)
        v.poke(session5.W_RESULT, bytes(session5.W_LEN))
        v.poke(0x0801, prog)
        ptr = bytes([end & 255, end >> 8])
        v.poke(0x2D, ptr * 3)
        v.poke(0xAE, ptr)
        assert bytes(v.mem(0x0801, 0x0801 + len(prog) - 1)) == prog, "program read back differs"
        v.type("run\n")
        v.wait_for("s5w state", timeout=timeout)
        d = session5.parse_w(bytes(v.mem(session5.W_RESULT, session5.W_RESULT + session5.W_LEN - 1)))
        return d, v.screen()
    finally:
        v.close()


@unittest.skipUnless(HAVE_VICE, "VICE not installed")
class W(unittest.TestCase):
    def test_1_write_verify_on_a_blank_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = os.path.join(tmp, "w.d64")
            with open(disk, "wb") as f:
                f.write(blank_d64())
            d, scr = run_w(disk, W_N, timeout=3600)
            print(f"\nW under VICE, stock KERNAL, N={W_N}: {d}\n{scr}", file=sys.stderr)
            self.assertEqual(session5.judge_w(d, W_N), ("pass", False), d)
            self.assertEqual(d["blocks_free"], 664)
            jiffies = (d["ti_end"] - d["ti_start"]) % 5184000
            print(f"W_CYCLE_VICE {jiffies / 60 / W_N:.3f} s per cycle ({jiffies / 60:.0f} s for {W_N}), "
                  "emulated clock", file=sys.stderr)
            # the file is gone at the end (the last scratch): no live entry in the directory sector 18/1
            dirsec = open(disk, "rb").read()[0x16500 + 256:0x16500 + 512]
            self.assertEqual([dirsec[e + 2] for e in range(0, 256, 32) if dirsec[e + 2]], [])

    @unittest.skipUnless(HAVE_TREE, "no .s5tree (release build copy)")
    def test_2_refuses_a_disk_with_no_free_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = os.path.join(tmp, "bb.d64")
            shutil.copyfile(os.path.join(TREE, "build", "breadbin.d64"), disk)
            before = open(disk, "rb").read()
            d, scr = run_w(disk, 5, timeout=300)
            self.assertEqual(session5.judge_w(d, 5), ("refused", False), d)
            self.assertEqual(d["blocks_free"], 0)
            self.assertEqual(d["done"], 0)
            self.assertIn("s5w refused", scr)
            self.assertEqual(open(disk, "rb").read(), before, "W wrote to a disk it refused")


@unittest.skipUnless(HAVE_VICE and HAVE_TREE, "VICE or .s5tree missing")
class B(unittest.TestCase):
    """The release kernel with an REU, booted from drive 8; the tools disk in drive 9."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.p = session5.tree_paths(TREE)
        cls.facts = session5.release_facts(cls.p)
        cls.labels = session5.labels_of(cls.p["lbl"])
        cls.tools = session5.build_tools(TREE, os.path.join(cls.tmp, "tools.d64"))
        cls.disk = os.path.join(cls.tmp, "bb.d64")
        shutil.copyfile(cls.p["d64"], cls.disk)
        # 2 MB as on the Ultimate: the block cache needs 11 banks above the 8 of the /tmp RAM disk, so
        # with 512 KB there is no cache and wv's cache-off read-back path would go untested
        cls.v = Vice(cls.disk, reu=2048, extra=["-drive9type", "1541", "-9", cls.tools])
        cls.v.wait_shell()
        out = cls.v.run("mount 9 /mnt")
        assert not out.strip(), out

    @classmethod
    def tearDownClass(cls):
        cls.v.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def iostat(self):
        lb = self.labels
        out = {}
        for n in session5.IO_COLS:
            b = self.v.mem(lb[n], lb[n] + 1)
            out[n] = b[0] if n == "io_nwfail" else b[0] | b[1] << 8
        return out

    def ticks(self):
        b = self.v.mem(self.labels["ticks"], self.labels["ticks"] + 2)
        return b[0] | b[1] << 8 | b[2] << 16

    def test_1_cksum_and_ls_match_the_image(self):
        got = self.v.run("/mnt/cksum /bin/as").strip()
        self.assertEqual(got, self.facts["cksum"])
        ls = self.v.run("ls /bin")
        self.assertEqual(sorted(ls.split()), self.facts["bin"])
        self.assertEqual(self.v.run("wc /bin/as").split(), self.facts["wc"].split())

    def test_2_wv_reports_a_failure(self):
        out = self.v.run(f"/mnt/wv 3 /nodir/x /bin/as {self.labels['io_nread']}")
        self.assertIn("wv fail c=1 s=2 e=2", out)
        self.assertIn("wv end n=3 ok=0 mis=0 err=1 nobus=0", out)

    def test_3_write_verify(self):
        io0, t0 = self.iostat(), self.ticks()
        cache0 = self.v.run("cache")
        self.v.type("clear\n")
        time.sleep(1)
        self.v.type(f"/mnt/wv {B_N} /home/s5b /bin/as {self.labels['io_nread']}\n")
        scr = self.v.wait_for("wv end", timeout=7200)
        t1, io1 = self.ticks(), self.iostat()
        cache1 = self.v.run("cache")
        secs = ((t1 - t0) & 0xFFFFFF) / 60
        print(f"\nB under VICE, N={B_N}: {secs:.0f} s emulated (includes typing), "
              f"B_CYCLE_VICE {secs / B_N:.3f} s per cycle\nIOSTAT before {io0}\nIOSTAT after {io1}\n"
              f"cache before: {cache0}\ncache after: {cache1}\n{scr}", file=sys.stderr)
        m = re.search(r"wv end n=(\d+) ok=(\d+) mis=(\d+) err=(\d+) nobus=(\d+)", scr)
        self.assertIsNotNone(m, scr)
        self.assertEqual(tuple(map(int, m.groups())), (B_N, B_N, 0, 0, 0), scr)
        self.assertEqual(io1["io_nfail"], 0)
        self.assertEqual(io1["io_nwfail"], 0)
        # each cycle's read-back went to the bus: at least one bus read per cycle
        self.assertGreaterEqual((io1["io_nread"] - io0["io_nread"]) & 0xFFFF, B_N)
        self.assertIn("reu cache: on", cache0)       # so wv's cache-off read-back path ran
        self.assertIn("reu cache: on", cache1)       # and wv put it back


if __name__ == "__main__":
    unittest.main()
