"""VICE run of experiments/iec-stall/disksum/disksum.s (not discovered by the suite: no test_ prefix).

    tools/ci/run.sh test-only T="tests.disksum_vice"

Stock KERNAL, true-drive 1541 on device 8 with build/breadbin.d64 attached (not autostarted), BASIC up. The reader is
put at $C000 and started with `sys49152` as disksum.py does; STATE/COUNT and the checksum table are read back and
compared with the image. Env DISKSUM_LOAD=1 does `load"$",8` first. Results are printed as one line per run.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(root, "tools"))
sys.path.insert(0, os.path.join(root, "experiments", "iec-stall", "disksum"))
import disksum as ds  # noqa: E402
import vicetest  # noqa: E402

IMAGE = os.path.join(root, "build", "breadbin.d64")
N = 683
TIMEOUT = 900


def assemble():
    d = tempfile.mkdtemp()
    o, b = os.path.join(d, "d.o"), os.path.join(d, "d.bin")
    subprocess.run(["ca65", os.path.join(root, "experiments", "iec-stall", "disksum", "disksum.s"), "-o", o], check=True)
    subprocess.run(["ld65", "-t", "none", "-S", "0xC000", "-o", b, o], check=True)
    return open(b, "rb").read()


class Plain(vicetest.Vice):
    """VICE at BASIC, the image attached to drive 8 (true drive), nothing autostarted."""

    def __init__(self):
        import socket
        self.image = IMAGE
        self.port = vicetest._free_port()
        args = [vicetest.X64, "-default", "+sound", "-minimized", "-warp", "-drive8type", "1541", "-8", IMAGE,
                "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{self.port}"]
        self.log = tempfile.NamedTemporaryFile(prefix="vice", suffix=".log", delete=False)
        self.proc = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT)
        self.sock = None
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


def one_run(preload=False):
    code = assemble()
    want = ds.expected(open(IMAGE, "rb").read())
    with Plain() as v:
        if preload:
            v.type('load"$",8\n')
            time.sleep(3)
            v.wait_for("ready.", timeout=60, after="load")
        f = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
        f.write(b"\x00\xc0" + code)
        f.close()
        v._cmd(f'l "{f.name}" 0 c000')
        v._cmd("x")
        v.type("sys49152\n")
        t0 = time.time()
        last, last_t = -1, time.time()
        while True:
            time.sleep(3)
            st = v.mem(ds.STATE, ds.STATE)[0]
            c = v.mem(ds.COUNT, ds.COUNT + 1)
            count = c[0] | c[1] << 8
            if st != 0:
                break
            if count != last:
                last, last_t = count, time.time()
            elif time.time() - last_t > 60 or time.time() - t0 > TIMEOUT:
                break
        err = bytes(v.mem(ds.ERRCH, ds.ERRCH + 1)).decode("latin1")
        got = None
        if st == 1:
            raw = bytes(v.mem(ds.TABLE, ds.TABLE + 3 * N - 1))
            got = [tuple(raw[3 * i:3 * i + 3]) for i in range(N)]
        if st == 0:
            for _ in range(3):
                print("REGS", v._cmd("r").strip().replace("\n", " | "), flush=True)
            print("ZP90-9F", bytes(v.mem(0x90, 0x9F)).hex(), "A0-AF", bytes(v.mem(0xA0, 0xAF)).hex(),
                  "stack", bytes(v.mem(0x1E0, 0x1FF)).hex(), flush=True)
            print("SCREEN", v.screen(), flush=True)
        extra = {"trk_sect": v.mem(0xC7E0, 0xC7E1)}
    res = {"state": st, "count": count, "err": err, "wall_s": round(time.time() - t0), **extra}
    if got:
        m, diffs, first = ds.compare(got, want)
        res.update(matches=m, differ=len(diffs), first=first)
    print("RESULT", "preload" if preload else "plain", res, flush=True)
    return res


class Disksum(unittest.TestCase):
    def test_1_plain(self):
        for i in range(3):
            r = one_run()
            self.assertEqual(r["state"], 1)
            self.assertEqual(r.get("differ"), 0)

    def test_2_after_load(self):
        for i in range(3):
            r = one_run(preload=True)
            self.assertEqual(r["state"], 1)
            self.assertEqual(r.get("differ"), 0)
