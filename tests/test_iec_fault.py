"""A send to the drive that fails part way (injected under VICE) must be a loud error and leave
no damage: every file of the image still reads back as built, the copy that met the fault is
right or its command said so, and the copies after it are right and quiet.

The copies are read back from the image too (/home/f1-f3, /mnt/*), not only the built files.

The 1541 keeps the bytes of a command that arrived without EOI and puts the next command after
them: "U2" + "U1:2 0 t s" is a U2 to t/s, "B-P" + "U1:..." returns a stale buffer, "U" + "U1:..."
is U5 (a jump into drive RAM). The kernel flushes such a half command before the next LISTEN
(src/kernel/iec.s, io_flush) and does not send U2 after a data phase that failed.

How a fault is made: a breakpoint at cmd_send sees each command (cmdbuf). For the chosen one,
cmdlen is cut so that K bytes go out and the next is held back (the last byte is always held for
EOI), and at bus_unlsn ST is set to 1: the held byte is dropped exactly as after a failed io_tx.
For the data phase (channel 2) and the CBM DOS write (channel 3) the last data byte is dropped
the same way at bus_unlsn.

    tools/ci/run.sh test-only T=tests.test_iec_fault
    tools/ci/run.sh test-only T=tests.test_iec_fault.IecFault.test_u1 FAULT_K=0,1,2,3,last

FAULT_K: bytes delivered before the loss (default per test: the most harmful point found on a
tree without the flush); FAULT_N: which command of the kind (counted from the copy's start;
default 1, and 7 for test_data_phase: a write whose dropped byte differs from what the drive
buffer already held; at 1 to 6 and 8 to 12 it does not show on 451b840). test_none runs the
harness with no fault (the control: no retry, no damage). One `FAULT {json}` line per case.

Measured on a tree without the flush (451b840): U1 K=1 hangs (U5); U2 K=1 hangs; U2 K=2 hangs
and leaves the image unreadable; a B-P at K=3 makes the next command fail and then hangs; a lost
U1 at K=3 or K=last costs two retries, a lost B-P at K=1, 2 or last one; the data phase
(FAULT_N=7) and the CBM write lose a byte with no error. With the flush and the write retry:
a lost byte in a block read or write (U1, U2, B-P, data) costs exactly one retry and no error;
the CBM write (a stream, not retried) is a loud error; no damage, quiet copies after it.

The monitor harness must not lose a stop: a stop missed means the fault would land on a later
command. The injection checks it is at the command it was armed for (cmdbuf, t/s); a miss is
fired 0, a harness failure, never a result.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")
ROOTFS = os.path.join(ROOT, "build", "root")
PROMPT = re.compile(r"\(C:\$[0-9a-f]{4}\) $")
STOP = re.compile(r"#(\d+) \(Stop on\s+exec ([0-9a-f]+)\)")
ST = 0x90


def labels():
    out = {}
    with open(os.path.join(ROOT, "build", "kernel.lbl")) as f:
        lines = f.read().splitlines()
    for ln in lines:
        m = re.match(r"al ([0-9A-F]{6}) \.(\S+)", ln)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


def local_label(name, after):
    """the address of the first cheap local `name` (e.g. @go) above `after`: kernel.lbl lists them
    by their bare name"""
    best = None
    with open(os.path.join(ROOT, "build", "kernel.lbl")) as f:
        for ln in f:
            m = re.match(r"al ([0-9A-F]{6}) \.(\S+)", ln)
            if m and m.group(2) == name:
                a = int(m.group(1), 16)
                if a > after and (best is None or a < best):
                    best = a
    return best


def parse_m(txt, space):
    mem = {}
    for ln in txt.split("\n"):
        m = re.match(r"^>" + space + r":([0-9a-f]{4})\s+((?:[0-9a-f]{2}\s+){1,16})", ln)
        if m:
            a = int(m.group(1), 16)
            for i, h in enumerate(m.group(2).split()):
                mem[a + i] = int(h, 16)
    return mem


class Mon(Vice):
    """Vice with a reader thread, so that breakpoints that hit while the emulator runs are
    noticed and handled (on_stop) before the next command (from tests/stale_trace.py on the
    stale-retry branch)."""
    on_stop = None

    def _start(self):
        self.lock = threading.RLock()
        self.buf = ""
        self.pos = 0
        self.alive = True
        self.cv = threading.Condition()
        self.in_handler = False
        self.pending = None
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        self.sock.settimeout(0.2)
        while self.alive:
            try:
                d = self.sock.recv(65536)
                if not d:
                    break
            except TimeoutError:
                continue
            except OSError:
                break
            with self.cv:
                self.buf += d.decode(errors="replace")
                self.cv.notify_all()

    def _raw(self, c, wait=0.15, timeout=8):
        with self.cv:
            start = len(self.buf)
            if not self.in_handler:
                # a stop that came in after the last scan and before this command: catch it now,
                # or the command's reply moves pos past it and it is lost
                m = STOP.search(self.buf[self.pos:start])
                if m:
                    self.pending = (int(m.group(1)), int(m.group(2), 16), self.buf[self.pos:start])
                    self.pos = start
                if c.strip() == "x" and self.pending:
                    return ""   # stopped at a breakpoint not yet handled: resuming would run past it
        self.sock.sendall((c + "\n").encode())
        if c.strip() == "x":
            time.sleep(wait)
            self.pos = start
            return ""
        end = time.time() + timeout
        pm = None
        with self.cv:
            while time.time() < end:
                pm = PROMPT.search(self.buf[start:])
                if pm:
                    break
                self.cv.wait(0.05)
        text = self.buf[start:]
        if pm:
            self.pos = start + pm.end()
            text = self.buf[start:self.pos]
        else:
            self.pos = len(self.buf)
        m = STOP.search(text)
        if m and not self.in_handler:
            self.pending = (int(m.group(1)), int(m.group(2), 16), text)
        return text

    def service(self):
        with self.lock:
            if self.in_handler:
                return False
            txt = self.buf[self.pos:]
            m = STOP.search(txt)
            if m:
                self.pending = (int(m.group(1)), int(m.group(2), 16), txt)
                self.pos = len(self.buf)
            if not self.pending:
                return False
            num, addr, txt = self.pending
            self.pending = None
            self.in_handler = True
            try:
                last = -1
                while True:
                    time.sleep(0.04)
                    n = len(self.buf)
                    if n == last and PROMPT.search(self.buf):
                        break
                    last = n
                self.pos = len(self.buf)
                self.on_stop(num, addr, txt)
                self._raw("x", wait=0.05)
            finally:
                self.in_handler = False
            return True

    def _cmd(self, c, wait=0.15):
        if not hasattr(self, "lock"):
            self._start()
            time.sleep(0.2)
        with self.lock:
            if self.service() and c.strip() == "x":
                return ""       # the handler has resumed: a second x could run past a stop that comes in meanwhile
            return self._raw(c, wait)

    def _wait(self, pred, timeout, what="condition"):
        deadline = time.time() + timeout
        last = 0
        while time.time() < deadline:
            self.service()
            if time.time() - last > 0.4:
                last = time.time()
                if pred(self.screen_lines()):
                    return
            time.sleep(0.03)
        raise TimeoutError(f"timeout waiting for {what}:\n{self.screen()}")

    def close(self):
        self.alive = False
        super().close()


def mkimage_cat(img, path):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "cat", img, path],
                       capture_output=True)
    return r.stdout if r.returncode == 0 else None


def ks(default):
    return os.environ.get("FAULT_K", default).split(",")


class IecFault(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="iecfault")
        self.lbl = labels()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- one boot, one fault ----
    def case(self, kind, k=None, extra=(), steps=None, nth=1, reu=None):
        """kind: 'U1', 'U2', 'B-P' (k bytes of the command delivered), 'data' (channel 2) or
        'cbm' (channel 3 on drive 9); 'U2st' (the U2 goes out whole, its status read times out
        before the first bit; motivated by the physical 1541 going quiet mid-byte, which this does
        not simulate); 'U2unl' (the U2 goes out whole, ATN is asserted for the UNLISTEN, and the
        $3F byte is not acknowledged: not a lost ATN edge). reu: KB of REU (the block cache is on).
        Returns the record."""
        lbl = self.lbl
        img = os.path.join(self.tmp, "a.d64")
        shutil.copyfile(IMAGE, img)
        nth = int(os.environ.get("FAULT_N", nth))
        st = {"active": False, "seen": 0, "fired": 0, "pending": False, "armed": False,
              "fault_ts": None, "bk": {}, "u2": set()}
        rec = {"kind": kind, "k": k}
        with Mon(img, extra=list(extra), **({"reu": reu} if reu else {})) as v:
            def rd(a, b):
                for _ in range(4):
                    m = parse_m(v._raw("m %04x %04x" % (a, b)), "C")
                    if all(x in m for x in range(a, b + 1)):
                        return bytes(m[x] for x in range(a, b + 1))
                raise RuntimeError("monitor read %04x-%04x failed" % (a, b))

            # the breakpoint at bus_unlsn exists from the start, disabled, and is switched by its
            # number (read from the listing: a reply read inside a stop can be a stale one)
            def arm_unlsn():
                v._raw("enable %d" % st["bk"][lbl["bus_unlsn"]])
                st["armed"] = True

            def disarm_unlsn():
                v._raw("disable %d" % st["bk"][lbl["bus_unlsn"]])
                st["armed"] = False

            def on_stop(num, addr, txt):
                if addr == lbl["cmd_send"]:
                    n = rd(lbl["cmdlen"], lbl["cmdlen"])[0]
                    cmd = rd(lbl["cmdbuf"], lbl["cmdbuf"] + n - 1).decode("latin1")
                    t, s = rd(lbl["trk"], lbl["sct"])
                    if cmd.startswith("U2"):
                        st["u2"].add(tuple(int(x) for x in cmd[3:].split()[2:4]))
                    if st.get("probe") is not None and cmd.startswith("U2") and len(st["probe"]) < 2:
                        # the drive's job headers (t/s of buffers 0-4, $06-$0F): which blocks it
                        # last read or wrote. Taken at the faulted U2 and at the next U2 (by then the
                        # drive has run whatever the cut command was)
                        m = parse_m(v._raw("m 8:0006 8:000f"), "8")
                        st["probe"].append([[m.get(6 + 2 * b), m.get(7 + 2 * b)] for b in range(5)])
                    if st["active"] and os.environ.get("FAULT_TRACE"):
                        print("CMD", st["fired"], repr(cmd), t, s, flush=True)
                    if not st["active"] or st["fired"] or st["pending"]:
                        return
                    if kind in ("U1", "U2", "B-P") and cmd.startswith(kind):
                        st["seen"] += 1
                        if st["seen"] == nth:
                            kk = n - 1 if k == "last" else int(k)
                            if kk < n - 1:
                                v._raw("> %04x %02x" % (lbl["cmdlen"], kk + 1))
                            st["pending"] = True
                            st["fault_ts"] = (t, s)
                            st["prefix"] = kind
                            rec["cmd"] = cmd
                            rec["sent"] = cmd[:kk]
                            arm_unlsn()
                    elif kind.endswith("eoil") and cmd.startswith(kind[:-4]):
                        # the last byte's EOI handshake completes (the drive has seen EOI), then the
                        # byte itself is lost: io_tx gives up before its first bit (PC to @fail)
                        st["seen"] += 1
                        if st["seen"] == nth:
                            st["eoil"] = True
                            st["probe"] = []
                            m = parse_m(v._raw("m 8:0006 8:000f"), "8")
                            st["probe"].append([[m.get(6 + 2 * b), m.get(7 + 2 * b)] for b in range(5)])
                            rec["cmd"] = cmd
                            rec["sent"] = cmd[:-1]
                            v._raw("enable %d" % st["bk"][st["go"]])
                    elif kind.endswith("eoi") and cmd.startswith(kind[:-3]):
                        # a spurious EOI: the K-th byte of the command goes out with EOI (as when
                        # a CPU halt of more than 200 us between the listener's ready and our CLK
                        # makes the drive take it for the last), the rest follows as usual. The
                        # drive runs cmd[:K] and then cmd[K:] as two commands. No bus fault.
                        st["seen"] += 1
                        if st["seen"] == nth:
                            st["eoi_k"] = n - 1 if k == "last" else int(k)
                            st["eoi_c"] = 0
                            rec["cmd"] = cmd
                            rec["sent"] = [cmd[:st["eoi_k"]], cmd[st["eoi_k"]:]]
                            v._raw("enable %d" % st["bk"][lbl["io_tx"]])
                    elif kind in ("U2st", "U2unl") and cmd.startswith("U2"):
                        st["seen"] += 1
                        if st["seen"] == nth:
                            st["fault_ts"] = (t, s)
                            rec["cmd"] = cmd
                            if kind == "U2st":
                                st["stt"] = True
                                v._raw("enable %d" % st["bk"][st["ago"]])
                            else:
                                st["unl"] = True
                                v._raw("enable %d" % st["bk"][st["go"]])
                    elif kind == "data" and cmd.startswith("B-P"):
                        st["seen"] += 1
                        if st["seen"] == nth:
                            st["pending"] = True
                            st["fault_ts"] = (t, s)
                            st["prefix"] = "B-P"
                            arm_unlsn()
                elif addr == st.get("ago"):
                    # the first byte the U2's status read waits for: the wait runs out (PC to
                    # bus_acptr's @tmo, past its pushes: ST bit 1, A = 0), as when the drive
                    # stalls; the drive still holds its message, cut short by the UNTALK
                    if st.get("stt"):
                        st["stt"] = False
                        v._raw("r pc = %04x" % st["atmo"])
                        v._raw("disable %d" % st["bk"][st["ago"]])
                        st["fired"] += 1
                elif addr == st.get("go") and st.get("unl"):
                    # the U2's UNLISTEN ($3F under ATN) is not taken: io_tx gives up before it
                    o, b = rd(lbl["io_out"], lbl["io_out"])[0], rd(lbl["io_b"], lbl["io_b"])[0]
                    if o & 0x08 and b == 0x3f:
                        st["unl"] = False
                        v._raw("r pc = %04x" % st["fail"])
                        v._raw("disable %d" % st["bk"][st["go"]])
                        st["fired"] += 1
                elif addr == st.get("go"):
                    if not st.get("eoil") or rd(lbl["io_eoi"], lbl["io_eoi"])[0] != 1:
                        return
                    v._raw("r pc = %04x" % st["fail"])
                    v._raw("disable %d" % st["bk"][st["go"]])
                    st["eoil"] = False
                    st["fired"] += 1
                elif addr == lbl["io_tx"]:
                    o = rd(lbl["io_out"], lbl["io_out"])[0]
                    if "eoi_k" not in st or o & 0x08:       # a byte under ATN (LISTEN, secondary)
                        return
                    st["eoi_c"] += 1
                    if st["eoi_c"] == st["eoi_k"]:
                        v._raw("> %04x 01" % lbl["io_eoi"])
                        v._raw("disable %d" % st["bk"][lbl["io_tx"]])
                        del st["eoi_k"]
                        st["fired"] += 1
                elif addr == lbl["bus_unlsn"]:
                    if not st["armed"]:
                        return
                    sa, l2 = rd(lbl["ie_sa"], lbl["ie_sa"])[0], rd(lbl["ie_len2"], lbl["ie_len2"])[0]
                    want = {"data": 2, "cbm": 3}.get(kind, 15)
                    if st["pending"] and sa == want and l2 == 0x60 and st.get("prefix"):
                        # the targeted command only: a stop the harness missed must show as fired 0,
                        # never as a fault on a later command
                        pre = st["prefix"]
                        if (rd(lbl["cmdbuf"], lbl["cmdbuf"] + len(pre) - 1).decode("latin1") != pre
                                or tuple(rd(lbl["trk"], lbl["sct"])) != st["fault_ts"]):
                            st["pending"] = False
                            st["wrong"] = True
                            disarm_unlsn()
                            return
                    if st["pending"] and sa == want and l2 == 0x60:
                        v._raw("> %04x 01" % ST)
                        st["pending"] = False
                        st["fired"] += 1
                        disarm_unlsn()
                else:
                    print("STOP? ", hex(addr), flush=True)

            v.on_stop = on_stop
            v.wait_shell()
            if kind == "cbm":
                self.assertEqual(v.run("mount 9 /mnt"), "")
            v._cmd("bk exec %x" % lbl["cmd_send"])
            v._cmd("bk exec %x" % lbl["bus_unlsn"])
            v._cmd("bk exec %x" % lbl["io_tx"])
            st["go"] = local_label("@go", lbl["io_tx"])
            st["fail"] = local_label("@fail", lbl["io_tx"])
            v._cmd("bk exec %x" % st["go"])
            st["ago"] = local_label("@go", lbl["bus_acptr"])
            st["atmo"] = local_label("@tmo", lbl["bus_acptr"])
            v._cmd("bk exec %x" % st["ago"])
            for _ in range(5):
                for m in re.finditer(r"BREAK:\s*(\d+)\s+C:\$([0-9a-fA-F]{4})", v._cmd("bk")):
                    st["bk"][int(m.group(2), 16)] = int(m.group(1))
                if all(a in st["bk"] for a in (lbl["cmd_send"], lbl["bus_unlsn"], lbl["io_tx"], st["go"],
                                               st["ago"])):
                    break
            v._cmd("disable %d" % st["bk"][st["go"]])
            v._cmd("disable %d" % st["bk"][st["ago"]])
            self.assertIn(lbl["bus_unlsn"], st["bk"], "breakpoint listing")
            self.assertIn(lbl["io_tx"], st["bk"], "breakpoint listing")
            v._cmd("disable %d" % st["bk"][lbl["bus_unlsn"]])
            v._cmd("disable %d" % st["bk"][lbl["io_tx"]])
            v._cmd("x")
            nr0 = self.retries(v)
            out = []
            try:
                for i, c in enumerate(steps):
                    if i == 0:
                        st["active"] = True
                        if kind == "cbm":
                            st["pending"] = True
                            with v.lock:
                                v.service()
                                arm_unlsn()
                                v._raw("x")
                    o = v.run(c, timeout=300)
                    if i == 0:         # the fault belongs to the first step only
                        st["active"] = False
                        st["pending"] = False
                        if st["armed"]:
                            with v.lock:
                                v.service()
                                disarm_unlsn()
                                v._raw("x")
                    out.append(o)
            except TimeoutError as e:
                rec["hang"] = str(e)[-300:]
            rec["out"] = out
            rec["retries"] = None if nr0 is None or "hang" in rec else self.retries(v) - nr0
            if kind == "cbm" and "hang" not in rec:
                v.run("umount /mnt")
        rec["fired"] = st["fired"]
        rec["wrong"] = st.get("wrong", False)
        rec["fault_ts"] = st["fault_ts"]
        # the disk: every file it was built with reads back unchanged
        bad = []
        for d, _, fs in os.walk(ROOTFS):
            for f in fs:
                if f == ".keep":       # placeholders for empty directories, not on the image
                    continue
                src = os.path.join(d, f)
                path = "/" + os.path.relpath(src, ROOTFS)
                with open(src, "rb") as f:
                    want = f.read()
                if mkimage_cat(img, path) != want:
                    bad.append(path)
        rec["damage"] = bad
        rec["img"] = img
        rec["u2"] = sorted(st["u2"])
        if st.get("probe") is not None:
            rec["headers"] = st["probe"]
        rec["foreign"] = foreign_writes(IMAGE, img, st["u2"])
        return rec

    def counter(self, v, name):
        if name not in self.lbl:
            return None
        a = self.lbl[name]
        return int.from_bytes(bytes(v.mem(a, a + 1)), "little")

    def retries(self, v):
        """block-read plus block-write retries (io_nretry, io_nwretry: IOSTAT; the write counter is
        absent on older trees, where io_nretry counted both)"""
        r = self.counter(v, "io_nretry")
        w = self.counter(v, "io_nwretry")
        return None if r is None else r + (w or 0)

    def check(self, rec, files, recovered=None):
        """files: [(path on the image, host original)] for each step that copies; a step's copy
        must be right, or the step must have said something (an error). recovered: the number of
        retries the fault must cost (1: one the kernel retries, a block read or write; 0: one the
        drive never notices, a spurious EOI): the copy must be right and quiet as well."""
        print("FAULT " + json.dumps({k: v for k, v in rec.items() if k != "img"}), flush=True)
        self.assertEqual(rec["fired"], 1, "fault never injected (a harness failure, not the kernel's)")
        self.assertNotIn("hang", rec)
        self.assertEqual(rec["damage"], [])
        if rec["foreign"]:      # a block no U2 was meant for changed: only after a loud step
            self.assertTrue(any(rec["out"]), "silent write to a block no U2 named: %s" % rec["foreign"])
        for i, (path, src) in enumerate(files):
            with open(src, "rb") as f:
                want = f.read()
            if rec["kind"] == "cbm":
                got = self.cbm_read(rec["img9"], os.path.basename(path))
            else:
                got = mkimage_cat(rec["img"], path)
            if i == 0 and recovered is not None:
                self.assertEqual(rec["out"][i], "", "the retry should have hidden the fault")
                self.assertEqual(got, want, f"{path} wrong after the retry")
                if rec["retries"] is not None:
                    self.assertEqual(rec["retries"], recovered, "retries for this fault")
            elif i == 0:    # the faulted step: right, or loud
                self.assertTrue(got == want or rec["out"][i] != "",
                                f"silent damage: {path} differs and the command said nothing")
            else:           # the step after: right, and quiet
                self.assertEqual(rec["out"][i], "", f"step {i} failed after the fault")
                self.assertEqual(got, want, f"{path} wrong after the fault")

    def cbm_read(self, img9, name):
        o = os.path.join(self.tmp, "r.bin")
        if os.path.exists(o):
            os.unlink(o)
        subprocess.run(["c1541", img9, "-read", name + ",s", o], capture_output=True)
        return open(o, "rb").read() if os.path.exists(o) else None

    def copies(self, kind, k, nth=1):
        steps = ["cp /bin/cat /home/f1", "cp /bin/ls /home/f2", "cp /bin/echo /home/f3"]
        rec = self.case(kind, k, steps=steps, nth=nth)
        # every copy is read back from the image (the files written, not just the ones built)
        self.check(rec, [("/home/f1", os.path.join(ROOTFS, "bin", "cat")),
                         ("/home/f2", os.path.join(ROOTFS, "bin", "ls")),
                         ("/home/f3", os.path.join(ROOTFS, "bin", "echo"))],
                   recovered=1 if kind in ("U1", "B-P", "data", "U1eoil", "B-Peoil", "U2st", "U2unl") else
                   0 if kind in ("U1eoi", "U2eoi", "B-Peoi") else None)
        return rec

    def test_none(self):
        """the harness itself: no fault, no damage"""
        steps = ["cp /bin/cat /home/f1", "cp /bin/ls /home/f2", "cp /bin/echo /home/f3"]
        rec = self.case("none", None, steps=steps)
        rec["fired"] = 1
        self.check(rec, [("/home/f1", os.path.join(ROOTFS, "bin", "cat")),
                         ("/home/f2", os.path.join(ROOTFS, "bin", "ls")),
                         ("/home/f3", os.path.join(ROOTFS, "bin", "echo"))])

    def test_u1(self):
        for k in ks("1"):           # "U" + "U1:..." is U5, a jump into drive RAM
            with self.subTest(k=k):
                self.copies("U1", k)   # one retry: the flush comes first, so the next try is clean

    def test_u2(self):
        for k in ks("2"):           # "U2" + "U1:2 0 t s" is a U2 to the block being read
            with self.subTest(k=k):
                self.copies("U2", k)

    def test_bp(self):
        for k in ks("3"):
            with self.subTest(k=k):
                self.copies("B-P", k)

    def test_u1_eoi(self):
        """a spurious EOI in the middle of a U1: the 1541 runs a command at UNLISTEN, with every
        byte, so nothing happens: quiet, right, no retry (measured; an earlier theory had the drive
        run both parts)"""
        for k in ks("4,10"):
            with self.subTest(k=k):
                self.copies("U1eoi", k)

    def test_u2_eoi(self):
        """a spurious EOI in the middle of a U2: the drive runs the whole command at UNLISTEN:
        quiet, right, no retry, no block changed that no U2 named"""
        for k in ks("4,8,9,10"):
            with self.subTest(k=k):
                self.copies("U2eoi", k)

    def test_u2_eoi_lost(self):
        """the drive sees the EOI of a U2's last byte, then the byte is lost: it may run the U2
        without it ("U2:2 0 19 1" for "U2:2 0 19 10"), a write to another block. No retry: the
        write fails loudly (EIO), and no block that a file holds is changed. FAULT_N picks the U2
        of the copy (default 1, 2, 3)"""
        for n in os.environ.get("FAULT_NS", "1,2,3").split(","):
            with self.subTest(n=n):
                rec = self.copies("U2eoil", None, nth=int(n))
                # loud with the right error: a failed directory write in sys_open once came back
                # as the new inode's number ("error 71")
                self.assertIn("i/o error", rec["out"][0])

    def test_u1_eoi_lost(self):
        """the same for a U1: a read of the wrong block is read again: one retry, quiet"""
        self.copies("U1eoil", None)

    def test_bp_eoi_lost(self):
        """the same for the B-P: its status is read before the data, tried again: one retry, quiet"""
        self.copies("B-Peoil", None)

    def test_u2_status_timeout(self):
        """the U2 went out whole (the block is written), then its status read times out (before
        its first bit; the physical 1541's mid-byte stall is the motivation, not what is simulated): the whole write is tried again, the same block
        again: one retry, quiet. On d0639fb (no retry from the U2 on) this was EIO"""
        for n in os.environ.get("FAULT_NS", "1,2,3").split(","):
            with self.subTest(n=n):
                self.copies("U2st", None, nth=int(n))

    def test_u2_unlisten_lost(self):
        """the U2 went out whole, its UNLISTEN is not answered: the drive may not have run it,
        and its status would then be the last command's "00". On channel 15 that is a failure,
        and since every byte arrived the U2 is whole: the write is tried again, the same block:
        one retry, quiet. (Under VICE the drive ran the U2 anyway: on d0639fb, which ignored
        the UNLISTEN, this was quiet with no retry)"""
        for n in os.environ.get("FAULT_NS", "1,2,3").split(","):
            with self.subTest(n=n):
                self.copies("U2unl", None, nth=int(n))

    def test_epoch_after_failed_first_write(self):
        """the REU cache is on; the boot's first write is the superblock's new build id
        (cache_epoch). That write fails (the U2's last byte lost: EIO). The next write must try
        the epoch again: the disk's build id is a new one at the end, or the cache would take a
        changed disk for the pristine one. On d0639fb ep_done stayed set and the id stayed"""
        steps = ["echo x > /home/f1", "echo y > /home/f2", "cat /home/f2"]
        rec = self.case("U2", "last", steps=steps, nth=1, reu=2048)
        print("EPOCH " + json.dumps({k: rec.get(k) for k in ("cmd", "out", "fired")}), flush=True)
        self.assertEqual(rec["fired"], 1, "fault never injected")
        self.assertEqual(rec["cmd"], "U2:2 0 19 0", "the boot's first write is the superblock's")
        self.assertIn("i/o error", rec["out"][0])
        self.assertEqual(rec["out"][1:], ["", "y"])
        off = 376 * 256 + 15
        with open(IMAGE, "rb") as f:
            id0 = f.read()[off:off + 4]
        with open(rec["img"], "rb") as f:
            id1 = f.read()[off:off + 4]
        self.assertNotEqual(id0, id1, "writes went ahead with the disk's old build id")

    def test_bp_eoi(self):
        """a spurious EOI in the middle of the B-P: the drive runs it whole: quiet, no retry"""
        for k in ks("3,5,6"):
            with self.subTest(k=k):
                self.copies("B-Peoi", k)

    def test_data_phase(self):
        self.copies("data", None, nth=7)    # a write whose dropped byte shows (where the drive buffer already holds the block, it does not)

    def test_cbm_write(self):
        cbm = os.path.join(self.tmp, "cbm.d64")
        subprocess.run(["c1541", "-format", "cbmdisk,cb", "d64", cbm], check=True, capture_output=True)
        rec = self.case("cbm", None, extra=["-drive9type", "1541", "-9", cbm],
                        steps=["cp /etc/help /mnt/help", "cp /etc/motd /mnt/motd"])
        rec["img9"] = cbm
        self.check(rec, [("/mnt/help", os.path.join(ROOTFS, "etc", "help")),
                         ("/mnt/motd", os.path.join(ROOTFS, "etc", "motd"))])


DIR_TS = (17 * 21 + 1) * 256       # track 18 sector 1: the first directory sector of a d64
PRG = os.path.join(ROOT, "build", "breadbin.prg")


def image_damage(img):
    """The files the image was built with that no longer read back as built."""
    bad = []
    for d, _, fs in os.walk(ROOTFS):
        for f in fs:
            if f == ".keep":
                continue
            src = os.path.join(d, f)
            path = "/" + os.path.relpath(src, ROOTFS)
            with open(src, "rb") as fh:
                if mkimage_cat(img, path) != fh.read():
                    bad.append(path)
    return bad


def ts_offset(t, s):
    spt = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
    return (sum(spt[:t - 1]) + s) * 256


def foreign_writes(before_img, after_img, targets):
    """The sectors that differ between the two images and that no U2 named."""
    with open(before_img, "rb") as f:
        a = f.read()
    with open(after_img, "rb") as f:
        b = f.read()
    spt = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
    out = []
    for t in range(1, 36):
        for s in range(spt[t - 1]):
            o = ts_offset(t, s)
            if a[o:o + 256] != b[o:o + 256] and (t, s) not in targets:
                out.append((t, s))
    return out


def dir_sector(img):
    with open(img, "rb") as f:
        return f.read()[DIR_TS:DIR_TS + 256]


class IecRestart(unittest.TestCase):
    """A C64-only restart (the drive is not reset: on the Ultimate a C64 reset leaves the physical
    drive alone, docs/hardware-notes.md) can leave a half command in a drive, and the first command
    sent to it after the restart (OPEN 15 "i0" at boot or at mount) would be appended to it.
    blk_init marks every drive, and the first send to a marked drive flushes it first (io_flush,
    through out_sa); iec_open tries three times, and if the flush never gets through it fails with
    EIO and sends nothing else to channel 15 (an "i0" after "S:*" would scratch every file).

    The restart here: the C64 alone goes through the KERNAL's reset (the drive untouched), the
    program is put in memory by the monitor and run at its SYS address, so nothing is sent on the
    bus before Breadbin's own first command. (A KERNAL LOAD"BREADBIN",8 is not covered: its OPEN
    meets the half command before Breadbin runs.)

    The half command is either "S:*" put into the drive's command buffer through the monitor
    (appended, "S:*i0" scratches every file) or a real U2 cut off after K bytes by a C64 reset at
    that point (FAULT_K, default 9). On a tree without the flush (6fe6cdf) K=0 to 8, 10, 11 and last
    boot quietly with no damage, and K=9 ("U2:2 0 19" + "i0") panics at the root mount; on a tree
    with the boot flush but not the retry or the marks for drives 9-11 (3bebf55) the drive 9 test
    loses its file and the flush-fault tests panic at the root mount; on 236a044 (the give-up then
    sent "i0" as before) three flushes that lose their first byte scratch the directory."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="iecrestart")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lbl = labels()
        self.img = os.path.join(self.tmp, "a.d64")
        shutil.copyfile(IMAGE, self.img)
        self.dir0 = dir_sector(self.img)
        self.assertEqual(self.dir0[2], 0x82, "the image's first directory entry is a PRG")

    def poke_half(self, v, drive):
        v._cmd("> %d:0200 53 3a 2a" % drive)    # "S:*", no EOI yet: a half command
        v._cmd("> %d:00a3 03" % drive)          # the drive's command buffer pointer (buffer 5, $99+10)
        for _ in range(4):      # a reply can come in late (the reader thread): read until it is there
            m = parse_m(v._cmd("m %d:0200 %d:0202" % (drive, drive)), str(drive))
            if all(a in m for a in (0x200, 0x201, 0x202)):
                break
        self.assertEqual([m.get(a) for a in (0x200, 0x201, 0x202)], [0x53, 0x3a, 0x2a], "half command in the drive")

    @staticmethod
    def c64_reset(v, raw=False):
        """The C64 alone through the KERNAL's reset: interrupts off, ROMs in, PC at $FCE2."""
        c = v._raw if raw else v._cmd
        c("> c:0001 37")
        c("> c:dc0d 7f")
        c("> c:d01a 00")
        c("r pc = fce2")

    def start(self, v, on_stop=None, bks=()):
        """At BASIC's READY after the reset: put Breadbin in memory and run it, with breakpoints."""
        v.wait_for("ready.", timeout=60)
        v._cmd('l "%s" 0' % PRG)               # into memory with no IEC traffic
        if on_stop:
            v.on_stop = on_stop
        for a in bks:
            v._cmd("bk exec %x" % a)
        v._cmd("r pc = 080d")                   # its BASIC stub's SYS 2061
        v._cmd("x")
        v.wait_shell(timeout=180)

    def quiet_boot(self, v):
        scr = v.screen().lower()
        for bad in ("panic", "error", "no root", "not there", "reu root"):
            self.assertNotIn(bad, scr, "the boot said something:\n" + scr)
        self.assertIn("bin", v.run("ls /"))
        self.assertEqual(v.run("cp /bin/cat /home/f1"), "")

    def after(self):
        with open(os.path.join(ROOTFS, "bin", "cat"), "rb") as f:
            self.assertEqual(mkimage_cat(self.img, "/home/f1"), f.read())
        self.assertEqual(image_damage(self.img), [])
        self.assertEqual(dir_sector(self.img), self.dir0,
                         "the directory changed: the half command ran")

    def listen_fault(self, nfail, flush_only, half=False, reu=False):
        """after a C64-only restart, the LISTEN byte to drive 8 is not taken (io_tx gives up
        before it: ST bit 7, as a missed frame ack would) nfail times; flush_only: only the
        LISTEN of a flush (the drive is marked). The drive is there: the boot must not take it
        for absent (the REU root), nor drop its mark (the half command would run)"""
        lbl = self.lbl
        lst = lbl["bus_listen"]
        go = local_label("@go", lbl["io_tx"])
        fail = local_label("@fail", lbl["io_tx"])
        st = {"n": 0, "arm": False, "bk": {}}
        kw = {}
        if reu:
            r = os.path.join(self.tmp, "root.reu")
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "reu", IMAGE, r],
                           check=True, capture_output=True)
            kw = {"reu": 256, "reu_image": r}

        def on_stop(num, addr, txt):
            if st["n"] >= nfail:
                return
            if addr == lst:
                m = parse_m(v._raw("m %04x %04x" % (lbl["ie_dev"], lbl["ie_dev"])), "C")
                d = parse_m(v._raw("m %04x %04x" % (lbl["io_dirty"], lbl["io_dirty"])), "C")
                if m.get(lbl["ie_dev"]) == 8 and (d.get(lbl["io_dirty"]) or not flush_only):
                    st["arm"] = True
                    v._raw("enable %d" % st["bk"][go])
            elif addr == go and st["arm"]:
                st["arm"] = False
                v._raw("disable %d" % st["bk"][go])
                v._raw("r pc = %04x" % fail)
                st["n"] += 1
                if st["n"] >= nfail:
                    v._raw("del")
        with Mon(self.img, **kw) as v:
            v.wait_shell()
            if half:
                self.poke_half(v, 8)
            self.c64_reset(v)
            v._cmd("x")
            v.wait_for("ready.", timeout=60)
            v._cmd('l "%s" 0' % PRG)
            v.on_stop = on_stop
            v._cmd("bk exec %x" % lst)
            v._cmd("bk exec %x" % go)
            for _ in range(5):
                for m in re.finditer(r"BREAK:\s*(\d+)\s+C:\$([0-9a-fA-F]{4})", v._cmd("bk")):
                    st["bk"][int(m.group(2), 16)] = int(m.group(1))
                if lst in st["bk"] and go in st["bk"]:
                    break
            v._cmd("disable %d" % st["bk"][go])
            v._cmd("r pc = 080d")
            v._cmd("x")
            v.wait_shell(timeout=180)
            scr = v.screen().lower()
            print("LISTENFAULT " + json.dumps({"nfail": nfail, "flush_only": flush_only, "n": st["n"],
                                               "reu_root": "root on reu" in scr}), flush=True)
            self.assertEqual(st["n"], nfail, "faults injected")
            self.assertNotIn("root on reu", scr, "a LISTEN not taken adopted the REU root")
            self.quiet_boot(v)
        self.after()

    def test_flush_listen_missed(self):
        """a half command in the drive; the flush's LISTEN is not taken once. The mark stays
        (ENODEV from the flush, out_sa tries again): flushed, quiet boot, nothing scratched. On
        d0639fb the mark was dropped and "i0" went after the "S:*" """
        self.listen_fault(1, True, half=True)

    def test_listen_missed_twice(self):
        """the REU holds a root image; the first two LISTENs to drive 8 are not taken. out_sa
        tries three times before ENODEV: a quiet boot from the drive. On d0639fb the second
        was ENODEV, and the boot adopted the REU root"""
        self.listen_fault(2, False, reu=True)

    def test_half_command_across_restart(self):
        with Mon(self.img) as v:
            v.wait_shell()
            self.poke_half(v, 8)
            self.c64_reset(v)
            v._cmd("x")
            self.start(v)
            self.quiet_boot(v)
        self.after()

    def test_drive9_half_command_across_restart(self):
        """the first mount of drive 9 after the restart flushes it too"""
        cbm = os.path.join(self.tmp, "cbm.d64")
        subprocess.run(["c1541", "-format", "cbmdisk,cb", "d64", cbm, "-write",
                        os.path.join(ROOTFS, "etc", "motd"), "motd,s"], check=True, capture_output=True)
        d9 = dir_sector(cbm)
        self.assertNotEqual(d9[2], 0)
        with Mon(self.img, extra=["-drive9type", "1541", "-9", cbm]) as v:
            v.wait_shell()
            self.poke_half(v, 9)
            self.c64_reset(v)
            v._cmd("x")
            self.start(v)
            self.quiet_boot(v)
            self.assertEqual(v.run("mount 9 /mnt"), "")
            self.assertIn("motd", v.run("ls /mnt"))
            v.run("umount /mnt")
        self.after()
        self.assertEqual(dir_sector(cbm), d9, "drive 9's directory changed: the half command ran")

    def flush_fault(self, nfail, half, at="last"):
        """fail the boot flush nfail times: at="last" drops its last byte (the one with EOI, at
        bus_unlsn), at="first" its first (at bus_ciout, before any space goes out: the drive keeps
        just the half command). Three failures: the open must not go ahead (EIO, the root mount
        fails loudly), never an "i0" sent after the half command, and no REU root."""
        lbl = self.lbl
        st = {"n": 0}
        bk = lbl["bus_unlsn"] if at == "last" else lbl["bus_ciout"]

        def on_stop(num, addr, txt):
            if addr != bk or st["n"] >= nfail:
                return
            m = parse_m(v._raw("m %04x %04x" % (lbl["io_pend"], lbl["io_held"])), "C")
            stv = parse_m(v._raw("m %04x %04x" % (ST, ST)), "C").get(ST)
            if m.get(lbl["io_pend"]) != 1 or m.get(lbl["io_held"]) != 0x20 or stv != 0:
                return                          # not a flush byte, or this flush already failed
            st["n"] += 1
            v._raw("> %04x 01" % ST)            # the held byte is dropped, and every one after it
            if st["n"] >= nfail:
                v._raw("del")                   # no more stops
        with Mon(self.img) as v:
            v.wait_shell()
            if half:
                self.poke_half(v, 8)
            self.c64_reset(v)
            v._cmd("x")
            if nfail < 3:
                self.start(v, on_stop, [bk])
            else:
                v.wait_for("ready.", timeout=60)
                v._cmd('l "%s" 0' % PRG)
                v.on_stop = on_stop
                v._cmd("bk exec %x" % bk)
                v._cmd("r pc = 080d")
                v._cmd("x")
                v.wait_for("cannot mount root", timeout=240)
            print("FLUSHFAULT " + json.dumps({"nfail": nfail, "half": half, "at": at, "n": st["n"]}), flush=True)
            self.assertEqual(st["n"], nfail, "faults injected")
            if nfail < 3:
                self.quiet_boot(v)
            else:
                self.assertNotIn("root on reu", v.screen().lower())
        if nfail < 3:
            self.after()
        self.assertEqual(dir_sector(self.img), self.dir0, "the directory changed: the half command ran")

    def test_flush_fault_once(self):
        """a byte of the boot flush lost: the second try clears the half command, quiet boot"""
        self.flush_fault(1, half=True)

    def test_flush_fault_first_byte_twice(self):
        """the first byte of the flush lost twice: the third try clears the half command, quiet boot"""
        self.flush_fault(2, half=True, at="first")

    def test_flush_fault_three(self):
        """all three flush tries lose their last byte: EIO, loud, the half command never runs"""
        self.flush_fault(3, half=True)

    def test_flush_fault_three_first_byte(self):
        """all three lose their first byte, so the drive holds just "S:*": an "i0" after the give-up
        would run "S:*i0" and scratch every file; the open must fail instead (EIO, loud)"""
        self.flush_fault(3, half=True, at="first")

    def test_u2_cut_by_reset(self):
        """a real U2 cut off after K bytes by a C64 reset (no poke): nothing damaged after the boot"""
        lbl = self.lbl
        for k in ks("9"):
            with self.subTest(k=k):
                img = self.img
                shutil.copyfile(IMAGE, img)
                st = {"armed": False, "fired": 0, "sent": None}

                def on_stop(num, addr, txt):
                    if addr == lbl["cmd_send"] and not st["armed"] and not st["fired"]:
                        n = parse_m(v._raw("m %04x %04x" % (lbl["cmdlen"], lbl["cmdlen"])), "C")[lbl["cmdlen"]]
                        m = parse_m(v._raw("m %04x %04x" % (lbl["cmdbuf"], lbl["cmdbuf"] + n - 1)), "C")
                        cmd = bytes(m[lbl["cmdbuf"] + i] for i in range(n)).decode("latin1")
                        if cmd.startswith("U2"):
                            kk = n - 1 if k == "last" else int(k)
                            v._raw("> %04x %02x" % (lbl["cmdlen"], kk + 1))   # kk go out, one is held
                            st["sent"] = cmd[:kk]
                            st["armed"] = True
                    elif addr == lbl["bus_unlsn"] and st["armed"]:
                        st["armed"] = False
                        st["fired"] += 1
                        v._raw("del")
                        self.c64_reset(v, raw=True)    # the held byte never goes: K bytes, no EOI
                with Mon(img) as v:
                    v.wait_shell()
                    v.on_stop = on_stop
                    v._cmd("bk exec %x" % lbl["cmd_send"])
                    v._cmd("bk exec %x" % lbl["bus_unlsn"])
                    v._cmd("x")
                    v.type("cp /bin/cat /home/f1\n")
                    self.start(v)
                    print("RESTART " + json.dumps({"k": k, "sent": st["sent"], "fired": st["fired"]}), flush=True)
                    self.assertEqual(st["fired"], 1, "reset never injected")
                    self.quiet_boot(v)
                self.after()


