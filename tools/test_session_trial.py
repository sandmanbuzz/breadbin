"""Host tests for experiments/iec-stall/session.py (the hardware trial runner), against the fake
Ultimate only. A small scripted C64 stand-in turns the runner's keystrokes and PRG runs into
screen text on a virtual clock, so a 90-minute plan runs in a second and no real device is touched.
"""
import os
import re
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
        self.loading = False
        self.reads = []           # (virtual time, address, length) of every readmem
        self.big_reads = []       # (virtual time, address, length) of reads >= 256 bytes
        self.pending = []         # (time, fn)
        self.kbuf = ""
        self.run_after = False    # RUN queued in the key buffer, read by BASIC after READY.
        self.marks = []           # (time, "start"|"terminal"): a transfer begins / its end is on screen
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
        if len(self.fake.runs) != self.seen_runs:
            self.step()                # run_prg resets synchronously: a read right after it sees the new boot
        self.reads.append((self.t, a, ln))
        if ln >= 256:
            self.big_reads.append((self.t, a, ln))

    def sync_screen(self):
        self.fake.ram[0xD6] = min(len(self.lines), 24)        # the cursor row
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
                self.marks.append((self.t, "start"))
                self.boot(40)
        if f.ram[0xC6]:
            n = f.ram[0xC6]
            text = bytes(f.ram[0x0277:0x0277 + n]).decode("latin-1").translate(
                {0xCF: "O", 0xD5: "U"}).lower()          # shifted O, U: the l-O and r-U abbreviations
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
        if cmd.startswith('lo"'):
            cmd = "load" + cmd[2:]
        if cmd == "ru":
            cmd = "run"
        self.events.append((self.t, cmd))
        if cmd == "run" and (self.lines[-1:] != ["ready."] or self.loading):
            self.run_after = True              # typed ahead: BASIC reads it after READY.
            return
        self.lines.append(cmd)
        if cmd.startswith("load"):
            self.marks.append((self.t, "start"))
            self.loading = True
            how = self.loads.pop(0)
            self.lines += ["searching for " + cmd.split('"')[1], "loading"]
            ctrl = cmd.endswith(",8")
            data = CTRL if ctrl else self.prg[2:]
            addr = 0x0801 if ctrl else (self.prg[0] | self.prg[1] << 8)
            if how == "hang":
                return
            if how == "error":
                def err():
                    self.lines.extend(["?load error", "ready."])
                    self.loading, self.run_after = False, False
                    self.marks.append((self.t, "terminal"))
                self.at(5, err)
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
                self.loading = False
                self.marks.append((self.t, "terminal"))
                if self.run_after:
                    self.run_after = False
                    self.command("run")
            self.at(8, done)
        elif cmd == "run":
            self.boot(25)

    def boot(self, dt):
        how = self.boots.pop(0)
        self.lines = []                       # Breadbin clears the screen
        if how == "ok":
            def login():
                self.marks.append((self.t, "terminal"))
                for n, a in self.labels.items():
                    self.fake.ram[a] = {"io_nread": 200, "io_nretry": 3, "io_nfail": 0,
                                        "io_neoi": 9}.get(n, 0x55)
                self.lines.append("login:")
            self.at(dt, login)
        elif how == "panic":
            def panic():
                self.lines.append("kernel panic: root mount")
                self.marks.append((self.t, "terminal"))
            self.at(10, panic)
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
            "al 00C00C .io_neoi\nal 00C010 .io_ltrk\nal 00C011 .io_lsct\nal 00C012 .io_lidx\n"
            "al 00C013 .io_ltry\nal 00C014 .io_lst\nal 00C015 .io_lwn\nal 00C016 .zz\n"
            "al 00C200 .io_last\n"
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
        self.assertRegex(r["io_last"], r"^ltrk=..;lsct=..;lidx=..;ltry=..;lst=..;lwn=..$")  # not the code label io_last
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

    def dma_run(self, mode):
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, boots=["ok", "ok"], labels=self.labels)
        self.run_session(sim, plan="1 C 1\n2 KBD 1\n", extra=["--poll-mode", mode])
        self.assertEqual(self.status, 0)
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual([r["outcome"] for r in rows], ["pass"] * 4)
        for r in rows:
            self.assertIn("poll=" + mode, r["detail"])
        self.assertTrue(any(f"poll mode {mode}" in c for c in self.comments()))
        return sim

    def windows(self, sim):
        """(start, terminal) per transfer, from the stand-in C64's own marks."""
        out, start = [], None
        for t, m in sim.marks:
            if m == "start" and start is None:
                start = t
            elif m == "terminal" and start is not None:
                out.append((start, t))
                start = None
        return out

    def test_poll_mode_none_reads_nothing_during_a_trial(self):
        sim = self.dma_run("none")
        w = self.windows(sim)
        self.assertEqual(len(w), 4)               # C, K, B (load + RUN count as one start), D
        limits = [120, 120, 150, 170]
        for (start, term), lim in zip(w, limits):
            # not one readmem, of any length, from the start until the limit (one second of slack for
            # the stand-in's half-second steps); the final screen read is at the limit
            inside = [r for r in sim.reads if start <= r[0] < start + lim - 1]
            self.assertEqual(inside, [], f"read inside a trial: {inside}")
            at_limit = [r for r in sim.reads if start + lim - 1 <= r[0] <= start + lim + 1
                        and r[2] == 1000]
            self.assertEqual(len(at_limit), 1)

    def test_poll_mode_byte_reads_one_byte_before_the_terminal_state(self):
        sim = self.dma_run("byte")
        w = self.windows(sim)
        self.assertEqual(len(w), 4)
        polls = 0
        for start, term in w:
            inside = [r for r in sim.reads if start <= r[0] < term]
            self.assertTrue(all(r[2] == 1 for r in inside), f"long read before terminal: {inside}")
            polls += len(inside)
            # at most one byte read per 2 s
            ts = [r[0] for r in inside]
            self.assertTrue(all(b - a >= 2 - 1e-9 for a, b in zip(ts, ts[1:])))
            # and the full screen read comes only after the terminal state is on screen
            after = [r for r in sim.reads if r[0] >= term and r[2] == 1000]
            self.assertTrue(after)
        self.assertGreater(polls, 3)

    def test_poll_mode_byte_hang_reads_the_screen_only_at_the_limit(self):
        sim = Sim(self.fake, self.prg, loads=["hang"], labels=self.labels)
        self.run_session(sim, plan="2 K 1\n", extra=["--poll-mode", "byte"])
        start = [t for t, m in sim.marks if m == "start"][0]
        big = [r for r in sim.reads if r[2] >= 256 and r[1] == 0x0400]
        self.assertEqual(len(big), 2)               # idle READY. check, then the limit
        self.assertGreaterEqual(big[1][0], start + 120 - 1)
        row = [r for r in self.rows() if r["outcome"] != "NOTE"][0]
        self.assertEqual(row["outcome"], "LOADING hang")

    def test_missing_labels_leave_counters_blank(self):
        os.remove(self.p("b.lbl"))
        sim = Sim(self.fake, self.prg, loads=["ok"], boots=["ok", "ok"])
        self.run_session(sim, plan="2 BD 1\n", extra=[])
        rows = [r for r in self.rows() if r["outcome"] == "pass"]
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertEqual((r["io_nread"], r["io_nretry"], r["io_nfail"], r["io_neoi"], r["io_last"]),
                             ("", "", "", "", "iostat absent"))

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


