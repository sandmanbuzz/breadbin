"""Host tests for experiments/iec-stall/session.py (the hardware trial runner), against the fake
Ultimate only. A small scripted C64 stand-in turns the runner's keystrokes and PRG runs into
screen text on a virtual clock, so a 90-minute plan runs in a second and no real device is touched.
"""
import os
import sys
import tempfile
import threading
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "experiments", "iec-stall"))

import fake_ultimate  # noqa: E402
import mkimage  # noqa: E402
import session  # noqa: E402
from ultimate import Ultimate  # noqa: E402

CTRL = bytes((i * 7) & 0xFF for i in range(500))      # the control disk's file, loaded at $0801


def screen_codes(lines):
    out = bytearray(b"\x20" * 1000)
    for r, l in enumerate(lines[-25:]):
        for c, ch in enumerate(l[:40]):
            out[r * 40 + c] = ord(ch) - 96 if "a" <= ch <= "z" else ord(ch)
    return bytes(out)


class Sim:
    """Virtual clock plus a C64 that reacts to what the runner writes into fake.ram.

    loads / boots are queues of behaviours, consumed in the order the runner asks:
      loads: ok | hang | error | corrupt | ctrl_bad     boots: ok | hang | panic
    """

    def __init__(self, fake, image_prg, loads=(), boots=(), labels=None):
        self.fake, self.prg = fake, image_prg
        self.loads, self.boots = list(loads), list(boots)
        self.labels = labels or {}
        self.t = 0.0
        self.seen_resets, self.seen_runs = 0, 0
        self.lines = []
        self.events = []          # (virtual time, what)
        self.big_reads = []       # (virtual time, address, length) of reads >= 256 bytes
        self.pending = []         # (time, fn)
        self.kbuf = ""
        fake.on_readmem = self.on_read
        self.sync_screen()

    # clock interface
    def now(self):
        return self.t

    def sleep(self, s):
        end = self.t + max(0.0, s)
        while self.t < end:
            self.t = min(self.t + 0.5, end)
            self.step()

    def on_read(self, a, ln):
        if ln >= 256:
            self.big_reads.append((self.t, a, ln))

    def sync_screen(self):
        self.fake.ram[0x0400:0x0400 + 1000] = screen_codes(self.lines)

    def at(self, dt, fn):
        self.pending.append((self.t + dt, fn))

    def step(self):
        f = self.fake
        if f.resets != self.seen_resets or len(f.runs) != self.seen_runs:
            ran = len(f.runs) != self.seen_runs
            self.seen_resets, self.seen_runs = f.resets, len(f.runs)
            self.pending.clear()
            self.lines = [] if ran else ["**** commodore 64 ****", "ready."]
            self.events.append((self.t, "run_prg" if ran else "reset"))
            if ran:
                self.boot(40)
        if f.ram[0xC6]:
            n = f.ram[0xC6]
            text = bytes(f.ram[0x0277:0x0277 + n]).decode("latin-1").lower()
            f.ram[0xC6] = 0
            self.kbuf += text                 # keys arrive 8 at a time; a line ends at Return
            *done, self.kbuf = self.kbuf.split("\r")
            for cmd in done:
                if cmd:
                    self.command(cmd)
        for p in [p for p in self.pending if p[0] <= self.t]:
            self.pending.remove(p)
            p[1]()
        self.sync_screen()

    def command(self, cmd):
        self.events.append((self.t, cmd))
        self.lines.append(cmd)
        if cmd.startswith("load"):
            how = self.loads.pop(0)
            self.lines += ["searching for " + cmd.split('"')[1], "loading"]
            ctrl = cmd.endswith(",8")
            data = CTRL if ctrl else self.prg[2:]
            addr = 0x0801 if ctrl else (self.prg[0] | self.prg[1] << 8)
            if how == "hang":
                return
            if how == "error":
                self.at(5, lambda: self.lines.extend(["?load error", "ready."]))
                return
            if how == "corrupt":
                data = bytes([data[0] ^ 1]) + data[1:]
            if how == "ctrl_bad":
                data = data[:-1]

            def done():
                f = self.fake
                f.ram[addr:addr + len(data)] = data
                f.ram[0x2B:0x2D] = (0x0801).to_bytes(2, "little")
                f.ram[0xAE:0xB0] = (addr + len(data)).to_bytes(2, "little")
                self.lines.append("ready.")
            self.at(8, done)
        elif cmd == "run":
            self.boot(25)

    def boot(self, dt):
        how = self.boots.pop(0)
        if how == "ok":
            def login():
                for n, a in self.labels.items():
                    self.fake.ram[a] = {"io_nread": 200, "io_nretry": 3, "io_nfail": 0,
                                        "io_neoi": 9}.get(n, 0x55)
                self.lines.append("login:")
            self.at(dt, login)
        elif how == "panic":
            self.at(10, lambda: self.lines.append("kernel panic: root mount"))
        elif how == "hang":
            self.fake.ram[0x90] = 0x02       # a receive timeout in ST: the class S signature
            self.fake.ram[0xDD00] = 0x87


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = fake_ultimate.FakeUltimate().start()
        self.addCleanup(self.fake.stop)
        for k, v in [(("SoftIEC Drive Settings", "IEC Drive"), "Enabled"),
                     (("Drive A Settings", "Drive"), "Enabled"),
                     (("Drive A Settings", "Drive Bus ID"), "9"),
                     (("C64 and Cartridge Settings", "DMA Load Mimics ID:"), "8"),
                     (("C64 and Cartridge Settings", "Kernal ROM"), "JiffyDOS-C64.bin")]:
            self.fake.configs[k] = v
        self.u = Ultimate(self.fake.host, port=self.fake.port)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.prg = (0x0801).to_bytes(2, "little") + bytes((i * 13 + 1) & 0xFF for i in range(700))
        self.p = lambda n: os.path.join(d, n)
        open(self.p("b.prg"), "wb").write(self.prg)
        img = mkimage.Image()
        img.write_cbm(b"BREADBIN", self.prg)
        open(self.p("b.d64"), "wb").write(bytes(img.data))
        # counters at 4 bytes' spacing so the width guess is 4; one last-event label
        open(self.p("b.lbl"), "w").write(
            "al 00C000 .io_nread\nal 00C004 .io_nretry\nal 00C008 .io_nfail\n"
            "al 00C00C .io_neoi\nal 00C010 .io_last_ev\nal 00C012 .zz\n"
            "al 00C100 .io_out\nal 00C103 .io_n\nal 00C10B .ie_dev\n")
        self.labels = session.read_labels(self.p("b.lbl"))
        self.out = self.p("res.tsv")

    def plan(self, text):
        open(self.p("plan.txt"), "w").write(text)

    def run_session(self, sim, extra=(), ask=None, plan=None):
        if plan:
            self.plan(plan)
        asked = []

        def ask_fn(t):
            asked.append(t)
            return (ask or (lambda t: "n" if t.startswith("Is the drive LED") else ""))(t)
        self.asked = asked
        argv = [self.p("plan.txt"), "--image", self.p("b.prg"), "--d64", self.p("b.d64"),
                "--out", self.out, "--disk-id", "T1", "--control-file", "CTRLFILE",
                "--commit", "v0-test", "--drive-on-minutes-ago", "30", "--reboot-wait", "0",
                *extra]
        self.status = session.main(argv, client=self.u, clock=sim, ask=ask_fn)

    def rows(self):
        lines = [l for l in open(self.out).read().splitlines() if not l.startswith("#")]
        hdr = lines[0].split("\t")
        self.assertEqual(hdr, session.COLUMNS)
        out = []
        for l in lines[1:]:
            f = l.split("\t")
            self.assertEqual(len(f), len(hdr), l)
            out.append(dict(zip(hdr, f)))
        return out

    def comments(self):
        return [l for l in open(self.out).read().splitlines() if l.startswith("#")]

    def assertConfigRestored(self):
        self.assertEqual(self.fake.configs[("SoftIEC Drive Settings", "IEC Drive")], "Enabled")
        self.assertEqual(self.fake.configs[("Drive A Settings", "Drive Bus ID")], "9")
        self.assertEqual(self.fake.configs[("C64 and Cartridge Settings", "DMA Load Mimics ID:")], "8")
        self.assertFalse(self.fake.paused)


