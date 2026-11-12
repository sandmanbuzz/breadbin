"""Host tests for experiments/iec-stall/session5.py (session 5 acceptance runner), against the fake Ultimate
only, on a virtual clock. A scripted C64 stand-in turns the runner's keystrokes into screen text and results.
No real device is touched; the tools disk is built with ca65/ld65 from a stand-in release tree made of this
repo's build (skipped when it is not built)."""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "experiments", "iec-stall"))

import fake_ultimate  # noqa: E402
import mkimage  # noqa: E402
import session  # noqa: E402
import session5  # noqa: E402
from ultimate import Ultimate  # noqa: E402
from ultimatetest import UltimateTarget  # noqa: E402

BUILD = os.path.join(ROOT, "build")
BUILT = all(os.path.exists(os.path.join(BUILD, f)) for f in
            ("breadbin.prg", "breadbin.d64", "kernel.lbl", os.path.join("lib", "breadbin.lib")))
HAVE_CC65 = shutil.which("ca65") is not None and shutil.which("ld65") is not None
# IOSTAT labels at the release's addresses, added to the stand-in tree's kernel.lbl where this build lacks them
IOLBL = {"io_nread": 0xE663, "io_nretry": 0xE665, "io_nfail": 0xE667, "io_neoi": 0xE669, "io_ltrk": 0xE66B,
         "io_lsct": 0xE66C, "io_lidx": 0xE66D, "io_ltry": 0xE66E, "io_lst": 0xE66F, "io_lwn": 0xE670,
         "io_nwretry": 0xE671, "io_nwfail": 0xE673}


def screen_codes(lines):
    out = bytearray(b"\x20" * 1000)
    for r, l in enumerate(lines[-25:]):
        for c, ch in enumerate(l[:40]):
            out[r * 40 + c] = ord(ch) - 96 if "a" <= ch <= "z" else ord(ch)
    return bytes(out)


