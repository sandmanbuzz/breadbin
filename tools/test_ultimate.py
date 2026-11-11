"""Host tests: the Ultimate REST client and test backend, against a fake server.

No hardware or emulator. They check our side of the protocol as documented; what
the real firmware does is for the hardware session to confirm (docs/hardware-notes.md).
"""
import collections
import threading
import time
import unittest

import fake_ultimate
import mkimage
import ultimate
import ultimatetest
from ultimate import KeyInjectionUnavailable, Ultimate, UltimateError
from ultimatetest import UltimateTarget, keys_for, petscii


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = fake_ultimate.FakeUltimate().start()
        self.addCleanup(self.fake.stop)
        self.u = Ultimate(self.fake.host, port=self.fake.port)


class Client(Base):
    def test_info_and_version(self):
        self.assertEqual(self.u.version()["version"], "0.1")
        self.assertIn("Ultimate", self.u.info()["product"])

    def test_memory_round_trip(self):
        self.u.writemem(0x0400, b"hello")                      # small: PUT with hex
        self.assertEqual(self.u.readmem(0x0400, 5), b"hello")
        big = bytes(range(256)) * 2
        self.u.writemem(0x2000, big)                           # large: POST body
        self.assertEqual(self.u.readmem(0x2000, 512), big)
        self.assertEqual(self.u.readmem(0xFFFF, 1), b"\x00")

    def test_memory_ranges_are_checked(self):
        with self.assertRaises(ValueError):
            self.u.readmem(0xFFFF, 2)
        with self.assertRaises(ValueError):
            self.u.writemem(0xFFFF, b"ab")

    def test_password(self):
        with fake_ultimate.FakeUltimate(password="secret").start() as f:
            with self.assertRaisesRegex(UltimateError, "403"):
                Ultimate(f.host, port=f.port).info()
            self.assertIn("product", Ultimate(f.host, port=f.port, password="secret").info())

    def test_errors_in_the_reply_raise(self):
        with self.assertRaises(UltimateError):
            self.u.call("PUT", "/v1/machine:nosuchthing")

    def test_unreachable_host_raises(self):
        with self.assertRaises(UltimateError):
            Ultimate("127.0.0.1", port=1, timeout=1).info()

    def test_machine_control(self):
        self.u.reset()
        self.assertEqual(self.fake.resets, 1)
        self.u.pause()
        self.assertTrue(self.fake.paused)
        self.u.resume()
        self.assertFalse(self.fake.paused)
        self.assertEqual(len(self.u.menu_screen()[0]), 1000)

    def test_keyboard_events(self):
        self.u.keyboard(["left_shift", "1"])
        self.u.keyboard(["a"], "press")
        self.u.release_all()
        self.assertEqual([e["kind"] for e in self.fake.events], ["keyboard", "keyboard", "release_all"])
        self.assertEqual(self.fake.events[0]["inputs"], ["left_shift", "1"])

    def test_no_key_injection_is_a_clear_error(self):
        with fake_ultimate.FakeUltimate(key_injection=False).start() as f:
            u = Ultimate(f.host, port=f.port)
            with self.assertRaisesRegex(KeyInjectionUnavailable, "no key injection"):
                u.keyboard(["a"])
            with self.assertRaises(unittest.SkipTest):          # keyboard tests skip, not error
                UltimateTarget(client=u).focus()
            f.ram[0x0289] = 10
            UltimateTarget(client=u).type("ok")                  # the key buffer still works
            self.assertEqual(f.ram[0xC6], 2)

    def test_input_is_split_to_64_events(self):
        self.u.input([{"kind": "keyboard", "inputs": ["a"], "transition": "tap"}] * 130)
        self.assertEqual(len(self.fake.events), 130)
        posts = [r for r in self.fake.requests if r[1] == "/v1/machine:input"]
        self.assertEqual(len(posts), 3)

    def test_input_is_split_to_4096_bytes(self):
        ev = {"kind": "keyboard", "inputs": list("abcdefgh"), "transition": "tap"}
        self.u.input([ev] * 64)                 # 64 events, but over 4096 bytes of JSON
        self.assertEqual(len(self.fake.events), 64)
        self.assertGreater(len([r for r in self.fake.requests if r[1] == "/v1/machine:input"]), 1)

    def test_mount_multipart_and_raw(self):
        img = b"D64" * 100
        self.u.mount("a", img, mode="unlinked")
        raw = Ultimate(self.fake.host, port=self.fake.port, attach="raw")
        raw.mount("b", img, mode="readonly")
        a, b = self.fake.mounts
        self.assertEqual((a["drive"], a["how"], a["mode"], a["type"], a["data"]),
                         ("a", "multipart", "unlinked", "d64", img))
        self.assertEqual((b["drive"], b["how"], b["mode"], b["data"]), ("b", "raw", "readonly", img))

    def test_mount_a_file_on_the_ultimate(self):
        self.u.mount("a", "/USB0/breadbin.d64")
        self.assertEqual(self.fake.mounts[0]["image"], "/USB0/breadbin.d64")

    def test_run_prg_loads_at_its_address(self):
        self.u.run_prg(b"\x00\xc0\xa9\x05\x60")
        self.assertEqual(bytes(self.fake.ram[0xC000:0xC003]), b"\xa9\x05\x60")
        self.assertEqual(self.fake.runs[0]["how"], "multipart")
        self.assertEqual(self.fake.resets, 1)

    def test_streams(self):
        self.u.stream_start("video", "192.168.1.2:11000")
        self.assertEqual(self.fake.streams, {"video": "192.168.1.2:11000"})
        self.u.stream_stop("video")
        self.assertEqual(self.fake.streams, {})