class Plan(unittest.TestCase):
    def test_parse_text_and_json(self):
        p = session.parse_plan("# c\n1 C 12\n2 kbd 10  # cycle\n3 C 6\n")
        self.assertEqual(p, [(1, "C", 12), (2, "KBD", 10), (3, "C", 6)])
        self.assertEqual(session.parse_plan('[[1,"C",2],{"block":2,"arms":"KB","count":1}]'),
                         [(1, "C", 2), (2, "KB", 1)])
        for bad in ("1 X 3", "1 C", "1 C 0"):
            with self.assertRaises(ValueError):
                session.parse_plan(bad)

    def test_protocol_order(self):
        o = session.expand(session.parse_plan("1 C 12\n2 KBD 10\n3 C 6"))
        self.assertEqual(len(o), 48)
        self.assertEqual([a for _, _, a in o[12:18]], list("KBDKBD"))
        self.assertEqual([i for _, i, _ in o], list(range(1, 49)))
        self.assertEqual({b for b, _, _ in o}, {1, 2, 3})

    def test_dry_run_prints_hand_actions(self):
        lines = []
        session.dry_run(session.expand(session.parse_plan("1 C 2\n2 KBD 1\n3 C 1")), "D9", lines.append)
        hands = [l for l in lines if l.startswith("HAND")]
        self.assertEqual(len(hands), 3)
        self.assertIn("insert the control disk in device 8, write-protected, then press Enter", hands[0])
        self.assertIn("Breadbin disk (D9)", hands[1])

    def test_d64_first_prg(self):
        img = mkimage.Image()
        body = bytes(range(256)) * 3
        img.write_cbm(b"BREADBIN", body)
        self.assertEqual(session.d64_first_prg(bytes(img.data)), ("BREADBIN", body))