class Sim:
    """Virtual clock and a C64 that reacts to what the runner writes into the fake's RAM.

    w: dict for the W result (state, done, mis, st, dos, free, cycle, step) or "hang".
    boots: queue of "ok" | "load_error" | "corrupt" | "hang" (no login) | "panic" for each machine load.
    wv: "pass" | "mis" | "nobus" | "hang";  sums: queue of "ok" | "bad" for each cksum;
    io: dict of IOSTAT counter values to show after a workload."""

    def __init__(self, fake, facts, labels, w=None, boots=(), wv="pass", sums=(), io=None, interrupt_at=None):
        self.fake, self.facts, self.labels = fake, facts, labels
        self.w, self.boots, self.wv, self.sums = w, list(boots), wv, list(sums)
        self.io = io or {}
        self.t = 0.0
        self.resets = fake.resets
        self.lines = ["ready."]
        self.mode = "basic"
        self.kbuf = ""
        self.log = []            # (t, what)
        self.requests = []       # (t, method, path) of every client request
        self.big_sleeps = []     # (start, end) of sleeps longer than 30 s
        self.interrupt_at = interrupt_at
        self.loaded = None
        self.sync()

    # clock
    def monotonic(self):
        return self.t

    time = now = monotonic

    def sleep(self, s):
        s = max(0.0, s)
        if s > 30:
            self.big_sleeps.append((self.t, self.t + s))
        self.step()
        self.t += s
        self.step()

    def sync(self):
        rows = [l[i:i + 40] for l in self.lines for i in range(0, max(len(l), 1), 40)]
        vis = rows[-24:]
        self.fake.ram[0xD6] = len(vis)
        self.fake.ram[0x0400:0x0400 + 1000] = screen_codes(vis)

    def step(self):
        f = self.fake
        if f.resets != self.resets:
            self.resets = f.resets
            self.lines, self.mode, self.kbuf = ["**** commodore 64 ****", "ready."], "basic", ""
            self.loaded = None
            self.log.append((self.t, "reset"))
        if f.ram[0xC6]:
            n = f.ram[0xC6]
            raw = bytes(f.ram[0x0277:0x0277 + n])
            f.ram[0xC6] = 0
            self.kbuf += "".join("\r" if b == 13 else chr(b + 32) if 0x41 <= b <= 0x5A else chr(b) for b in raw)
            *done, self.kbuf = self.kbuf.split("\r")
            for cmd in done:
                self.command(cmd)
        self.sync()

    def command(self, cmd):
        self.log.append((self.t, cmd))
        if self.interrupt_at and cmd.startswith(self.interrupt_at):
            raise KeyboardInterrupt
        if self.mode == "basic":
            self.lines.append(cmd)
            if cmd.startswith("load"):
                self.load()
            elif cmd == "run":
                self.run()
            return
        if self.mode == "login":
            self.lines.append("login: " + cmd)
            self.lines.append("/ $")
            self.mode = "shell"
            return
        if self.mode == "dead":
            return
        self.lines[-1] = "/ $ " + cmd
        out = self.shell(cmd)
        if self.mode == "dead":
            return
        self.lines += out + ["/ $"]
        if cmd == "clear":
            self.lines = ["/ $"]

    def load(self):
        how = self.boots.pop(0) if self.boots else "ok"
        self.loaded = how
        img = mkimage.Image(self.fake.mounts[-1]["data"])
        prg = bytearray(img.cbm_read(img.cbm_files()[0][0]))
        base = prg[0] | prg[1] << 8
        if how == "load_error":
            self.lines += ["", "searching for *", "loading", "?load  error", "ready."]
            return
        if how == "corrupt":
            prg[500] ^= 0xFF
        self.fake.ram[base:base + len(prg) - 2] = prg[2:]
        end = base + len(prg) - 2
        self.fake.ram[0xAE:0xB0] = bytes([end & 255, end >> 8])
        self.lines += ["", "searching for *", "loading", "ready."]

    def run(self):
        how = self.loaded
        if how is None:                       # nothing loaded since the reset: the W program poked in
            self.run_w()
            return
        if how == "hang":
            self.mode, self.lines = "dead", ["breadbin"]
            return
        if how == "panic":
            self.mode, self.lines = "dead", ["breadbin", "panic: bus"]
            return
        for n in session5.IO_COLS:
            self.poke_io(n, 0)
        self.mode, self.lines = "login", ["breadbin", "login:"]

    def poke_io(self, name, value):
        a = self.labels[name]
        w = 1 if name == "io_nwfail" else 2
        self.fake.ram[a:a + w] = value.to_bytes(w, "little")

    def run_w(self):
        w = self.w or {}
        if w == "hang":
            r = bytearray(session5.W_LEN)
            r[0:3], r[14] = b"S5W", 1
            self.fake.ram[session5.W_RESULT:session5.W_RESULT + session5.W_LEN] = r
            self.mode = "dead"
            return
        r = bytearray(session5.W_LEN)
        r[0:4] = b"S5W\x01"
        r[4:6] = w.get("done", 0).to_bytes(2, "little")
        r[6:8] = w.get("mis", 0).to_bytes(2, "little")
        r[8:10] = w.get("st", 0).to_bytes(2, "little")
        r[10:12] = w.get("dos", 0).to_bytes(2, "little")
        r[14] = w.get("state", 2)
        r[15:17] = w.get("cycle", 0).to_bytes(2, "little")
        r[17] = w.get("step", 0)
        r[18:20] = w.get("free", 664).to_bytes(2, "little")
        r[20:23] = (1000).to_bytes(3, "big")
        r[23:26] = (1000 + 60 * 3 * max(w.get("done", 0), 1)).to_bytes(3, "big")
        self.fake.ram[session5.W_RESULT:session5.W_RESULT + session5.W_LEN] = r
        self.lines += ["s5w end n 300 done %d" % w.get("done", 0), "s5w state %d" % w.get("state", 2), "ready."]

    def shell(self, cmd):
        if cmd in ("clear", "mount 9 /mnt"):
            return []
        if cmd == "ls /bin":
            names = self.facts["bin"]
            return ["".join(n.ljust(13) for n in names[i:i + 3]).rstrip() for i in range(0, len(names), 3)]
        if cmd == "/mnt/cksum /bin/as":
            how = self.sums.pop(0) if self.sums else "ok"
            return [self.facts["cksum"] if how == "ok" else "1 7686 /bin/as"]
        if cmd == "wc /bin/as":
            return [self.facts["wc"]]                 # right-aligned, as wc prints it
        m = re.match(r"/mnt/wv (\d+) /home/s5b /bin/as (\d+)$", cmd)
        if m:
            n = int(m.group(1))
            assert int(m.group(2)) == self.labels["io_nread"]
            for k, v in self.io.items():
                self.poke_io(k, v)
            if self.wv == "hang":
                self.mode = "dead"
                return []
            if self.wv == "mis":
                return ["wv fail c=7 s=10 e=0 i=3 g=1 w=2", f"wv end n={n} ok=6 mis=1 err=0 nobus=0"]
            nob = n if self.wv == "nobus" else 0
            return [f"wv c={c}" for c in range(50, n + 1, 50)][-3:] + [f"wv end n={n} ok={n} mis=0 err=0 nobus={nob}"]
        return [f"sh: {cmd.split()[0]}: not found"]