class Session1(Base):
    """Session-1 additions: uptime in stall dumps, the 2b poll arm, a DMA kernel apart from the disk's."""

    def test_stall_dump_has_uptime_in_jiffies(self):
        self.fake.ram[0x4A:0x4D] = (0x2710).to_bytes(3, "little")      # ticks = 10000
        self.fake.ram[0xA0:0xA3] = bytes([0x00, 0x01, 0x02])           # stock jiffy clock, $A0 high
        sim = Sim(self.fake, self.prg, loads=["hang"], boots=["hang"], labels=self.labels)
        self.run_session(sim, plan="2 KD 1\n")
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual([r["outcome"] for r in rows], ["LOADING hang", "stall"])
        for r in rows:
            self.assertIn("ticks_jiffies=10000", r["dump"])
            self.assertIn("kjiffy_jiffies=258", r["dump"])
        for t, a, ln in sim.reads:
            if a in (0x4A, 0xA0):
                self.assertEqual(ln, 3)
                self.assertGreaterEqual(t, 120)              # only after the trial's limit

    def test_block_word_and_arm_p_parse(self):
        self.assertEqual(session.parse_plan("2b DP 8\ndry K 1"), [("2b", "DP", 8), ("dry", "K", 1)])

    def test_arm_p_polls_a_screen_every_2s_and_arm_d_does_not(self):
        sim = Sim(self.fake, self.prg, boots=["ok"] * 4, labels=self.labels)
        self.run_session(sim, plan="2b DP 2\n")
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual([(r["block"], r["arm"], r["outcome"]) for r in rows],
                         [("2b", "DP"[i % 2], "pass") for i in range(4)])
        self.assertIn("poll=1000b/2s", rows[1]["detail"])
        self.assertIn("poll=none", rows[0]["detail"])
        self.assertEqual(rows[1]["io_nread"], "200")
        w = self.windows_of(sim)
        self.assertEqual(len(w), 4)
        for i, (a, b) in enumerate(w):
            n = [t for t, ad, ln in sim.big_reads if a <= t < b]
            if i % 2 == 0:
                self.assertEqual(n, [], "arm D read during the transfer")
            else:
                self.assertGreaterEqual(len(n), 10)
                self.assertGreaterEqual(n[0] - a, 3 - 0.6)           # the stand-in notices a run in 0.5 s steps
                self.assertTrue(all(y - x <= 2.5 for x, y in zip(n, n[1:])))

    @staticmethod
    def windows_of(sim):
        out, start = [], None
        for t, m in sim.marks:
            if m == "start" and start is None:
                start = t
            elif m == "terminal" and start is not None:
                out.append((start, t))
                start = None
        return out

    def test_arm_p_four_failures_end_block_2b(self):
        sim = Sim(self.fake, self.prg, boots=["ok", "hang"] * 4 + ["ok"] * 4, labels=self.labels)
        self.run_session(sim, plan="2b DP 8\n")
        rows = self.rows()
        p = [r for r in rows if r["arm"] == "P" and r["outcome"] == "stall"]
        self.assertEqual(len(p), 4)
        self.assertTrue(any("arm P reached 4 failures" in r["note"] for r in rows))
        self.assertEqual(len([r for r in rows if r["outcome"] == "pass"]), 4)   # 4 D passes, then nothing
        self.assertEqual(len(sim.boots), 4)                                       # D trial 5 never ran

    def test_dma_kernel_apart_from_the_disk_kernel(self):
        dma = (0x0801).to_bytes(2, "little") + bytes(range(1, 200))
        open(self.p("dma.prg"), "wb").write(dma)
        open(self.p("dma.lbl"), "w").write(
            "al 00C000 .io_nread\nal 00C004 .io_nretry\nal 00C008 .io_nfail\nal 00C00C .io_neoi\n")
        open(self.p("b.lbl"), "w").write("al 00004A .ticks\nal 00004D .p1\n")      # disk kernel: no IOSTAT
        sim = Sim(self.fake, self.prg, loads=["ok"], boots=["ok", "ok"],
                  labels=session.read_labels(self.p("dma.lbl")))
        self.run_session(sim, plan="2 BD 1\n", extra=["--dma-image", self.p("dma.prg")])
        self.assertEqual(self.status, 0)
        b, d = [r for r in self.rows() if r["outcome"] == "pass"]
        self.assertEqual((b["io_nread"], b["io_last"]), ("", "iostat absent"))
        self.assertEqual(d["io_nread"], "200")
        self.assertNotEqual(b["image_sha"], d["image_sha"])
        self.assertEqual(self.fake.runs[-1]["size"], len(dma))     # D uploaded the DMA kernel, not the disk's
        self.assertTrue(any("ticks label: $004a" in c for c in self.comments()))

    def test_the_session1_plan_file_runs_end_to_end(self):
        plan = os.path.join(HERE, "..", "experiments", "iec-stall", "plans", "session1.plan")
        sim = Sim(self.fake, self.prg, loads=["ok"] * 38, boots=["ok"] * 36, labels=self.labels)
        self.plan(open(plan).read())
        self.run_session(sim)
        self.assertEqual(self.status, 0)
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual(len(rows), 64)
        self.assertEqual({r["outcome"] for r in rows}, {"pass"})
        self.assertEqual([r["block"] for r in rows],
                         ["1"] * 12 + ["2"] * 30 + ["2b"] * 16 + ["3"] * 6)
        self.assertEqual("".join(r["arm"] for r in rows[12:42]), "KBD" * 10)
        self.assertEqual("".join(r["arm"] for r in rows[42:58]), "DP" * 8)
        self.assertEqual(len([t for t in self.asked if t.startswith("HAND")]), 3)
        self.assertConfigRestored()