class IecOpenFault(unittest.TestCase):
    """A byte lost in an OPEN (iec_open: 15 "i0", then 2 "#") of a drive that answered LISTEN is
    not "no drive": the open is tried again (three times, each after a flush) and, if it still
    fails, is EIO. Only a drive that does not answer may read as absent (ENODEV), which at boot
    adopts an REU that holds a root image. The REU here holds one (`mkimage.py reu`), so an
    adoption would show ("root on reu"). The fault: at bus_unlsn, while the open's last byte (the
    one sent with EOI) is held, ST is set, and the byte is dropped as after a failed io_tx. The
    boot is a C64-only restart (as IecRestart) so the breakpoint is in place before blk_init.

    On 236a044 (before the retry) one lost byte of either open adopts the REU root."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="iecopen")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lbl = labels()
        self.img = os.path.join(self.tmp, "a.d64")
        shutil.copyfile(IMAGE, self.img)
        self.reu = os.path.join(self.tmp, "root.reu")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "reu", IMAGE, self.reu],
                       check=True, capture_output=True)

    def arm(self, v, byte, nfail, st, dev=8):
        """the OPEN's own send only: LISTEN with secondary $F0 | sa to dev, its last byte held"""
        lbl = self.lbl
        sa = 15 if byte == "0" else 2

        def on_stop(num, addr, txt):
            if addr != lbl["bus_unlsn"] or st["n"] >= nfail:
                return
            m = parse_m(v._raw("m %04x %04x" % (lbl["io_pend"], lbl["io_held"])), "C")
            c = parse_m(v._raw("m %04x %04x" % (lbl["ie_dev"], lbl["ie_len2"])), "C")
            if (m.get(lbl["io_pend"]) == 1 and m.get(lbl["io_held"]) == ord(byte)
                    and c.get(lbl["ie_dev"]) == dev and c.get(lbl["ie_sa"]) == sa
                    and c.get(lbl["ie_len2"]) == 0xf0):
                st["n"] += 1
                v._raw("> %04x 01" % ST)
                if st["n"] >= nfail:
                    v._raw("del")
        v.on_stop = on_stop

    def boot_fault(self, byte, nfail):
        st = {"n": 0}
        with Mon(self.img, reu=256, reu_image=self.reu) as v:
            v.wait_shell()
            IecRestart.c64_reset(v)
            v._cmd("x")
            v.wait_for("ready.", timeout=60)
            v._cmd('l "%s" 0' % PRG)
            self.arm(v, byte, nfail, st)
            v._cmd("bk exec %x" % self.lbl["bus_unlsn"])
            v._cmd("r pc = 080d")
            v._cmd("x")
            if nfail < 3:
                v.wait_shell(timeout=180)
            else:
                v.wait_for("cannot mount root", timeout=180)
            scr = v.screen().lower()
            rec = {"byte": byte, "nfail": nfail, "n": st["n"], "reu_root": "root on reu" in scr}
            if nfail < 3:
                rec["ls"] = v.run("ls /")
        print("OPENFAULT " + json.dumps(rec), flush=True)
        self.assertEqual(st["n"], nfail, "faults injected")
        self.assertFalse(rec["reu_root"], "a lost byte in the open adopted the REU root:\n" + scr)
        if nfail < 3:
            self.assertIn("reu holds a root image", scr)
            self.assertIn("bin", rec["ls"])
            self.assertEqual(image_damage(self.img), [])

    def test_i0_byte_lost(self):
        """the EOI byte of OPEN 15 "i0" lost once: tried again, quiet boot from the drive"""
        self.boot_fault("0", 1)

    def test_hash_byte_lost(self):
        """the "#" of OPEN 2 lost once: tried again, quiet boot from the drive"""
        self.boot_fault("#", 1)

    def test_i0_lost_three_times(self):
        """every try fails: EIO, the root mount fails loudly; the REU root is not adopted"""
        self.boot_fault("0", 3)

    def test_mount9_i0_byte_lost(self):
        """the same at mount 9: one lost byte of its "i0" costs a try, the mount works"""
        cbm = os.path.join(self.tmp, "cbm.d64")
        subprocess.run(["c1541", "-format", "cbmdisk,cb", "d64", cbm, "-write",
                        os.path.join(ROOTFS, "etc", "motd"), "motd,s"], check=True, capture_output=True)
        st = {"n": 0}
        with Mon(self.img, extra=["-drive9type", "1541", "-9", cbm]) as v:
            v.wait_shell()
            self.arm(v, "0", 1, st, dev=9)
            v._cmd("bk exec %x" % self.lbl["bus_unlsn"])
            v._cmd("x")
            out = v.run("mount 9 /mnt")
            ls = v.run("ls /mnt")
        print("OPENFAULT " + json.dumps({"mount9": out, "n": st["n"], "ls": ls}), flush=True)
        self.assertEqual(st["n"], 1, "fault injected")
        self.assertEqual(out, "", "mount 9 after one lost byte")
        self.assertIn("motd", ls)