class Full(Base):
    def test_small_plan_runs_to_completion(self):
        sim = Sim(self.fake, self.prg, loads=["ok", "ok", "ok", "ok"], boots=["ok", "ok", "ok"],
                  labels=self.labels)
        plan = "1 C 1\n2 KBD 1\n3 C 1\n"
        self.run_session(sim, plan=plan)
        self.assertEqual(self.status, 0)
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual([r["arm"] for r in rows], list("CKBDC"))
        self.assertEqual([r["outcome"] for r in rows], ["pass"] * 5)
        self.assertEqual([r["trial"] for r in rows], ["1", "2", "3", "4", "5"])
        r = rows[2]                                    # arm B: counters from the labels
        self.assertEqual((r["io_nread"], r["io_nretry"], r["io_nfail"], r["io_neoi"]),
                         ("200", "3", "0", "9"))
        self.assertIn("io_last_ev=", r["io_last"])
        self.assertEqual(rows[3]["io_nread"], "200")   # arm D too
        self.assertEqual(rows[1]["io_nread"], "")      # K reads no counters
        self.assertEqual(len(r["image_sha"]), 16)
        self.assertEqual((r["commit"], r["disk_id"], r["session"]), ("v0-test", "T1", "1"))
        self.assertTrue(r["start_iso"])
        self.assertAlmostEqual(float(rows[0]["min_drive_on"]) - float(rows[0]["min_session"]), 30, 1)
        self.assertIn("len=500", rows[0]["detail"])
        self.assertEqual(zlib.crc32(CTRL), int(rows[0]["detail"].split("crc32=")[1][:8], 16))
        # hand actions: control disk, Breadbin disk, control disk again
        hands = [t for t in self.asked if t.startswith("HAND")]
        self.assertEqual(len(hands), 3)
        self.assertConfigRestored()
        self.assertTrue(any("config after restore" in c for c in self.comments()))
        self.assertTrue(any("config set, read back" in c for c in self.comments()))
        # the configuration was applied: soft IEC off during the run
        self.assertIn(("SoftIEC Drive Settings", "IEC Drive", "Disabled"), self.fake.config_puts)

    def test_dma_rule_no_screen_read_early_in_a_transfer(self):
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, boots=["ok", "ok"], labels=self.labels)
        self.run_session(sim, plan="1 C 1\n2 KBD 1\n")
        starts = [t for t, what in sim.events if what.startswith("load") or what == "run"
                  or what == "run_prg"]
        self.assertEqual(len(starts), 5)           # C load, K load, B load, B run, D run_prg
        screen_reads = [t for t, a, ln in sim.big_reads if a == 0x0400]
        for t0 in starts:
            # the sim notices a command up to one 0.5 s step after the runner sent it
            early = [t for t in screen_reads if t0 <= t < t0 + session.FIRST_READ - 1]
            self.assertEqual(early, [], f"screen-sized read inside {session.FIRST_READ} s of {t0}")
        # and big reads of the loaded range happen only after READY. (K/C verification)
        self.assertTrue(screen_reads)

    def test_missing_labels_leave_counters_blank(self):
        os.remove(self.p("b.lbl"))
        sim = Sim(self.fake, self.prg, loads=["ok"], boots=["ok", "ok"])
        self.run_session(sim, plan="2 BD 1\n", extra=[])
        rows = [r for r in self.rows() if r["outcome"] == "pass"]
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertEqual((r["io_nread"], r["io_nretry"], r["io_nfail"], r["io_neoi"], r["io_last"]),
                             ("", "", "", "", ""))

    def test_failure_outcomes(self):
        sim = Sim(self.fake, self.prg,
                  loads=["ok", "error", "corrupt", "ok", "ok", "ctrl_bad"],
                  boots=["panic"], labels=self.labels)
        self.run_session(sim, plan="1 C 2\n2 KKB 1\n3 C 1\n")   # C, C(bad len), K err, K corrupt, B ok-load+panic
        out = [(r["arm"], r["outcome"]) for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual(out, [("C", "pass"), ("C", "LOAD ERROR"),
                               ("K", "mismatch"), ("K", "pass"), ("B", "root-mount panic"),
                               ("C", "mismatch")])


class Timeouts(Base):
    def test_timeout_records_dumps_resets_and_asks_about_the_led(self):
        sim = Sim(self.fake, self.prg, loads=["hang", "ok"], boots=["hang", "hang"],
                  labels=self.labels)
        answers = iter(["y", "", "n", "n"])        # LED on (then power-cycle Enter), LED off, LED off

        def ask(t):
            return next(answers) if (t.startswith("Is the drive LED") or t.startswith("power-cycle")) else ""
        self.run_session(sim, ask=ask, plan="2 KBD 1\n")
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual([(r["arm"], r["outcome"]) for r in rows],
                         [("K", "LOADING hang"), ("B", "stall"), ("D", "stall")])
        self.assertIn("st=02", rows[1]["dump"])
        self.assertIn("dd00=87", rows[1]["dump"])
        self.assertIn("power-cycled", rows[0]["note"])
        self.assertIn("power-cycled before this trial", rows[1]["note"])
        self.assertIn("LED off", rows[2]["note"])
        self.assertGreaterEqual(float(rows[0]["seconds"]), 120)
        self.assertEqual(float(rows[1]["seconds"]) >= 150 - 1, True)   # B: limit measured from load
        self.assertEqual(float(rows[2]["seconds"]) >= 170, True)
        resets_after = self.fake.resets
        self.assertGreaterEqual(resets_after, 3)
        self.assertConfigRestored()
        stall = open(self.out + ".stall").read().splitlines()        # decode.py's format, B and D
        self.assertEqual(len(stall), 2)
        self.assertIn(" stack:", stall[0])

    def test_hang_dump_is_short_reads_only(self):
        sim = Sim(self.fake, self.prg, loads=["ok"], boots=["hang"], labels=self.labels)
        self.run_session(sim, plan="2 B 1\n")
        # the only reads of length >= 256 are the screen (1000); the dump reads <= 64 bytes
        for t, a, ln in sim.big_reads:
            self.assertEqual((a, ln), (0x0400, 1000))

    def test_boot_timeout_without_st_bit_is_other(self):
        sim = Sim(self.fake, self.prg, boots=["ok"], labels=self.labels)
        sim.boots = ["hang"]
        orig = sim.boot

        def boot(dt):
            orig(dt)
            self.fake.ram[0x90] = 0
        sim.boot = boot
        self.run_session(sim, plan="2 D 1\n")
        r = [r for r in self.rows() if r["outcome"] != "NOTE"][0]
        self.assertEqual(r["outcome"], "other")
        self.assertIn("no ST timeout bit", r["detail"])


class Stopping(Base):
    def test_arm_with_five_failures_is_skipped(self):
        sim = Sim(self.fake, self.prg, loads=["error"] * 5, boots=["ok"] * 8, labels=self.labels)
        self.run_session(sim, plan="2 KD 8\n")
        rows = self.rows()
        k = [r for r in rows if r["arm"] == "K"]
        d = [r for r in rows if r["arm"] == "D"]
        self.assertEqual([r["outcome"] for r in k],
                         ["LOAD ERROR"] * 5 + ["NOTE"] + ["skipped"] * 3)
        self.assertEqual([r["outcome"] for r in d], ["pass"] * 8)
        self.assertTrue(any("reached 5 failures" in r["note"] and r["outcome"] == "NOTE" for r in k))
        self.assertEqual(self.status, 0)
        self.assertEqual(len(sim.boots), 0)

    def test_three_wedges_stop_the_block(self):
        sim = Sim(self.fake, self.prg, loads=["hang"] * 5, labels=self.labels)
        self.run_session(sim, ask=lambda t: "y" if t.startswith("Is the drive LED") else "",
                         plan="1 K 5\n2 C 1\n")
        rows = self.rows()
        self.assertEqual([r["outcome"] for r in rows if r["block"] == "1" and r["arm"] == "K"].count(
            "LOADING hang"), 3)
        self.assertTrue(any("3 wedges in a row" in r["note"] for r in rows))
        self.assertEqual(len(sim.loads), 1)      # K trials 4 and 5 never ran; block 2's C did

    def test_stop_at_a_prompt_ends_everything(self):
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, boots=["ok"] * 3, labels=self.labels)
        self.run_session(sim, ask=lambda t: "stop" if "Breadbin disk" in t else "", plan="1 C 1\n2 KBD 1\n3 C 1\n")
        self.assertEqual(self.status, 3)
        rows = self.rows()
        self.assertEqual([r["outcome"] for r in rows], ["pass", "STOP"])
        self.assertIn("owner typed stop", rows[-1]["note"])
        self.assertConfigRestored()

    def test_ctrl_c_during_a_trial_is_logged_and_stops(self):
        sim = Sim(self.fake, self.prg, loads=["ok"], labels=self.labels)
        real_sleep = sim.sleep
        state = {"n": 0}

        def sleep(s):
            state["n"] += 1
            if state["n"] == 4:
                raise KeyboardInterrupt
            real_sleep(s)
        sim.sleep = sleep
        self.run_session(sim, plan="1 C 3\n")
        self.assertEqual(self.status, 3)
        outs = [r["outcome"] for r in self.rows()]
        self.assertEqual(outs[-1], "STOP")
        self.assertEqual(len(outs), 2)
        self.assertConfigRestored()