class Session2(Base):
    """Session-2 poll arms Q, J, O (table POLL_ARMS) against the stand-in."""

    windows_of = staticmethod(Session1.windows_of)

    def run_arms(self, plan, **kw):
        sim = Sim(self.fake, self.prg, labels=self.labels, **kw)
        self.run_session(sim, plan=plan)
        return sim, [r for r in self.rows() if r["outcome"] != "NOTE"]

    def reads_in(self, sim, a, b, addr=None, ln=None):
        return [t for t, ad, n in sim.reads
                if a <= t < b and (addr is None or ad == addr) and (ln is None or n == ln)]

    def test_plan_letters_and_table(self):
        self.assertEqual(session.parse_plan("1 KJ 8\n2 dq 1\n3 DO 2"),
                         [(1, "KJ", 8), (2, "DQ", 1), (3, "DO", 2)])
        self.assertEqual([session.poll_label(a) for a in "PQJO"],
                         ["1000b/2s", "1000b/0.5s", "1000b/0.5s", "1b/0.1s"])
        self.assertEqual([session.LIMITS[a] for a in "PQJO"], [170, 170, 120, 170])
        self.assertEqual([session.ARM_FAIL_LIMITS[a] for a in "PQJO"], [4, 4, 4, 4])
        self.assertEqual([session.arm_kernel(a) for a in "PQJO"], ["dma", "dma", "disk", "dma"])

    def test_arm_q_reads_a_screen_every_half_second(self):
        sim, rows = self.run_arms("2 DQ 2\n", boots=["ok"] * 4)
        self.assertEqual([(r["arm"], r["outcome"]) for r in rows], [("D", "pass"), ("Q", "pass")] * 2)
        self.assertIn("poll=1000b/0.5s", rows[1]["detail"])
        self.assertEqual(rows[1]["io_nread"], "200")
        self.assertIn("ltrk=55;", rows[1]["io_last"])
        w = self.windows_of(sim)
        for i, (a, b) in enumerate(w):
            n = [t for t, ad, ln in sim.big_reads if a <= t < b]
            if i % 2 == 0:
                self.assertEqual(n, [])
            else:                      # passes early at the login (40 s), ~2 reads per second until then
                self.assertGreaterEqual(len(n), 70)
                self.assertLessEqual(n[0] - a, 0.6)
                self.assertTrue(all(abs((y - x) - 0.5) < 0.01 for x, y in zip(n[1:], n[2:])), n[:6])

    def test_arm_q_ignores_a_stale_login_read_at_the_start(self):
        class Stale(Sim):
            def on_read(self, a, ln):          # the reset is NOT noticed by a read: old screen shows
                self.reads.append((self.t, a, ln))
                if ln >= 256:
                    self.big_reads.append((self.t, a, ln))
        sim = Stale(self.fake, self.prg, boots=["hang"], labels=self.labels)
        sim.lines = ["login:"]
        sim.sync_screen()
        self.run_session(sim, plan="2 Q 1\n")
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual(rows[0]["outcome"], "stall")
        self.assertGreaterEqual(float(rows[0]["seconds"]), 169)
        self.assertEqual(sim.big_reads[0][0], 0.0)           # it did read at t=0

    def test_arm_o_reads_one_byte_every_tenth_of_a_second(self):
        sim, rows = self.run_arms("4 DO 1\n", boots=["ok"] * 2)
        self.assertEqual([(r["arm"], r["outcome"]) for r in rows], [("D", "pass"), ("O", "pass")])
        self.assertIn("poll=1b/0.1s", rows[1]["detail"])
        self.assertEqual(rows[1]["io_nread"], "200")
        w = self.windows_of(sim)
        starts = [t for t, m in sim.marks if m == "start"]
        d0, o0 = starts[0], starts[1]
        self.assertEqual(self.reads_in(sim, d0, o0 - 1, 0xD6), [])
        n = self.reads_in(sim, o0, o0 + 169, 0xD6, 1)
        self.assertGreaterEqual(len(n), 1600)            # 170 s at 10 per second; no early exit
        self.assertTrue(all(abs((y - x) - 0.1) < 0.01 for x, y in zip(n, n[1:])))
        self.assertEqual(self.reads_in(sim, o0 + 1, o0 + 169, None, 1000), [])   # no screen reads before the limit
        self.assertGreaterEqual(rows[1]["seconds"] and float(rows[1]["seconds"]), 169)
        self.assertEqual(len(w), 2)

    def test_arm_o_stall_is_a_stall_with_dump(self):
        sim, rows = self.run_arms("4 O 1\n", boots=["hang"])
        self.assertEqual(rows[0]["outcome"], "stall")
        self.assertIn("st=02", rows[0]["dump"])
        self.assertIn("poll=1b/0.1s", rows[0]["detail"])

    def test_arm_j_pass_polls_the_screen_from_the_typed_command(self):
        sim, rows = self.run_arms("1 KJ 2\n", loads=["ok"] * 4)
        self.assertEqual([(r["arm"], r["outcome"]) for r in rows], [("K", "pass"), ("J", "pass")] * 2)
        self.assertIn("bytes identical", rows[1]["detail"])
        self.assertIn("poll=1000b/0.5s", rows[1]["detail"])
        self.assertIn("poll=none", rows[0]["detail"])
        starts = [t for t, m in sim.marks if m == "start"]
        for i, (a, b) in enumerate(self.windows_of(sim)):
            n = [t for t, ad, ln in sim.big_reads if a <= t < b]
            if i % 2 == 0:
                self.assertEqual(n, [], "arm K read the screen during the load")
            else:
                self.assertGreaterEqual(len(n), 10)       # the 8 s load, read every 0.5 s
                self.assertTrue(all(abs((y - x) - 0.5) < 0.01 for x, y in zip(n, n[1:])))
        self.assertEqual(len(starts), 4)

    def test_arm_j_failure_outcomes_are_distinguished(self):
        sim, rows = self.run_arms("1 J 4\n", loads=["hang", "error", "corrupt", "ok"])
        self.assertEqual([r["outcome"] for r in rows], ["LOADING hang", "LOAD ERROR", "mismatch", "pass"])
        self.assertIn("?load", rows[1]["detail"])
        self.assertIn("1 bytes differ", rows[2]["detail"])
        self.assertTrue(rows[0]["dump"])
        for r in rows:
            self.assertIn("poll=1000b/0.5s", r["detail"])
        self.assertGreaterEqual(float(rows[0]["seconds"]), 119)     # the hang runs to the limit

    def test_arm_j_four_failures_stop_the_arm_not_the_block(self):
        sim, rows = self.run_arms("1 KJ 6\n", loads=["ok", "error"] * 4 + ["ok"] * 4)
        j = [r for r in rows if r["arm"] == "J" and r["outcome"] == "LOAD ERROR"]
        self.assertEqual(len(j), 4)
        self.assertEqual(len([r for r in rows if r["arm"] == "K" and r["outcome"] == "pass"]), 6)    # K carried on
        self.assertEqual(len([r for r in rows if r["arm"] == "J" and r["outcome"] != "skipped"]), 4)

    def test_the_session2_plan_file_runs_end_to_end(self):
        plan = os.path.join(HERE, "..", "experiments", "iec-stall", "plans", "session2.plan")
        sim = Sim(self.fake, self.prg, loads=["ok"] * 16, boots=["ok"] * 44, labels=self.labels)
        self.plan(open(plan).read())
        self.run_session(sim)
        self.assertEqual(self.status, 0)
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual(len(rows), 60)
        self.assertEqual({r["outcome"] for r in rows}, {"pass"})
        self.assertEqual("".join(r["arm"] for r in rows), "KJ" * 8 + "DQ" * 8 + "DP" * 6 + "DO" * 8)
        self.assertEqual(len([t for t in self.asked if t.startswith("HAND")]), 1)
        self.assertConfigRestored()