class LoggingUltimate(Ultimate):
    sim = None

    def request(self, method, path, params=None, body=None, content_type=None):
        if self.sim is not None:
            self.sim.requests.append((self.sim.t, method, path))
        return super().request(method, path, params, body, content_type)


def standin_tree(dst):
    """A tree shaped like the release worktree, from this repo's build; IOSTAT labels added if absent."""
    for sub in ("build/lib", "src", "tools"):
        os.makedirs(os.path.join(dst, sub), exist_ok=True)
    for f in ("breadbin.prg", "breadbin.d64", "kernel.lbl", "lib/breadbin.lib"):
        shutil.copyfile(os.path.join(BUILD, f), os.path.join(dst, "build", f))
    shutil.copytree(os.path.join(ROOT, "include"), os.path.join(dst, "include"))
    shutil.copyfile(os.path.join(ROOT, "src", "prog.cfg"), os.path.join(dst, "src", "prog.cfg"))
    for f in ("cx.py", "mkimage.py"):
        shutil.copyfile(os.path.join(ROOT, "tools", f), os.path.join(dst, "tools", f))
    lbl = os.path.join(dst, "build", "kernel.lbl")
    have = open(lbl).read()
    with open(lbl, "a") as f:
        for n, a in IOLBL.items():
            if f".{n}\n" not in have:
                f.write(f"al {a:06X} .{n}\n")
    return dst