class Keys(unittest.TestCase):
    def test_keys_for(self):
        self.assertEqual(keys_for("a"), ["a"])
        self.assertEqual(keys_for("A"), ["left_shift", "a"])
        self.assertEqual(keys_for("!"), ["left_shift", "1"])
        self.assertEqual(keys_for("|"), ["left_shift", "minus"])
        self.assertEqual(keys_for("\n"), ["return"])
        self.assertEqual(keys_for(" "), ["space"])
        with self.assertRaises(ValueError):
            keys_for("{")

    def test_keys_are_all_valid_ultimate_names(self):
        valid = set(fake_ultimate.KEYS)
        for ch in "abcxyz0189 \n+-.,:;=/*@_^!\"#$%&'()<>?[]|ABZ\x08":
            self.assertLessEqual(set(keys_for(ch)), valid, ch)
        for names in ultimatetest.XNAMES.values():
            self.assertLessEqual(set(names), valid)

    def test_petscii(self):
        self.assertEqual([petscii(c) for c in "aZ1\n|"], [0x41, 0xDA, 0x31, 0x0D, 0xDD])


class FakeClock:
    """Virtual time for UltimateTarget: sleeps cost nothing but a yield, so the 0.1 s pacing, the
    quiet periods and the timeouts run in milliseconds while every duration stays measurable."""

    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    time = monotonic

    def sleep(self, d):
        self.t += d
        time.sleep(0.0005)          # let the fake server and the drain thread run