class Session3(Base):
    """Session-3 arms Z, S, T, G, H (POLL_ARMS / VARIANT_ARMS) against the stand-in."""

    windows_of = staticmethod(Session1.windows_of)
    run_arms = Session2.run_arms
    reads_in = Session2.reads_in
    KERNAL = ("C64 and Cartridge Settings", "Kernal ROM")

    def setUp(self):
        super().setUp()
        # the reply OEM firmware 1.1.0 gives: "presets", the stock entry is the empty one
        self.fake.config_presets[self.KERNAL] = ["", "JiffyDOS-C64.bin", "JiffyDOS-kernal.bin"]

    def idle_sim(self, bus, **kw):
        """A Sim whose $DD00 follows bus(t); on a hang boot the stall value stays."""
        sim = Sim(self.fake, self.prg, labels=self.labels, **kw)
        orig = sim.on_read

        def on_read(a, ln):
            if a == 0xDD00:
                self.fake.ram[0xDD00] = bus(sim.t)
            orig(a, ln)
        self.fake.on_readmem = on_read
        return sim

    def test_table_and_plan_files(self):
        self.assertEqual([session.poll_label(a) for a in "ZSGHT"],
                         ["1000b/0.5s+pause", "1000b/0.5s", "1000b/0.5s+gate3x1b", "1000b/0.5s+gate3x1b", None])
        self.assertEqual([session.LIMITS[a] for a in "ZSGHT"], [170, 120, 170, 120, 120])
        self.assertEqual([session.arm_kernel(a) for a in "ZSGHT"], ["dma", "disk", "dma", "disk", "disk"])
        self.assertEqual([session.arm_stock(a) for a in "ZSGHTKD"], [False, True, False, False, True, False, False])
        self.assertEqual([session.ARM_FAIL_LIMITS[a] for a in "ZSGH"], [4, 4, 4, 4])
        plans = os.path.join(HERE, "..", "experiments", "iec-stall", "plans")
        whole = session.expand(session.parse_plan(open(os.path.join(plans, "session3.plan")).read()))
        self.assertEqual("".join(a for _, _, a in whole), "DZ" * 8 + "TS" * 8 + "DG" * 8 + "KH" * 8)
        parts = []
        for i in range(1, 5):
            parts += [a for _, _, a in session.expand(session.parse_plan(
                open(os.path.join(plans, f"session3-b{i}.plan")).read()))]
        self.assertEqual(parts, [a for _, _, a in whole])

    def test_arm_z_pauses_around_each_screen_read_and_always_resumes(self):
        sim, rows = self.run_arms("1 DZ 1\n", boots=["ok"] * 2)
        self.assertEqual([(r["arm"], r["outcome"]) for r in rows], [("D", "pass"), ("Z", "pass")])
        self.assertIn("poll=1000b/0.5s+pause", rows[1]["detail"])
        seq = [p.split(":")[-1] for m, p in self.fake.requests if p.startswith("/v1/machine:") and
               p.split(":")[-1] in ("pause", "resume", "readmem")]
        z = seq[seq.index("readmem") - 1:]            # from Z's first screen read on
        self.assertFalse(self.fake.paused)
        self.assertGreaterEqual(len([k for k in range(1, len(z) - 1) if z[k - 1:k + 2] == ["pause", "readmem", "resume"]]),
                                70)

    def test_arm_z_resumes_when_the_screen_read_fails(self):
        sim = Sim(self.fake, self.prg, boots=["ok"], labels=self.labels)
        rig = session.Rig(self.u, sim, self.prg, self.labels, "X")
        self.fake.on_readmem = lambda a, ln: (_ for _ in ()).throw(RuntimeError("read failed"))
        with self.assertRaises(Exception):
            rig.poll_screen(session.POLL_ARMS["Z"])
        self.assertFalse(self.fake.paused)

    def test_a_paused_machine_is_resumed_by_the_restore_trap(self):
        sim = Sim(self.fake, self.prg, boots=["ok"], labels=self.labels)
        orig = session.Session.run

        def boom(self_):
            self.u.pause()
            raise RuntimeError("harness bug while paused")
        session.Session.run = boom
        try:
            with self.assertRaises(RuntimeError):
                self.run_session(sim, plan="1 Z 1\n")
        finally:
            session.Session.run = orig
        self.assertFalse(self.fake.paused)
        self.assertConfigRestored()

    def test_arm_g_gate_reads_three_dd00_bytes_and_polls_only_when_idle(self):
        # bus busy (DATA out driven, $DD00 = $C5... mask $F8 != $C0 -> 0xCD has bit 3 set) before 10 s, idle after
        sim = None

        def bus(t):
            return 0xCD if sim.marks and t - sim.marks[-1][0] < 10 else 0xC7
        sim = self.idle_sim(bus, boots=["ok"] * 2)
        self.run_session(sim, plan="3 DG 1\n")
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual([(r["arm"], r["outcome"]) for r in rows], [("D", "pass"), ("G", "pass")])
        d = rows[1]["detail"]
        self.assertIn("poll=1000b/0.5s+gate3x1b", d)
        m = re.search(r"screen_reads=(\d+) skipped=(\d+) dd00=(\S+)", d)
        self.assertTrue(m, d)
        done, skipped = int(m.group(1)), int(m.group(2))
        self.assertGreaterEqual(skipped, 12)
        self.assertGreaterEqual(done, 40)
        hist = dict(x.split(":") for x in m.group(3).split(","))
        self.assertEqual(set(hist), {"cd", "c7"})
        self.assertEqual(sum(map(int, hist.values())), 3 * (done + skipped))   # every read is in the histogram
        self.assertNotIn("screen_reads", rows[0]["detail"])                    # D has no gate
        gg = [(t, a, n) for t, a, n in sim.reads if a == 0xDD00]
        self.assertTrue(all(n == 1 for _, _, n in gg))
        # 0.1 s apart inside a poll; no screen read while the bus is busy
        for (t0, _, _), (t1, _, _) in list(zip(gg[0::3], gg[1::3]))[:20]:
            self.assertAlmostEqual(t1 - t0, 0.1, places=6)
        g0 = [t for t, m in sim.marks if m == "start"][1]
        self.assertEqual([t for t, a, n in sim.big_reads if g0 < t < g0 + 9.5], [])    # none while the bus is busy

    def test_gate_demands_all_three_reads_idle(self):
        calls = {"n": 0}

        def bus(t):
            calls["n"] += 1
            return 0xCD if calls["n"] % 3 == 0 else 0xC7        # the third read of each poll shows busy
        sim = self.idle_sim(bus, boots=["hang"])
        self.run_session(sim, plan="3 G 1\n")
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual(rows[0]["outcome"], "stall")
        self.assertIn("screen_reads=0 skipped=", rows[0]["detail"])
        self.assertEqual([x for x in sim.big_reads if x[0] < 169], [])

    def test_arm_h_is_the_gated_kernal_load(self):
        sim = self.idle_sim(lambda t: 0xC7, loads=["ok"] * 2)
        self.run_session(sim, plan="4 KH 1\n")
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual([(r["arm"], r["outcome"]) for r in rows], [("K", "pass"), ("H", "pass")])
        self.assertIn("bytes identical", rows[1]["detail"])
        self.assertIn("skipped=0", rows[1]["detail"])
        self.assertIn("dd00=c7:", rows[1]["detail"])

    def test_stock_kernal_arms_select_and_restore_the_kernal_rom(self):
        sim = Sim(self.fake, self.prg, loads=["ok"] * 5, boots=["ok"], labels=self.labels)
        self.run_session(sim, plan="2 TS 2\n3 D 1\n1 K 1\n")
        rows = [r for r in self.rows() if r["outcome"] != "NOTE"]
        self.assertEqual(self.status, 0)
        self.assertEqual("".join(r["arm"] for r in rows), "TSTSDK")
        self.assertEqual({r["outcome"] for r in rows}, {"pass"})
        puts = [v for c, i, v in self.fake.config_puts if (c, i) == self.KERNAL]
        self.assertEqual(puts[:2], ["", "JiffyDOS-C64.bin"])      # once in (the EMPTY value is sent), once back for D
        self.assertEqual(self.fake.configs[self.KERNAL], "JiffyDOS-C64.bin")
        self.assertTrue(any("stock Kernal ROM value discovered: ''" in c for c in self.comments()))
        self.assertConfigRestored()

    def test_kernal_restored_by_trap_after_a_stock_arm_breaks(self):
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, labels=self.labels)
        orig = session.Rig.trial
        n = {"i": 0}

        def trial(self_, arm):
            n["i"] += 1
            r = orig(self_, arm)
            if n["i"] == 2:
                raise KeyboardInterrupt
            return r
        session.Rig.trial = trial
        try:
            self.run_session(sim, plan="2 TS 3\n")
        finally:
            session.Rig.trial = orig
        self.assertEqual(self.status, 3)
        self.assertEqual(self.fake.configs[self.KERNAL], "JiffyDOS-C64.bin")
        self.assertConfigRestored()

    def test_stock_arm_refuses_when_no_stock_value_is_listed(self):
        for vals in (["JiffyDOS-C64.bin", "other.bin"], ["Original", "Stock ROM"], None):
            if vals is None:
                del self.fake.config_presets[self.KERNAL]
            else:
                self.fake.config_presets[self.KERNAL] = vals
            sim = Sim(self.fake, self.prg, loads=["ok"] * 2, labels=self.labels)
            with self.assertRaises(SystemExit) as cm:
                self.run_session(sim, plan="2 TS 1\n")
            self.assertIn("refuse to run", str(cm.exception))
            self.assertEqual(self.fake.config_puts, [], vals)               # nothing was changed

    def test_reads_the_oem_reply_shape(self):
        # the reply OEM firmware 1.1.0 gave on 2026-11-10 (read-only GET on the real machine)
        reply = {"C64 and Cartridge Settings": {"Kernal ROM": {
            "current": "JiffyDOS-C64.bin", "presets": ["", "JiffyDOS-C64.bin", "JiffyDOS-kernal.bin"],
            "default": ""}}, "errors": []}
        allowed = session.config_allowed(reply, *session.KERNAL_ITEM)
        self.assertEqual(allowed, ["", "JiffyDOS-C64.bin", "JiffyDOS-kernal.bin"])
        self.assertEqual(session.pick_stock_kernal(allowed), ("", "empty entry"))

    def test_empty_entry_is_the_stock_value_only_when_listed(self):
        self.assertEqual(session.pick_stock_kernal(["JiffyDOS-C64.bin", ""])[0], "")
        self.assertIsNone(session.pick_stock_kernal(["JiffyDOS-C64.bin"])[0])
        self.assertIsNone(session.pick_stock_kernal([])[0])
        self.assertEqual(session.pick_stock_kernal(["JiffyDOS Original.bin", "Original"])[0], "Original")

    def test_dry_run_marks_stock_arms(self):
        self.plan("2 TS 1\n")
        lines = []
        session.main([self.p("plan.txt"), "--image", self.p("b.prg"), "--d64", self.p("b.d64"), "--out", self.out,
                      "--disk-id", "T1", "--control-file", "X", "--dry-run"], out=lines.append)
        self.assertEqual(sum("stock KERNAL" in l for l in lines), 2)
        self.assertEqual(self.fake.requests, [])

    # ---- hater review of the session-3 harness (blocked 4055947, 648a952)
    def hook_put(self, fn):
        orig = session.ConfigGuard.put
        session.ConfigGuard.put = fn(orig)
        self.addCleanup(setattr, session.ConfigGuard, "put", orig)

    def during_restore(self, make_fault):
        """Run `2 T 1` with make_fault() called after every PUT of the restore."""
        orig_restore = session.ConfigGuard.restore
        state = {"restoring": False}

        def restore(g):
            state["restoring"] = True
            return orig_restore(g)

        def hook(orig):
            def put(g, c, i, v):
                r = orig(g, c, i, v)
                if state["restoring"]:         # the interrupt lands right after each PUT of the restore
                    make_fault()
                return r
            return put
        session.ConfigGuard.restore = restore
        self.addCleanup(setattr, session.ConfigGuard, "restore", orig_restore)
        self.hook_put(hook)
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, labels=self.labels)
        self.run_session(sim, plan="2 T 1\n")

    def test_a_second_ctrl_c_in_restore_cannot_leave_the_stock_kernal(self):
        def ki():
            raise KeyboardInterrupt
        self.during_restore(ki)
        self.assertEqual(self.fake.configs[self.KERNAL], "JiffyDOS-C64.bin")
        self.assertConfigRestored()
        self.assertEqual(self.status, 0)

    def test_real_sigint_sigterm_sighup_in_restore_are_blocked(self):
        import signal
        for sg in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            self.fake.configs[self.KERNAL] = "JiffyDOS-C64.bin"
            self.fake.config_puts.clear()
            self.during_restore(lambda: os.kill(os.getpid(), sg))
            self.assertEqual(self.fake.configs[self.KERNAL], "JiffyDOS-C64.bin", sg)
            self.assertConfigRestored()
            self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)   # handlers put back

    def test_restore_puts_the_kernal_first_and_reboots_even_if_resume_fails(self):
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, labels=self.labels)
        orig = self.u.resume
        state = {"restoring": False}
        orig_restore = session.ConfigGuard.restore

        def restore(g):
            state["restoring"] = True
            return orig_restore(g)

        def resume():
            if state["restoring"]:
                raise RuntimeError("resume failed")
            return orig()
        self.u.resume = resume
        session.ConfigGuard.restore = restore
        self.addCleanup(setattr, session.ConfigGuard, "restore", orig_restore)
        n0 = []
        self.run_session(sim, plan="2 T 1\n")
        puts = [(c, i) for c, i, v in self.fake.config_puts]
        self.assertEqual(puts[-5:][0], self.KERNAL)                    # first PUT of the restore
        reboots = [p for m, p in self.fake.requests if p.endswith("reboot")]
        self.assertGreaterEqual(len(reboots), 3)                       # apply, Kernal in, restore
        self.assertEqual(self.fake.configs[self.KERNAL], "JiffyDOS-C64.bin")

    def test_kernal_not_restored_is_loud_and_exits_4(self):
        def hook(orig):
            def put(g, c, i, v):
                if (c, i) == self.KERNAL and g.restored:
                    raise RuntimeError("PUT failed")
                return orig(g, c, i, v)
            return put
        self.hook_put(hook)
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, labels=self.labels)
        self.run_session(sim, plan="2 T 1\n")
        self.assertEqual(self.status, session.EXIT_KERNAL_NOT_RESTORED)
        self.assertEqual(self.fake.configs[self.KERNAL], "")
        self.assertTrue(any("KERNAL NOT RESTORED" in c for c in self.comments()))

    def test_kernal_read_back_mismatch_stops_the_run(self):
        # the firmware ignores the Kernal PUT: nothing changes, the run stops at the first attempt
        orig = self.fake._configs

        def cfg(h, method, sub, cmd, q, body):
            if method == "PUT" and "Kernal" in sub:
                return self.fake._json(h)
            return orig(h, method, sub, cmd, q, body)
        self.fake._configs = cfg
        sim = Sim(self.fake, self.prg, loads=["ok"] * 20, labels=self.labels)
        self.run_session(sim, plan="2 TS 3\n")
        self.assertEqual(self.status, 3)
        rows = self.rows()
        trials = [r for r in rows if r["outcome"] not in ("NOTE", "STOP")]
        self.assertEqual(len(trials), 1, [(r["arm"], r["outcome"]) for r in rows])      # first attempt only
        self.assertIn("read back", trials[0]["detail"])
        self.assertFalse(any(r["outcome"] == "skipped" or "reached" in r["note"] for r in rows))
        self.assertEqual(len(sim.loads), 20)                        # no load was ever typed
        self.assertEqual(self.fake.configs[self.KERNAL], "JiffyDOS-C64.bin")

    def test_unreadable_original_kernal_stops_select(self):
        g = session.ConfigGuard(self.u, Sim(self.fake, self.prg), lambda *a: None)
        g.kernal_orig = "<unreadable: boom>"
        g.stock_value = ""
        with self.assertRaises(session.StopSession):
            g.select_kernal(True)
        self.assertEqual(self.fake.config_puts, [])

    def test_start_refuses_an_unexpected_kernal(self):
        for cur in ("", "JiffyDOS-kernal.bin"):
            self.fake.configs[self.KERNAL] = cur
            for plan in ("1 C 1\n", "2 TS 1\n"):
                sim = Sim(self.fake, self.prg, loads=["ok"] * 2, labels=self.labels)
                with self.assertRaises(SystemExit) as cm:
                    self.run_session(sim, plan=plan)
                self.assertIn("refusing to start", str(cm.exception))
                self.assertEqual(self.fake.config_puts, [], (cur, plan))
        del self.fake.configs[self.KERNAL]                   # unreadable
        with self.assertRaises(SystemExit):
            self.run_session(Sim(self.fake, self.prg), plan="1 C 1\n")
        self.assertEqual(self.fake.config_puts, [])

    def test_allow_kernal_overrides_except_when_it_makes_stock_arms_pointless(self):
        self.fake.configs[self.KERNAL] = "JiffyDOS-kernal.bin"
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, labels=self.labels)
        self.run_session(sim, plan="2 TS 1\n", extra=["--allow-kernal", "JiffyDOS-kernal.bin"])
        self.assertEqual(self.status, 0)
        self.assertEqual(self.fake.configs[self.KERNAL], "JiffyDOS-kernal.bin")      # put back to what it was
        self.fake.configs[self.KERNAL] = ""
        with self.assertRaises(SystemExit) as cm:
            self.run_session(Sim(self.fake, self.prg), plan="2 TS 1\n", extra=["--allow-kernal", ""])
        self.assertIn("already the stock", str(cm.exception))
        self.run_session(Sim(self.fake, self.prg, loads=["ok"], labels=self.labels), plan="1 C 1\n",
                         extra=["--allow-kernal", ""])                              # no stock arm: fine
        self.assertEqual(self.status, 0)

    def test_h_hang_with_the_bus_never_idle_is_a_loading_hang_like_j(self):
        def bus(t):
            return 0xC7 if not sim.marks else 0xCD
        sim = self.idle_sim(bus, loads=["hang"])
        self.run_session(sim, plan="4 H 1\n")
        h = [r for r in self.rows() if r["arm"] == "H"][0]
        sim_j = Sim(self.fake, self.prg, loads=["hang"], labels=self.labels)
        self.run_session(sim_j, plan="4 J 1\n")
        j = [r for r in self.rows() if r["arm"] == "J"][0]
        self.assertEqual(h["outcome"], "LOADING hang")
        self.assertEqual(h["outcome"], j["outcome"])
        self.assertIn("skipped=", h["detail"])

    def test_g_panic_with_the_bus_never_idle_is_a_panic_like_q(self):
        sim = self.idle_sim(lambda t: 0xCD, boots=["panic"])
        self.run_session(sim, plan="3 G 1\n")
        g = [r for r in self.rows() if r["arm"] == "G"][0]
        sim_q = Sim(self.fake, self.prg, boots=["panic"], labels=self.labels)
        self.run_session(sim_q, plan="3 Q 1\n")
        q = [r for r in self.rows() if r["arm"] == "Q"][0]
        self.assertEqual(g["outcome"], "root-mount panic")
        self.assertEqual(g["outcome"], q["outcome"])
        self.assertEqual([x[0] for x in sim.big_reads if x[0] < 169], [])     # still no read while busy

    def test_arm_z_resumes_when_the_pause_itself_fails(self):
        sim = Sim(self.fake, self.prg, boots=["ok"], labels=self.labels)
        rig = session.Rig(self.u, sim, self.prg, self.labels, "X")

        def pause():
            raise RuntimeError("pause failed (maybe after the machine stopped)")
        self.u.pause = pause
        with self.assertRaises(RuntimeError):
            rig.poll_screen(session.POLL_ARMS["Z"])
        self.assertIn(("PUT", "/v1/machine:resume"), self.fake.requests)

    def test_gated_arms_sleep_after_the_read_like_q_and_j(self):
        sim = self.idle_sim(lambda t: 0xC7, boots=["ok"])
        self.run_session(sim, plan="3 G 1\n")
        ts = [t for t, a, n in sim.big_reads if t > 3]
        self.assertGreater(len(ts), 5)
        # gate (2 x 0.1 s) then 0.5 s after the read: 0.7 s start to start, not 0.5
        self.assertAlmostEqual(ts[2] - ts[1], 0.7, places=6)

    def test_the_fake_tells_a_missing_value_from_an_empty_one(self):
        self.u.call("PUT", "/v1/configs/A/B", {"value": ""})
        self.assertEqual(self.fake.config_puts[-1], ("A", "B", ""))
        with self.assertRaises(Exception):
            self.u.call("PUT", "/v1/configs/A/B")


    # ---- second hater review (blocked 8726c79)
    def test_reboot_failing_after_the_kernal_put_stops_the_run(self):
        orig = self.u.reboot
        state = {"n": 0}

        def reboot():
            if self.fake.configs.get(self.KERNAL) == "" and state["n"] == 0:
                state["n"] = 1
                raise OSError("timed out")
            return orig()
        self.u.reboot = reboot
        sim = Sim(self.fake, self.prg, loads=["ok"] * 8, boots=["ok"] * 2, labels=self.labels)
        self.run_session(sim, plan="2 TS 2\n")
        self.assertEqual(self.status, 3)
        trials = [r for r in self.rows() if r["outcome"] not in ("NOTE", "STOP")]
        self.assertEqual(len(trials), 1)                              # no stock arm ran on the wrong ROM
        self.assertIn("selection failed", trials[0]["detail"])
        self.assertEqual(len(sim.loads), 8)
        self.assertEqual(self.fake.configs[self.KERNAL], "JiffyDOS-C64.bin")

    def test_kernal_put_rejected_by_firmware_stops_the_run(self):
        orig = self.fake._configs

        def cfg(h, method, sub, cmd, q, body):
            if method == "PUT" and "Kernal" in sub and q.get("value") == "":
                return self.fake._json(h, 400, ["bad value"])
            return orig(h, method, sub, cmd, q, body)
        self.fake._configs = cfg
        sim = Sim(self.fake, self.prg, loads=["ok"] * 20, labels=self.labels)
        self.run_session(sim, plan="2 TS 3\n")
        self.assertEqual(self.status, 3)
        rows = self.rows()
        self.assertEqual(len([r for r in rows if r["outcome"] not in ("NOTE", "STOP")]), 1)
        self.assertFalse(any(r["outcome"] == "skipped" or "reached" in r["note"] for r in rows))

    def test_ctrl_c_in_the_final_config_dump_keeps_exit_4(self):
        def hook(orig):
            def put(g, c, i, v):
                if (c, i) == self.KERNAL and g.restored:
                    raise RuntimeError("PUT failed")
                return orig(g, c, i, v)
            return put
        self.hook_put(hook)
        import cfgdump
        o = cfgdump.write_dump

        def wd(c, path):
            if path.endswith("end.json"):
                raise KeyboardInterrupt
            return o(c, path)
        cfgdump.write_dump = wd
        self.addCleanup(setattr, cfgdump, "write_dump", o)
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, labels=self.labels)
        self.run_session(sim, plan="2 T 1\n")
        self.assertEqual(self.status, session.EXIT_KERNAL_NOT_RESTORED)

    def test_teardown_ignores_signals_from_its_first_instruction(self):
        import signal
        seen = []
        orig = session.ConfigGuard.restore

        def restore(g):
            seen.append(signal.getsignal(signal.SIGINT))      # main's finally has already ignored it
            return orig(g)
        session.ConfigGuard.restore = restore
        self.addCleanup(setattr, session.ConfigGuard, "restore", orig)
        sim = Sim(self.fake, self.prg, loads=["ok"], labels=self.labels)
        self.run_session(sim, plan="1 C 1\n")
        self.assertEqual(seen, [signal.SIG_IGN])
        self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)

    def test_restore_announces_itself(self):
        import contextlib
        import io
        buf = io.StringIO()
        sim = Sim(self.fake, self.prg, loads=["ok"], labels=self.labels)
        with contextlib.redirect_stdout(buf):
            self.run_session(sim, plan="1 C 1\n")
        self.assertIn("restoring the Ultimate config; Ctrl-C is ignored until done", buf.getvalue())

    def test_one_flaky_kernal_read_back_after_restore_is_not_a_failed_restore(self):
        orig = session.ConfigGuard.get
        state = {"n": 0}

        def get(g, c, i):
            if g.restored and (c, i) == self.KERNAL and state["n"] == 0:
                state["n"] = 1
                return "<unreadable: blip>"
            return orig(g, c, i)
        session.ConfigGuard.get = get
        self.addCleanup(setattr, session.ConfigGuard, "get", orig)
        sim = Sim(self.fake, self.prg, loads=["ok"] * 3, labels=self.labels)
        self.run_session(sim, plan="2 T 1\n")
        self.assertEqual(state["n"], 1)
        self.assertEqual(self.status, 0)
        self.assertFalse(any("KERNAL NOT RESTORED" in c for c in self.comments()))


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
            if state["n"] == 3:
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