@unittest.skipUnless(BUILT and HAVE_CC65, "needs make (build/) and cc65")
class Runner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.tree = standin_tree(os.path.join(cls.tmp, "tree"))
        cls.tools = session5.build_tools(cls.tree, os.path.join(cls.tmp, "tools.d64"))
        cls.p = session5.tree_paths(cls.tree)
        cls.facts = session5.release_facts(cls.p)
        cls.labels = session5.labels_of(cls.p["lbl"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.fake = fake_ultimate.FakeUltimate().start()
        self.addCleanup(self.fake.stop)
        for c, i, _, normal in session.CONFIG:
            self.fake.configs[(c, i)] = normal
        self.fake.configs[session.KERNAL_ITEM] = session.NORMAL_KERNAL
        self.start_cfg = dict(self.fake.configs)
        self.res = tempfile.mkdtemp(dir=self.tmp)
        self.env = dict(os.environ)
        os.environ.pop("BREADBIN_ULTIMATE_BUS", None)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.env)))

    def go(self, argv, **simkw):
        sim = Sim(self.fake, self.facts, self.labels, **simkw)
        client = LoggingUltimate(self.fake.host, port=self.fake.port)
        client.sim = sim
        self.sim = sim

        def factory(image):
            return UltimateTarget(image, client=client, clock=sim)
        out = []
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status = session5.main(argv + ["--tree", self.tree, "--results", self.res, "--tools-d64", self.tools,
                                           "--reboot-wait", "0", "--no-prompt"],
                                   client=client, clock=sim, out=lambda *a, **k: out.append(" ".join(map(str, a))),
                                   target_factory=factory)
        self.out = "\n".join(out)
        return status

    def tsv(self, arm):
        rows = [l.split("\t") for l in open(os.path.join(self.res, f"{arm}.tsv")).read().splitlines()
                if not l.startswith("#")]
        return [dict(zip(rows[0], r)) for r in rows[1:]]

    def assert_restored(self):
        self.assertEqual(self.fake.configs, self.start_cfg)
        log = open(os.path.join(self.res, "session5.log.tsv")).read()
        self.assertIn("config set, read back", log)
        self.assertIn("config after restore", log)
        set_puts = [p for p in self.fake.config_puts if p[1] == "IEC Drive"]
        self.assertEqual([p[2] for p in set_puts][-2:], ["Disabled", "Enabled"])

    def no_request_between(self, start, end):
        inside = [r for r in self.sim.requests if start < r[0] < end]
        self.assertEqual(inside, [], "a request to the machine during the workload")

    # ---- W
    def test_w_pass_reads_once_after_the_wait(self):
        st = self.go(["w", "-n", "300"], w=dict(state=2, done=300))
        self.assertEqual(st, 0, self.out)
        row = self.tsv("w")[0]
        self.assertEqual((row["outcome"], row["done"], row["mismatches"]), ("pass", "300", "0"))
        self.assertEqual(row["s_per_cycle"], "3.00")
        (s, e), = self.sim.big_sleeps
        self.assertEqual(e - s, session5.W_WAIT_BASE + 300 * session5.W_CYCLE_EST * session5.W_WAIT_FACTOR)
        run_t = [t for t, c in self.sim.log if c == "run"][0]
        self.assertEqual(run_t, s)
        self.no_request_between(s, e)
        self.assert_restored()

    def test_w_program_is_written_and_checked(self):
        self.go(["w", "-n", "7"], w=dict(state=2, done=7))
        prog, end = session5.tokenize(session5.w_program(7))
        self.assertEqual(bytes(self.fake.ram[0x0801:0x0801 + len(prog)]), prog)
        self.assertEqual(bytes(self.fake.ram[0x2D:0x33]), bytes([end & 255, end >> 8]) * 3)

    def test_w_refused_is_its_own_status(self):
        st = self.go(["w"], w=dict(state=4, done=0, free=0))
        self.assertEqual(st, session5.EXIT_REFUSED)
        self.assertEqual(self.tsv("w")[0]["outcome"], "refused")
        self.assert_restored()

    def test_w_mismatch_fails_and_captures(self):
        st = self.go(["w"], w=dict(state=3, done=41, mis=1, cycle=42, step=9))
        self.assertEqual(st, 1)
        row = self.tsv("w")[0]
        self.assertEqual((row["outcome"], row["fail_cycle"], row["fail_step"]), ("FAIL", "42", "9"))
        self.assertIn("result", open(os.path.join(self.res, "w.capture.txt")).read())
        self.assert_restored()

    def test_w_still_running_at_the_limit_is_a_hang(self):
        st = self.go(["w"], w="hang")
        self.assertEqual(st, 1)
        self.assertEqual(self.tsv("w")[0]["outcome"], "HANG")
        self.assert_restored()

    # ---- B
    def test_b_pass_with_counters(self):
        st = self.go(["b", "-n", "300"], io={"io_nread": 900, "io_nretry": 2})
        self.assertEqual(st, 0, self.out)
        row = self.tsv("b")[0]
        self.assertEqual((row["outcome"], row["wv_ok"], row["io_nread"], row["io_nretry"]), ("pass", "300", "900", "2"))
        self.assertIn("io_nretry=2", row["note"])
        cmd_t = [t for t, c in self.sim.log if c.startswith("/mnt/wv")][0]
        (s, e), = [b for b in self.sim.big_sleeps if b[0] >= cmd_t]
        self.no_request_between(s, e)
        self.assert_restored()

    def test_b_failures(self):
        for kw, outcome in ((dict(wv="mis"), "FAIL"), (dict(io={"io_nfail": 1}), "FAIL"),
                            (dict(io={"io_nwfail": 1}), "FAIL"), (dict(wv="hang"), "HANG"),
                            (dict(boots=["load_error"]), "LOAD_ERROR"), (dict(boots=["corrupt"]), "LOAD_ERROR")):
            with self.subTest(kw=kw):
                self.res = tempfile.mkdtemp(dir=self.tmp)
                st = self.go(["b"], **kw)
                self.assertEqual(st, 1, self.out)
                self.assertEqual(self.tsv("b")[0]["outcome"], outcome)
                self.assertTrue(os.path.exists(os.path.join(self.res, "b.capture.txt")))
                self.assert_restored()

    def test_b_nobus_is_invalid(self):
        st = self.go(["b"], wv="nobus")
        self.assertEqual(st, session5.EXIT_INVALID)
        self.assertEqual(self.tsv("b")[0]["outcome"], "INVALID")

    # ---- R
    def test_r_pass(self):
        st = self.go(["r", "-n", "3"])
        self.assertEqual(st, 0, self.out)
        rows = self.tsv("r")
        self.assertEqual([r["outcome"] for r in rows], ["pass"] * 3)
        self.assertEqual(rows[0]["ls_bin"], f"ok {len(self.facts['bin'])}")
        self.assertEqual(len([c for _, c in self.sim.log if c.startswith("load")]), 3)
        self.assert_restored()

    def test_r_pass_with_wc(self):
        st = self.go(["r", "-n", "2", "--sum", "wc"])
        self.assertEqual(st, 0, self.out)
        self.assertEqual([r["outcome"] for r in self.tsv("r")], ["pass"] * 2)

    def test_r_stops_at_the_first_failure(self):
        st = self.go(["r", "-n", "5"], sums=["ok", "bad"])
        self.assertEqual(st, 1)
        rows = self.tsv("r")
        self.assertEqual([r["outcome"] for r in rows], ["pass", "FAIL"])
        self.assertEqual(len([c for _, c in self.sim.log if c.startswith("load")]), 2)
        cap = open(os.path.join(self.res, "r.capture.txt")).read()
        self.assertIn("cycle 2", cap)
        self.assertIn("decode.py", cap)
        self.assertTrue(os.path.exists(os.path.join(self.res, "r-kernel.prg.stall")))

    def test_r_hang_and_panic(self):
        for boot, outcome in (("hang", "HANG"), ("panic", "HANG")):
            with self.subTest(boot=boot):
                self.res = tempfile.mkdtemp(dir=self.tmp)
                st = self.go(["r", "-n", "2"], boots=[boot])
                self.assertEqual(st, 1)
                self.assertEqual(self.tsv("r")[0]["outcome"], outcome)

    # ---- plan, refusals, interruption
    def test_plan_stops_after_a_failed_arm(self):
        plan = os.path.join(self.res, "p.plan")
        with open(plan, "w") as f:
            f.write("1 W 300\n2 B 300\n3 R 50\n")
        st = self.go(["plan", plan], w=dict(state=3, done=3, dos=1, step=5))
        self.assertEqual(st, 1)
        self.assertFalse(os.path.exists(os.path.join(self.res, "b.tsv")))
        self.assertIn("nothing more runs", self.out)
        self.assert_restored()

    def test_the_committed_plan(self):
        order = session5.parse_plan(open(os.path.join(ROOT, "experiments", "iec-stall", "plans",
                                                      "session5.plan")).read())
        self.assertEqual(order, [("1", "W", 300), ("2", "B", 300), ("3", "R", 50)])

    def test_interrupt_restores_the_config(self):
        st = self.go(["r", "-n", "3"], interrupt_at="ls")
        self.assertEqual(st, session5.EXIT_STOP)
        self.assert_restored()

    def test_refuses_a_non_jiffy_kernal_before_any_change(self):
        self.fake.configs[session.KERNAL_ITEM] = ""
        with self.assertRaises(SystemExit):
            self.go(["w"])
        self.assertEqual(self.fake.config_puts, [])

    def test_refuses_another_boot_bus(self):
        os.environ["BREADBIN_ULTIMATE_BUS"] = "9"
        with self.assertRaises(SystemExit):
            self.go(["r"])
        self.assertEqual(self.fake.config_puts, [])