class Target(Base):
    READY = bytes([0x12, 0x05, 0x01, 0x04, 0x19, 0x2E])      # "ready." as screen codes
    PRG = b"\x01\x08" + bytes(range(1, 200))                  # load address $0801, 199 bytes
    BREAK = bytes([0x02, 0x12, 0x05, 0x01, 0x0B])

    def setUp(self):
        super().setUp()
        self.clock = FakeClock()

    def target(self):
        return UltimateTarget(client=self.u, clock=self.clock, _min_quiet=0)

    def boot(self, f, **kw):
        kw.setdefault("load_quiet", 0.1)
        return UltimateTarget(f.name, client=self.u, settle=0, clock=self.clock, _min_quiet=0, **kw)

    def log_reads(self):
        """Every readmem as (virtual time, address, length); chains to an existing hook."""
        log, prev = [], self.fake.on_readmem
        clock = self.clock

        def hook(a, n):
            log.append((clock.t, a, n))
            if prev:
                prev(a, n)
        self.fake.on_readmem = hook
        return log

    def drain(self):
        """Stand in for the C64 consuming keys: empty the buffer, record what was in it."""
        seen = bytearray()
        stop = threading.Event()

        def run():
            while not stop.is_set():
                with self.fake.lock:                  # a paused C64 does not run
                    n = self.fake.ram[0xC6]
                    if n and not self.fake.paused:
                        seen.extend(self.fake.ram[0x0277:0x0277 + n])
                        self.fake.ram[0xC6] = 0
                time.sleep(0.01)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.addCleanup(lambda: (stop.set(), t.join()))
        return seen

    def script_load(self, busy_polls=0, final=None, row=4):
        """A C64 that shows "searching" under the cursor for the first busy_polls reads of $D6,
        then `final` lines (default: loading / ready.) with the cursor on `row`."""
        self.fake.poke(0x0400, b"\x20" * 1000)
        final = final if final is not None else [b"\x0c", self.READY]
        n = [0]

        def show(r, line):
            self.fake.poke(0x0400 + 40 * r, b"\x20" * 40)
            self.fake.poke(0x0400 + 40 * r, line)

        def hook(a, ln):
            if a != 0xD6:
                return
            n[0] += 1
            if n[0] <= busy_polls:
                self.fake.ram[0xD6] = 3
                show(2, b"\x13\x05\x01")               # "sea"
            else:
                for i, line in enumerate(final):
                    show(row - len(final) + i, line)
                self.fake.ram[0xD6] = row
        self.fake.on_readmem = hook

    def image(self, prg=None, poke=True):
        """A real .d64 whose first file is `prg`; with poke, the fake's RAM already holds the loaded
        bytes and the end pointer."""
        import os
        import tempfile
        prg = prg or self.PRG
        img = mkimage.Image()
        img.write_cbm(b"BREADBIN", prg)
        with tempfile.NamedTemporaryFile(suffix=".d64", delete=False) as f:
            f.write(bytes(img.data))
        self.addCleanup(os.unlink, f.name)
        if poke:
            base = prg[0] | prg[1] << 8
            self.fake.poke(base, prg[2:])
            end = base + len(prg) - 2
            self.fake.poke(0xAE, bytes([end & 0xFF, end >> 8]))
        return f

    @staticmethod
    def disk(f):
        with open(f.name, "rb") as fh:
            return fh.read()

    def assertPaced(self, log, gap=0.09, skip=()):
        gaps = [b[0] - a[0] for a, b in zip(log, log[1:])]
        self.assertGreater(len(log), 2)
        self.assertGreaterEqual(min(g for i, g in enumerate(gaps) if i not in skip), gap, gaps)

    # ---- keybuf, screen, bus gate
    def test_keybuf_writes_the_stock_buffer(self):
        self.fake.ram[0x0289] = 10
        self.target().keybuf(b"\x03\x91")
        self.assertEqual(bytes(self.fake.ram[0x0277:0x0279]), b"\x03\x91")
        self.assertEqual(self.fake.ram[0xC6], 2)
        self.assertFalse(self.fake.paused)

    def test_type_chunks_and_waits_for_room(self):
        self.fake.ram[0x0289] = 10
        seen = self.drain()
        self.target().type("echo hello world\n")
        deadline = time.time() + 5
        while len(seen) < 17 and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(bytes(seen), bytes(petscii(c) for c in "echo hello world\n"))

    def test_keybuf_times_out_if_nothing_drains(self):
        self.fake.ram[0x0289] = 10
        self.fake.ram[0xC6] = 10
        with self.assertRaises(TimeoutError):
            self.target().keybuf(b"x", timeout=0.3)
        self.assertFalse(self.fake.paused)

    def test_screen_is_read_from_screen_ram(self):
        self.fake.poke(0x0400, b"\x20" * 1000)                      # blank screen
        self.fake.poke(0x0400, bytes([0x2F, 0x20, 0x24]))          # "/ $"
        self.fake.poke(0x0400 + 40, bytes([0x08, 0x09]))            # "hi"
        lines = self.target().screen_lines()
        self.assertEqual(lines[0], "/ $")
        self.assertEqual(lines[1], "hi")

    def test_screen_lines_outside_a_wait_never_returns_a_stale_screen(self):
        # chosen: wait (bounded) for the gate, then raise; callers poll or look once, and a stale
        # screen would silently be the wrong one
        self.fake.poke(0x0400, b"\x20" * 1000)
        self.fake.poke(0x0400, bytes([0x08, 0x09]))                 # "hi"
        t = self.target()
        self.assertEqual(t.screen_lines()[0], "hi")
        self.fake.ram[0xDD00] = 0x87                               # CLK in low: a transfer
        self.fake.poke(0x0400, bytes([0x0F, 0x0B]))                 # "ok", not to be seen yet
        with self.assertRaises(TimeoutError) as cm:
            t.screen_lines(gate_timeout=3)
        self.assertIn("never idle", str(cm.exception))
        self.fake.ram[0xDD00] = 0xC7
        self.assertEqual(t.screen_lines()[0], "ok")

    def test_screen_lines_waits_for_the_gate_to_open(self):
        self.fake.poke(0x0400, b"\x20" * 1000)
        self.fake.poke(0x0400, bytes([0x0F, 0x0B]))
        self.fake.ram[0xDD00] = 0x87
        t = self.target()
        t0 = self.clock.t

        def hook(a, n):
            if self.clock.t - t0 > 2:
                self.fake.ram[0xDD00] = 0xC7
        self.fake.on_readmem = hook
        self.assertEqual(t.screen_lines()[0], "ok")

    def test_any_driven_line_counts_as_busy(self):
        t = self.target()
        for v in (0x47, 0x87, 0xE7, 0xD7, 0xCF):                    # DATA in, CLK in low; DATA, CLK, ATN out
            self.fake.ram[0xDD00] = v
            self.assertFalse(t.bus_idle(), hex(v))
        for v in (0xC0, 0xC3, 0xC4, 0xC7):                          # VIC bank and PA2 do not matter
            self.fake.ram[0xDD00] = v
            self.assertTrue(t.bus_idle(), hex(v))

    def kernal_target(self):
        t = self.target()
        t._bus_idle_values = ultimatetest.BUS_IDLE_KERNAL
        return t

    def test_the_gate_opens_at_the_kernals_idle_only_in_the_kernal_phase(self):
        self.fake.poke(0x0400, b"\x20" * 1000)
        self.fake.ram[0xDD00] = 0x97                  # measured at BASIC READY (JiffyDOS KERNAL), idle
        t = self.kernal_target()
        t.screen_lines(gate_timeout=1)
        t.verify_loaded(self.disk(self.image()))      # the read-back gates at READY too
        own = self.target()
        self.assertFalse(own.bus_idle())              # Breadbin phase: $90 is a send, not idle
        with self.assertRaises(TimeoutError):
            own.screen_lines(gate_timeout=1)

    def test_gate_verdict_over_all_256_values_in_both_phases(self):
        for phase, allowed in ((ultimatetest.BUS_IDLE_OWN, (0xC0,)), (ultimatetest.BUS_IDLE_KERNAL, (0xC0, 0x90))):
            t = self.target()
            t._bus_idle_values = phase
            for v in range(256):
                self.fake.ram[0xDD00] = v
                self.assertEqual(t.bus_idle(), (v & 0xF8) in allowed, (phase, hex(v)))

    def test_all_three_samples_must_be_the_same_value(self):
        t = self.kernal_target()
        for seq, want in (((0x97, 0xC7, 0x97), False), ((0xC7, 0x97, 0xC7), False),
                          ((0xC7, 0xC7, 0xC7), True), ((0x97, 0x97, 0x97), True),
                          ((0xC7, 0xC7, 0x97), False)):
            n = [0]

            def hook(a, ln, seq=seq, n=n):
                if a == 0xDD00:
                    self.fake.ram[0xDD00] = seq[min(n[0], 2)]
                    n[0] += 1
            self.fake.on_readmem = hook
            self.assertEqual(t.bus_idle(), want, [hex(v) for v in seq])

    def test_gate_log_prints_verdicts_raw_bytes_and_the_gated_read(self):
        import contextlib
        import io
        import os
        self.fake.poke(0x0400, b"\x20" * 1000)
        os.environ["BREADBIN_ULTIMATE_GATELOG"] = "1"
        self.addCleanup(os.environ.pop, "BREADBIN_ULTIMATE_GATELOG", None)
        t = self.target()
        err = io.StringIO()
        self.fake.ram[0x0289] = 10
        with contextlib.redirect_stderr(err):
            t.screen_lines()
            t.keybuf(b"x")
        out = err.getvalue()
        self.assertIn("gate idle raw=$C7,$C7,$C7 t=", out)
        self.assertIn("gate read $0400 len 1000 t=", out)
        self.assertIn("gate keys len 1 t=", out)
        os.environ.pop("BREADBIN_ULTIMATE_GATELOG")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.target().screen_lines()
        self.assertNotIn("gate ", err.getvalue())              # off by default

    def test_boot_accepts_the_kernals_idle_until_run_and_only_c0_after(self):
        f = self.image()
        self.loaded_machine()
        self.fake.ram[0xDD00] = 0x97                  # the KERNAL's idle through the whole boot
        t = self.boot(f)
        self.assertFalse(t.bus_idle())                # now Breadbin runs: $97 is not idle
        self.fake.ram[0xDD00] = 0xC7
        self.assertTrue(t.bus_idle())
        self.fake.ram[0xDD00] = 0x97
        t.boot(f.name)                                # a reboot returns to the KERNAL set
        self.assertFalse(t.bus_idle())

    def dd00_script(self, values):
        """$DD00 reads return `values` in turn (then the last one forever)."""
        vals, prev = list(values), self.fake.on_readmem

        def hook(a, n):
            if a == 0xDD00:
                self.fake.ram[0xDD00] = vals.pop(0) if len(vals) > 1 else vals[0]
            if prev:
                prev(a, n)
        self.fake.on_readmem = hook

    def test_a_gated_read_between_busy_verdicts_is_reported_without_the_log(self):
        import contextlib
        import io
        self.fake.poke(0x0400, b"\x20" * 1000)
        t = self.target()
        self.dd00_script([0x87, 0xC7, 0xC7, 0xC7, 0x87])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            t.screen_lines()                 # busy, then idle x3, then the read
            self.assertFalse(t.bus_idle())   # busy straight after it
        self.assertEqual(t.gate_races, 1)
        self.assertIn("ultimatetest: gate race #1: read $0400 len 1000 landed between busy verdicts", err.getvalue())
        self.assertIn("race #1", t._recent())
        for _ in range(40):                  # the race's context outlives the rolling history
            t.bus_idle()
        self.assertIn("events up to race #1:", t._recent())
        self.assertIn("race #1: read $0400 len 1000", t._recent())

    def test_the_race_line_quotes_the_busy_sample(self):
        import contextlib
        import io
        self.fake.poke(0x0400, b"\x20" * 1000)
        t = self.target()
        self.dd00_script([0x87, 0xC7, 0xC7, 0xC7, 0xC7, 0x67])     # busy after: $C7 then $67
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            t.screen_lines()
            self.assertFalse(t.bus_idle())
        self.assertIn("the busy sample $67", err.getvalue())

    def test_keybufs_one_byte_count_read_is_not_a_race(self):
        import contextlib
        import io
        self.fake.ram[0x0289] = 10
        t = self.target()
        self.dd00_script([0x87, 0xC7, 0xC7, 0xC7, 0x87])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            t.keybuf(b"x")                    # count read is 1 byte; the key write is the gated DMA
            self.fake.ram[0xC6] = 0
            t.bus_idle()
        self.assertEqual((t.gate_races, t.gate_key_candidates), (0, 1))
        self.assertIn("gate key-write candidate #1 (the busy verdict may be the typed command's own I/O): "
                      "key write len 1", err.getvalue())
        self.assertNotIn("read $00C6", err.getvalue())

    def race_run(self, before, after, script_after=(0xC7, 0xC7, 0xC7, 0x87)):
        """busy verdict (its third sample busy); `before` s; idle verdict + gated screen read; `after` s; one more verdict."""
        import contextlib
        import io
        self.fake.poke(0x0400, b"\x20" * 1000)
        t = self.target()
        self.fake.on_readmem = None          # a fresh script per run
        self.dd00_script([0xC7, 0xC7, 0x87] + list(script_after))   # busy on its third sample
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(t.bus_idle())
            self.clock.t += before
            t.screen_lines()
            self.clock.t += after
            t.bus_idle()
        return t

    def test_the_race_windows_are_measured_from_the_busy_sample_and_the_reads_end(self):
        # the waits poll every 0.4-0.5 s: a gap of about 0.6 s on either side is still a race
        self.assertEqual(self.race_run(0.9, 0.5).gate_races, 1)      # 0.9 s from the busy sample, 1.1 from its first
        self.assertEqual(self.race_run(1.1, 0.0).gate_races, 0)      # idle verdict too long after
        self.assertEqual(self.race_run(0.0, 1.1).gate_races, 0)      # next verdict too long after

    def test_a_gated_one_byte_read_after_a_busy_verdict_is_not_a_race(self):
        t = self.target()
        self.dd00_script([0x87, 0xC7, 0xC7, 0xC7, 0x87])
        self.assertFalse(t.bus_idle())
        self.assertTrue(t.bus_idle())
        t._dma_read(0x00C6, 1)                # gated (straight after the idle verdict), 1 byte
        self.assertFalse(t.bus_idle())
        self.assertEqual(t.gate_races, 0)

    def test_a_failed_gated_request_is_still_a_race_candidate(self):
        import contextlib
        import io
        t = self.target()
        self.dd00_script([0x87, 0xC7, 0xC7, 0xC7, 0x87])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertFalse(t.bus_idle())
            self.assertTrue(t.bus_idle())
            with self.assertRaises(Exception):
                t._dma_read(0xFFFF, 2)        # the fake refuses the range: the request fails
            self.assertFalse(t.bus_idle())
        self.assertEqual(t.gate_races, 1)
        self.assertIn("read $FFFF len 2 (failed) landed", err.getvalue())

    def test_a_failed_key_write_is_still_a_candidate(self):
        import contextlib
        import io
        self.fake.ram[0x0289] = 10
        t = self.target()
        self.dd00_script([0x87, 0xC7, 0xC7, 0xC7, 0x87])

        def broken(address, data):
            raise ultimate.UltimateError("write failed")
        t.u.writemem = broken
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertFalse(t.bus_idle())
            with self.assertRaises(ultimate.UltimateError):
                t.keybuf(b"x")
            self.assertFalse(t.bus_idle())
        self.assertEqual(t.gate_key_candidates, 1)
        self.assertIn("key write len 1 (failed) landed", err.getvalue())

    def test_a_race_on_mixed_idle_samples_does_not_call_an_idle_value_busy(self):
        import contextlib
        import io
        self.fake.poke(0x0400, b"\x20" * 1000)
        t = self.target()
        t._bus_idle_values = ultimatetest.BUS_IDLE_KERNAL
        self.dd00_script([0x87, 0xC7, 0xC7, 0xC7, 0xC7, 0x97, 0x97])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            t.screen_lines()
            self.assertFalse(t.bus_idle())
        self.assertIn("samples $C7,$97,$97 differ", err.getvalue())
        self.assertNotIn("busy sample", err.getvalue())

    def test_a_nested_timeout_carries_the_gate_history_once(self):
        self.fake.ram[0xDD00] = 0x87
        t = self.target()
        with self.assertRaises(TimeoutError) as cm:
            t._in_wait(t.keybuf, b"x", timeout=0.3)
        self.assertEqual(str(cm.exception).count("recent gate events"), 1)

    def test_a_boot_starts_a_new_race_history(self):
        f = self.image()
        self.loaded_machine()
        t = self.boot(f)
        t.gate_races, t.gate_key_candidates = 5, 2
        t._races = collections.deque([["race #5: old"]])
        t._suspect, t._last_busy = ("read $0400 len 1000", self.clock.t), self.clock.t
        t.boot(f.name)
        self.assertEqual((t.gate_races, t.gate_key_candidates, t._races, t._suspect, t._last_busy),
                         (0, 0, None, None, None))
        self.assertNotIn("race #5", t._recent())

    def test_no_race_without_a_busy_verdict_before(self):
        import contextlib
        import io
        self.fake.poke(0x0400, b"\x20" * 1000)
        t = self.target()
        self.dd00_script([0xC7, 0xC7, 0xC7, 0x87])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            t.screen_lines()
            self.assertFalse(t.bus_idle())
        self.assertEqual((t.gate_races, err.getvalue()), (0, ""))

    def test_timeouts_carry_the_recent_gate_events(self):
        self.fake.ram[0xDD00] = 0x87
        with self.assertRaises(TimeoutError) as cm:
            self.target().keybuf(b"x", timeout=0.3)
        self.assertIn("recent gate events", str(cm.exception))
        self.assertIn("busy raw=$87", str(cm.exception))

    def test_a_failed_boot_leaves_only_c0_accepted(self):
        f = self.image()
        self.loaded_machine()
        t = self.boot(f)
        for step in ("run", "verify"):
            def fail(*a, **k):
                raise ultimatetest.LoadError(step)
            orig_type, orig_verify = t.type, t.verify_loaded
            if step == "run":
                t.type = lambda text: fail() if text == "run\n" else orig_type(text)
            else:
                t.verify_loaded = fail
            with self.assertRaises(ultimatetest.LoadError):
                t.boot(f.name)
            t.type, t.verify_loaded = orig_type, orig_verify
            self.assertEqual(t._bus_idle_values, ultimatetest.BUS_IDLE_OWN, step)
            self.fake.ram[0xDD00] = 0x97
            self.assertFalse(t.bus_idle(), step)
            self.fake.ram[0xDD00] = 0xC7

    def test_keybuf_waits_for_an_idle_bus(self):
        self.fake.ram[0x0289] = 10
        self.fake.ram[0xDD00] = 0x87
        with self.assertRaises(TimeoutError):
            self.target().keybuf(b"x", timeout=0.5)
        self.assertEqual(self.fake.ram[0xC6], 0)
        self.assertFalse(self.fake.paused)

    def test_mem_is_inclusive_like_vice(self):
        self.fake.poke(0x0100, b"\x01\x02\x03")
        self.assertEqual(self.target().mem(0x0100, 0x0102), [1, 2, 3])

    def test_real_keys(self):
        t = self.target()
        t.xkey("a", "Return", "exclam", delay=0)
        t.xtype("Hi", delay=0)
        t.xdown("Shift_L")
        t.xup("Shift_L")
        got = [(e["inputs"], e["transition"]) for e in self.fake.events]
        self.assertEqual(got, [
            (["a"], "tap"), (["return"], "tap"), (["left_shift", "1"], "tap"),
            (["left_shift", "h"], "tap"), (["i"], "tap"),
            (["left_shift"], "press"), (["left_shift"], "release")])

    def test_keybuf_busy_path_is_paced_and_does_not_spin(self):
        self.fake.ram[0x0289] = 10
        self.fake.ram[0xDD00] = 0x87
        t = self.target()
        log = self.log_reads()
        with self.assertRaises(TimeoutError):
            t.keybuf(b"x", timeout=0.8)
        self.assertLess(len(log), 12, len(log))          # was thousands per second
        self.assertPaced(log)

    def test_gated_screen_read_follows_the_last_idle_sample_at_once(self):
        # the validated arm: three 1-byte samples 0.1 s apart, then ONE 1000-byte read (a snapshot)
        self.fake.poke(0x0400, b"\x20" * 1000)
        t = self.target()
        log = self.log_reads()
        t.screen_lines()
        t.screen_lines()
        self.assertEqual([n for _, _, n in log], [1, 1, 1, 1000, 1, 1, 1, 1000])
        self.assertLess(log[3][0] - log[2][0], 0.05)
        self.assertLess(log[7][0] - log[6][0], 0.05)
        self.assertGreaterEqual(log[1][0] - log[0][0], 0.09)       # samples and polling stay paced
        self.assertGreaterEqual(log[4][0] - log[3][0], 0.09)

    def test_keybuf_reads_the_count_at_once_then_bytes_then_count_without_pause(self):
        self.fake.ram[0x0289] = 10
        t = self.target()
        log = self.log_reads()
        n0 = len(self.fake.requests)
        self.writes, real = [], t.u.writemem
        t.u.writemem = lambda a, d: (self.writes.append((a, bytes(d))), real(a, d))[1]
        t.keybuf(b"ab")
        self.assertEqual([a for _, a, _ in log], [0xDD00] * 3 + [0xC6])
        self.assertLess(log[3][0] - log[2][0], 0.05)             # the count read follows the verdict
        self.assertGreaterEqual(log[1][0] - log[0][0], 0.09)
        cmds = [r[1] for r in self.fake.requests[n0:]]
        self.assertFalse([c for c in cmds if "pause" in c or "resume" in c], cmds)
        self.assertEqual(self.writes, [(0x0277, b"ab"), (0xC6, b"\x02")])   # bytes first, count last
        self.assertEqual(self.fake.ram[0xC6], 2)

    def test_keybuf_waits_for_an_empty_buffer(self):
        self.fake.ram[0x0289] = 10
        self.fake.ram[0xC6] = 1
        self.fake.ram[0x0277] = 0x41
        with self.assertRaises(TimeoutError):
            self.target().keybuf(b"x", timeout=0.5)
        self.assertEqual((self.fake.ram[0xC6], self.fake.ram[0x0277]), (1, 0x41))   # untouched

    def test_keybuf_refuses_more_than_the_buffer_holds(self):
        for data in (b"", b"x" * 11):
            with self.assertRaises(ValueError):
                self.target().keybuf(data)

    # ---- waits do not match a screen from before them
    def test_wait_for_does_not_match_a_screen_read_before_the_wait(self):
        self.fake.poke(0x0400, b"\x20" * 1000)
        self.fake.poke(0x0400, bytes([0x0C, 0x0F, 0x07]))     # "log"
        t = self.target()
        t.screen_lines()                                      # idle: cached
        self.fake.ram[0xDD00] = 0x87                          # busy from now on
        with self.assertRaises(TimeoutError) as cm:
            t.wait_for("log", timeout=3)
        msg = str(cm.exception)
        self.assertIn("stale", msg)
        self.assertIn("skipped", msg)

    def test_wait_for_matches_once_a_fresh_read_happens(self):
        self.fake.poke(0x0400, b"\x20" * 1000)
        self.fake.poke(0x0400, bytes([0x0C, 0x0F, 0x07]))
        self.fake.ram[0xDD00] = 0x87
        t = self.target()
        t0 = self.clock.t
        self.fake.on_readmem = lambda a, n: (self.clock.t - t0 > 1) and self.fake.ram.__setitem__(0xDD00, 0xC7)
        self.assertIn("log", t.wait_for("log", timeout=30))

    def test_wait_shell_does_not_match_a_stale_screen(self):
        self.fake.poke(0x0400, b"\x20" * 1000)
        self.fake.poke(0x0400, bytes([0x2F, 0x20, 0x24]))     # "/ $"
        t = self.target()
        t.screen_lines()
        self.fake.ram[0xDD00] = 0x87
        with self.assertRaises(TimeoutError) as cm:
            t.wait_shell(timeout=3)
        self.assertIn("stale", str(cm.exception))

    # ---- the one check after the quiet period
    def test_check_ready_path(self):
        self.script_load()
        log = self.log_reads()
        t = self.target()
        t0 = self.clock.t
        t.wait_ready_quiet(20)
        self.assertEqual({n for _, _, n in log}, {1})
        self.assertGreaterEqual(log[0][0] - t0, 20)            # nothing before the quiet is over
        self.assertEqual(log[0][1], 0xD6)

    def test_still_loading_after_the_quiet_is_a_loud_failure_after_one_check(self):
        self.script_load(busy_polls=10 ** 6)
        log = self.log_reads()
        with self.assertRaises(ultimatetest.LoadError) as cm:
            self.target().wait_ready_quiet(20)
        msg = str(cm.exception)
        self.assertIn("still running", msg)
        self.assertIn("20 s of quiet (one check)", msg)
        self.assertIn("BREADBIN_ULTIMATE_LOAD_QUIET", msg)
        self.assertEqual([a for _, a, _ in log], [0xD6, 0x0400 + 40 * 2])     # one check: $D6, the row byte

    def test_an_unreadable_check_fails_at_once_and_says_so(self):
        self.script_load(final=[bytes([0x12, 0x05, 0x01, 0x04])])      # "read": neither busy nor ready
        log = self.log_reads()
        with self.assertRaises(ultimatetest.LoadError) as cm:
            self.target().wait_ready_quiet(20)
        self.assertIn("not readable", str(cm.exception))
        self.assertNotIn("still running", str(cm.exception))
        self.assertEqual(len([1 for _, a, _ in log if a == 0xD6]), 1)     # one check, no second interval

    def test_error_above_ready(self):
        self.script_load(final=[b"\x3f\x0c\x0f", self.READY])    # ?LO..., then ready.
        with self.assertRaises(ultimatetest.LoadError) as cm:
            self.target().wait_ready_quiet(20)
        self.assertIn("error line", str(cm.exception))

    def test_error_before_ready_appears(self):
        self.script_load(final=[b"\x3f\x0c\x0f"])
        with self.assertRaises(ultimatetest.LoadError) as cm:
            self.target().wait_ready_quiet(20)
        self.assertIn("error line", str(cm.exception))

    def test_break_above_ready(self):
        self.script_load(final=[self.BREAK, self.READY])
        with self.assertRaises(ultimatetest.LoadError):
            self.target().wait_ready_quiet(20)

    def test_break_before_ready_appears(self):
        self.script_load(final=[self.BREAK])
        with self.assertRaises(ultimatetest.LoadError):
            self.target().wait_ready_quiet(20)

    def test_ready_at_the_bottom_of_a_scrolled_screen(self):
        self.script_load(row=24)
        self.target().wait_ready_quiet(20)

    def test_wait_ready_1byte_is_gone(self):
        self.assertFalse(hasattr(UltimateTarget, "wait_ready_1byte"))

    # ---- quiet validation
    def test_quiet_default_and_env(self):
        import os
        os.environ["BREADBIN_ULTIMATE_LOAD_QUIET"] = "7.5"
        self.addCleanup(os.environ.pop, "BREADBIN_ULTIMATE_LOAD_QUIET", None)
        self.assertEqual(UltimateTarget(client=self.u).load_quiet, 7.5)
        os.environ.pop("BREADBIN_ULTIMATE_LOAD_QUIET")
        self.assertEqual(UltimateTarget(client=self.u).load_quiet, ultimatetest.BOOT_QUIET)
        self.assertGreaterEqual(ultimatetest.BOOT_QUIET, ultimatetest.MIN_QUIET)

    def test_quiet_refuses_bad_values(self):
        import os
        self.addCleanup(os.environ.pop, "BREADBIN_ULTIMATE_LOAD_QUIET", None)
        for bad in ("nan", "inf", "-inf", "1", "4.9", "0", "-3", "soon", "600.1", "1e9"):
            os.environ["BREADBIN_ULTIMATE_LOAD_QUIET"] = bad
            with self.assertRaises(ValueError, msg=bad):
                UltimateTarget(client=self.u)
        os.environ.pop("BREADBIN_ULTIMATE_LOAD_QUIET")
        with self.assertRaises(ValueError):
            UltimateTarget(client=self.u, load_quiet=2)
        with self.assertRaises(ValueError):
            UltimateTarget(client=self.u, load_quiet=float("inf"))
        UltimateTarget(client=self.u, load_quiet=5)                     # the floor itself is allowed
        UltimateTarget(client=self.u, load_quiet=600)                   # and the ceiling

    def test_gate_timeout_default_outlasts_the_callers_waits(self):
        self.assertGreaterEqual(UltimateTarget.gate_timeout, 120)
        self.assertFalse(hasattr(self.target(), "boot_timeout"))

    def test_screen_lines_rides_out_a_long_busy_period(self):
        self.fake.poke(0x0400, b"\x20" * 1000)
        self.fake.ram[0xDD00] = 0x87
        t = self.target()
        t0 = self.clock.t
        self.fake.on_readmem = lambda a, n: (self.clock.t - t0 > 60) and self.fake.ram.__setitem__(0xDD00, 0xC7)
        t.screen_lines()                                  # 60 s of busy bus: no raise

    def test_deadlines_use_the_monotonic_clock(self):
        self.assertIs(ultimatetest._RealClock.time, time.monotonic)

    def test_readback_prints_the_end_pointer_for_the_hardware_log(self):
        import contextlib
        import io
        f = self.image()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.target().verify_loaded(self.disk(f))
        self.assertIn("end pointer $AE/$AF = $08C8, expected $08C8", err.getvalue())

    # ---- the read-back
    def test_readback_passes_when_ram_matches(self):
        f = self.image()
        self.target().verify_loaded(self.disk(f))

    def test_readback_reports_first_offset_and_count(self):
        f = self.image()
        self.fake.ram[0x0801 + 5] ^= 0xFF
        self.fake.ram[0x0801 + 9] ^= 0xFF
        with self.assertRaises(ultimatetest.LoadError) as cm:
            self.target().verify_loaded(self.disk(f))
        self.assertIn("offset 5", str(cm.exception))
        self.assertIn("2 bytes", str(cm.exception))

    def test_readback_checks_the_end_pointer(self):
        f = self.image()
        self.fake.ram[0xAE] ^= 0x01            # a short load over stale RAM: bytes match, pointer does not
        with self.assertRaises(ultimatetest.LoadError) as cm:
            self.target().verify_loaded(self.disk(f))
        self.assertIn("end pointer", str(cm.exception))

    def test_readback_uses_the_bytes_that_were_mounted(self):
        import os
        f = self.image()
        data = self.disk(f)
        os.unlink(f.name)
        self.addCleanup(lambda: open(f.name, "wb").close())     # so the image cleanup finds a file
        self.target().verify_loaded(data)

    def test_readback_skips_rom_overlaid_ranges(self):
        prg = b"\x00\x9f" + bytes(range(1, 256)) * 4            # $9F00 up past $A000
        f = self.image(prg=prg, poke=False)
        self.fake.poke(0x9F00, prg[2:2 + 0x100])                 # RAM below $A000 correct; above is ROM: wrong
        end = 0x9F00 + len(prg) - 2
        self.fake.poke(0xAE, bytes([end & 0xFF, end >> 8]))
        self.target().verify_loaded(self.disk(f))

    def test_readback_waits_for_an_idle_bus(self):
        f = self.image()
        self.fake.ram[0xDD00] = 0x87
        t = self.target()
        log = self.log_reads()
        with self.assertRaises(TimeoutError):
            t.verify_loaded(self.disk(f), timeout=0.6)
        self.assertEqual({n for _, _, n in log}, {1})

    def test_readback_reads_follow_the_idle_verdict_at_once(self):
        f = self.image()
        t = self.target()
        log = self.log_reads()
        t.verify_loaded(self.disk(f))
        self.assertEqual([a for _, a, _ in log], [0xDD00] * 3 + [0xAE] + [0xDD00] * 3 + [0x0801])
        self.assertLess(log[3][0] - log[2][0], 0.05)
        self.assertLess(log[7][0] - log[6][0], 0.05)

    # ---- boot
    def loaded_machine(self, **kw):
        self.fake.ram[0x0289] = 40
        self.script_load(**kw)
        self.fake.poke(0x0400, self.READY)           # for the wait before the load command
        return self.drain()

    def test_boot_makes_no_request_during_the_quiet_period_after_the_load_command(self):
        f = self.image()
        self.loaded_machine()
        marks = {}
        orig = UltimateTarget.type

        def typed(t, text):
            orig(t, text)
            if text.startswith("load"):
                marks["t"], marks["n"] = t._clock.t, len(self.fake.requests)
        UltimateTarget.type = typed
        self.addCleanup(setattr, UltimateTarget, "type", orig)
        log = self.log_reads()
        UltimateTarget(f.name, client=self.u, settle=0, clock=self.clock, load_quiet=20)
        after = [r for r in log if r[0] > marks["t"]]
        self.assertGreaterEqual(after[0][0] - marks["t"], 20)         # nothing before the quiet is over
        self.assertEqual(len(self.fake.requests) - marks["n"] > 0, True)
        # the first request after the load command is the check: no other request in between
        first = next(i for i, r in enumerate(self.fake.requests[marks["n"]:]) if "readmem" in r[1])
        self.assertEqual(first, 0)

    def test_boot_reads_no_screen_between_the_load_command_and_ready(self):
        f = self.image()
        self.loaded_machine()
        log = self.log_reads()
        UltimateTarget(f.name, client=self.u, settle=0, clock=self.clock, load_quiet=20)
        start = next(i for i, r in enumerate(log) if r[1] == 0xD6)
        big = [(a, ln) for _, a, ln in log[start:] if ln != 1]
        self.assertEqual(big, [(0xAE, 2), (0x0801, 199)])             # only the read-back, after ready.

    def test_boot_fails_on_a_corrupt_load(self):
        f = self.image()
        self.fake.ram[0x0801 + 7] ^= 0x01
        self.loaded_machine()
        with self.assertRaises(ultimatetest.LoadError):
            self.boot(f)

    def test_boot_fails_if_the_load_is_still_running(self):
        f = self.image()
        self.loaded_machine(busy_polls=10 ** 6)
        with self.assertRaises(ultimatetest.LoadError) as cm:
            self.boot(f)
        self.assertIn("BREADBIN_ULTIMATE_LOAD_QUIET", str(cm.exception))

    def test_boot_resumes_a_machine_left_paused(self):
        self.u.pause()
        self.u.reset()
        self.assertTrue(self.fake.paused)       # as on hardware: a reset keeps the pause
        self.loaded_machine()
        f = self.image()
        self.fake.paused_at_reset.clear()
        self.boot(f)
        self.assertEqual(self.fake.paused_at_reset, [False])    # the pause did not reach the reset

    def test_boot_loads_from_the_bus_the_environment_names(self):
        import os
        seen = self.loaded_machine()
        f = self.image()
        os.environ["BREADBIN_ULTIMATE_BUS"] = "9"
        self.addCleanup(os.environ.pop, "BREADBIN_ULTIMATE_BUS", None)
        self.boot(f)
        deadline = time.time() + 5
        want = bytes(petscii(c) for c in 'load"*",9,1\nrun\n')
        while len(seen) < len(want) and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(bytes(seen), want)

    def test_boot_mounts_resets_and_types_the_load_command(self):
        seen = self.loaded_machine()
        f = self.image()
        self.boot(f)
        deadline = time.time() + 5
        want = bytes(petscii(c) for c in 'load"*",8,1\nrun\n')
        while len(seen) < len(want) and time.time() < deadline:
            time.sleep(0.05)
        m = self.fake.mounts[0]
        self.assertEqual((m["drive"], m["mode"], m["data"]), ("a", "unlinked", self.disk(f)))
        self.assertGreaterEqual(self.fake.resets, 1)
        self.assertEqual(bytes(seen), want)


if __name__ == "__main__":
    unittest.main()