class Config(Base):
    def test_config_restored_after_an_exception(self):
        sim = Sim(self.fake, self.prg, loads=["ok"], labels=self.labels)

        def boom(*a, **k):
            raise RuntimeError("harness bug")
        # a failure that escapes the session loop: the results file refuses a row
        orig = session.Session.run
        session.Session.run = boom
        try:
            with self.assertRaises(RuntimeError):
                self.run_session(sim, plan="1 C 1\n")
        finally:
            session.Session.run = orig
        self.assertConfigRestored()
        self.assertIn(("SoftIEC Drive Settings", "IEC Drive", "Disabled"), self.fake.config_puts)

    def test_config_restored_when_a_put_fails_midway(self):
        sim = Sim(self.fake, self.prg, loads=["ok"], labels=self.labels)
        orig = session.ConfigGuard.put
        n = {"i": 0}

        def flaky(self_, c, i, v):
            n["i"] += 1
            if n["i"] == 3:
                raise RuntimeError("PUT failed")
            return orig(self_, c, i, v)
        session.ConfigGuard.put = flaky
        try:
            with self.assertRaises(RuntimeError):
                self.run_session(sim, plan="1 C 1\n")
        finally:
            session.ConfigGuard.put = orig
        self.assertConfigRestored()

    def test_extra_set_is_restored_to_its_prior_value(self):
        self.fake.configs[("Turbo", "Mode")] = "Off"
        sim = Sim(self.fake, self.prg, loads=["ok"], labels=self.labels)
        self.run_session(sim, plan="1 C 1\n", extra=["--set", "Turbo/Mode=On"])
        self.assertIn(("Turbo", "Mode", "On"), self.fake.config_puts)
        self.assertEqual(self.fake.configs[("Turbo", "Mode")], "Off")

    def test_wrong_disk_refused(self):
        open(self.p("b.prg"), "ab").write(b"x")
        sim = Sim(self.fake, self.prg)
        with self.assertRaises(SystemExit):
            self.run_session(sim, plan="1 C 1\n")
        self.assertEqual(self.fake.config_puts, [])      # nothing touched before the check

    def test_dry_run_touches_nothing(self):
        self.plan("1 C 2\n2 KBD 2\n")
        lines = []
        st = session.main([self.p("plan.txt"), "--image", self.p("b.prg"), "--d64", self.p("b.d64"),
                           "--out", self.out, "--disk-id", "T1", "--control-file", "X", "--dry-run"],
                          out=lines.append)
        self.assertEqual(st, 0)
        self.assertEqual(self.fake.requests, [])
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(sum(l.startswith("block") for l in lines), 8)


if __name__ == "__main__":
    unittest.main()