class Pure(unittest.TestCase):
    def test_tokenizer_basics(self):
        tok = session5.tokenize_line
        self.assertEqual(tok('print#15,"s0:s5w"'), bytes([0x98]) + b'15,"S0:S5W"')
        self.assertEqual(tok("input#15,e"), bytes([0x84]) + b"15,E")
        self.assertEqual(tok('rem print "x'), bytes([0x8F]) + b' PRINT "X')
        self.assertEqual(tok("data to,go:print"), bytes([0x83]) + b" TO,GO:" + bytes([0x99]))
        self.assertEqual(tok("?a"), bytes([0x99]) + b"A")
        self.assertEqual(tok("if a<>w then 640"), bytes([0x8B]) + b" A" + bytes([0xB3, 0xB1]) + b"W "
                         + bytes([0xA7]) + b" 640")

    @unittest.skipUnless(shutil.which("petcat"), "petcat (VICE) not installed")
    def test_tokenizer_matches_petcat(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt, prg = os.path.join(tmp, "w.txt"), os.path.join(tmp, "w.prg")
            with open(txt, "w") as f:
                f.write(session5.w_program(300))
            subprocess.run(["petcat", "-w2", "-o", prg, "--", txt], check=True, capture_output=True)
            prog, end = session5.tokenize(session5.w_program(300))
            self.assertEqual(open(prg, "rb").read(), b"\x01\x08" + prog)

    def test_program_limits(self):
        with self.assertRaises(ValueError):
            session5.w_program(40000)
        prog, end = session5.tokenize(session5.w_program(300))
        self.assertLess(end, 0x9F00)
        self.assertEqual(end, 0x0801 + len(prog))

    def test_parse_and_judge_w(self):
        r = bytearray(29)
        r[0:4] = b"S5W\x01"
        r[4:6] = (300).to_bytes(2, "little")
        r[14] = 2
        d = session5.parse_w(r)
        self.assertEqual(session5.judge_w(d, 300), ("pass", False))
        self.assertEqual(session5.judge_w(d, 299), ("FAIL", True))
        r[8] = 1
        self.assertEqual(session5.judge_w(session5.parse_w(r), 300), ("FAIL", True))
        self.assertEqual(session5.judge_w(session5.parse_w(bytes(29)), 300), ("NO_RESULT", True))

    def test_posix_cksum(self):
        self.assertEqual(session5.posix_cksum(b""), 4294967295)
        self.assertEqual(session5.posix_cksum(b"hello\n"), 3015617425)


if __name__ == "__main__":
    unittest.main()