class IecDosError(unittest.TestCase):
    """A 2x error the drive itself reports (its status channel answered with the code) is not
    retried: retrying a 20-29 media error or 26 WRITE PROTECT ON only knocks the head again. A bus
    failure (a lost byte, a timeout, a status read that failed) still is (IecFault), and so are
    other codes (a 3x can be a command cut short on the bus). Drive 9 holds a copy
    of the boot image, write-protected for the write case and with every sector off track 18
    marked error 23 (an error table appended to the d64, which VICE turns into bad GCR) for the
    read case. Delta of the IOSTAT counters: a give-up and no retry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="iecdos")
        self.lbl = labels()
        if "io_nwfail" not in self.lbl:
            self.skipTest("needs IOSTAT and the write counters")

    def tearDown(self):
        for d, _, fs in os.walk(self.tmp):
            for f in fs:
                os.chmod(os.path.join(d, f), 0o644)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def counters(self, v):
        n = {}
        for k in ("io_nretry", "io_nfail", "io_nwretry", "io_nwfail"):
            a = self.lbl[k]
            b = v.mem(a, a + 1)
            n[k] = b[0] if k == "io_nwfail" else b[0] | b[1] << 8
        return n

    def run_case(self, img9, extra, cmds):
        with Vice(IMAGE, extra=["-drive9type", "1541"] + extra + ["-9", img9]) as v:
            v.wait_shell()
            n0 = self.counters(v)
            out = [v.run(c, timeout=300) for c in cmds]
            n1 = self.counters(v)
            out.append(v.run("ls /"))
        d = {k: n1[k] - n0[k] for k in n0}
        print("DOSERR " + json.dumps({"out": out, "delta": d}), flush=True)
        self.assertIn("bin", out[-1], "the system is still usable")
        return out, d

    def test_write_protect(self):
        """26 WRITE PROTECT ON: the write gives up after one try"""
        img9 = os.path.join(self.tmp, "ro.d64")
        shutil.copyfile(IMAGE, img9)
        os.chmod(img9, 0o444)
        out, d = self.run_case(img9, ["-attach9ro"], ["mount 9 /mnt", "cp /etc/motd /mnt/home/w"])
        self.assertTrue(any(o for o in out[:2]), "the write failed loudly")
        self.assertGreaterEqual(d["io_nwfail"], 1)
        self.assertEqual(d["io_nwretry"], 0, "a write the drive refused was retried")

    def test_read_error(self):
        """23 READ ERROR (checksum) on every sector off track 18: each read gives up after one try"""
        img9 = os.path.join(self.tmp, "bad.d64")
        with open(IMAGE, "rb") as f:
            data = f.read()[:174848]
        err = bytearray()
        for t in range(1, 36):
            n = 21 if t <= 17 else 19 if t <= 24 else 18 if t <= 30 else 17
            err += bytes([1 if t == 18 else 5] * n)     # 1: no error, 5: error 23
        with open(img9, "wb") as f:
            f.write(data + bytes(err))
        out, d = self.run_case(img9, [], ["mount 9 /mnt", "cat /mnt/etc/motd"])
        self.assertTrue(any(o for o in out[:2]), "the read failed loudly")
        self.assertGreaterEqual(d["io_nfail"], 1)
        self.assertEqual(d["io_nretry"], 0, "a read the drive reported bad was retried")


if __name__ == "__main__":
    unittest.main()
