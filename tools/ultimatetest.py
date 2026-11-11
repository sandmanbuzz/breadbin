#!/usr/bin/env python3
"""Drive a real Ultimate 64 (or C64 Ultimate) for the Breadbin tests.

Same interface as tools/vicetest.py's Vice, so a test can run on either:

    BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=192.168.1.64 \\
        python3 -m unittest tests.test_system.Boot.test_02_echo

    with UltimateTarget("build/breadbin.d64") as v:     # mounts, resets, boots
        v.wait_shell()
        print(v.run("echo hi"))

Two ways to type, as in Vice:
  type(text) / keybuf(bytes)   write PETSCII into the key buffer at $0277 by DMA
                               (what VICE's `keybuf` does; no key timing involved)
  xkey/xtype/xdown/xup         real key events through the Ultimate's keyboard
                               input (Ultimate 64 only), so the matrix scan runs

UNVERIFIED on hardware, to check first: that a "tap" is held long enough for the
60 Hz scan to see it; how DMA reads of $0001 behave; the upload encoding (see
tools/ultimate.py); the boot time. See docs/hardware-notes.md.
"""
import collections
import math
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ultimate import KeyInjectionUnavailable, Ultimate  # noqa: E402
from vicetest import Target  # noqa: E402

KEYD, KEYCNT, KEYMAX = 0x0277, 0x00C6, 0x0289

# Every REST memory access is a DMA that halts the 6510, and a halt inside a serial transfer
# corrupts or stalls it (docs/design/io-attack-log.md, session 2: 1000-byte reads every 0.5 s
# broke both the machine's JiffyDOS load and our driver). Breadbin's own driver handshakes every
# byte and tolerated 1-byte reads every 0.1 s (0 retries in 264 reads), but session 4 showed the
# machine's JiffyDOS load does not (below). So outside that load, screen reads and key-buffer
# writes happen only when the bus looks idle, judged from 1-byte reads of CIA 2 port A, and the
# gated read or key-buffer write follows the last idle sample at once (the arm G procedure, 8/8 clean).
CIA2_PA = 0xDD00
# An idle bus is ($DD00 & $F8) in an allowed set, and all IDLE_SAMPLES samples must show the SAME
# value (an idle bus reads the same every time; ($90, $C0, $90) is a Breadbin send's signature).
#  $C0: all lines released (Breadbin's idle, sessions 2-3). The only value accepted once Breadbin runs.
#  $90: bit 4 set, i.e. the C64 itself drives CLK (the line is low whoever else holds it), DATA and
#       ATN released: the KERNAL/JiffyDOS idle at BASIC (measured $97 at READY on hardware,
#       2026-11-10). Accepted ONLY while the machine's own KERNAL owns the bus, from boot()'s reset
#       until the `run` keystrokes are written: Breadbin's driver produces $90 during every 1-bit
#       setup of a send (~131 of ~224 cycles per 1-bit) and during the frame-ack wait, so with $90
#       accepted three samples inside a send of mostly-$FF data (the bitmap block, written on every
#       allocation) are likely (~0.7, against ~0.04 with $C0 only; hardware Boot class 29/30 twice
#       after 487a12b: a lost mkdir/cd, and one io_nretry).
BUS_MASK = 0xF8
BUS_IDLE_OWN = (0xC0,)
BUS_IDLE_KERNAL = (0xC0, 0x90)
IDLE_SAMPLES, IDLE_GAP = 3, 0.1   # all must look idle; no faster than one 1-byte read per 0.1 s
RACES = 3                         # races whose context TimeoutErrors keep
EVENTS = 24                       # gate events kept per context in TimeoutError messages

# The machine's own `load"*",8,1` (JiffyDOS KERNAL + JiffyDOS 1541) has bus-idle gaps of >= 0.2 s,
# so the idle gate above failed it 4 of 4 (?LOAD ERROR x3 and one silent 2-byte mismatch; hardware
# session 3, 2026-11-10, docs/design/io-trial-protocol.md and io-attack-log.md): a 1000-byte
# read lands as the next transfer starts.
# Session 4 (docs/design/io-attack-log.md on io/session1): even ONE 1-byte readmem of $D6 every
# 0.1 s silently corrupted the machine's JiffyDOS load on the first polled trial (5 bytes wrong
# from +788, load reported success). So while the machine's load can be running the harness makes
# NO request to the machine at all (no readmem, writemem, pause, resume, keybuf): boot() sleeps
# BOOT_QUIET after typing the load command, then wait_ready_quiet() makes ONE check (two 1-byte
# reads: $D6, then the first byte of the row above the cursor; only when that says "ready." are
# the rest read). If the machine is still loading, that check may itself have disturbed the load:
# LoadError at once, telling you to raise BREADBIN_ULTIMATE_LOAD_QUIET. Never poll into a load.
# A stock KERNAL load is slower (about 40-50 s): raise the quiet for it.
# The 20 s default stays until the drive-A boot load is measured on hardware: the ~8 s figure
# (a ~15 KB boot file) is the physical 1541's JiffyDOS load; the drive-A load time is unmeasured.
# verify_loaded() after READY is the guard: it reads the loaded range and the end pointer back and
# compares them with the disk bytes that were mounted, so a check that landed in a running load
# cannot go unnoticed. Every polling readmem goes through _dma_read(), no sooner than IDLE_GAP
# after the last; the gated read right after an idle verdict is not delayed.
#
# Residual risk, NOT accepted, partly visible: the gate cannot close the race with a transfer that
# starts after its last sample. Hardware Boot class, single 1000-byte gated screen reads, $C0-only
# after `run`: 4 runs (2 on 1b273dc, 2 on 4032d95), 16 idle verdicts with a busy verdict just
# before and just after (excluding the boot phase), 1 run ended with the machine stuck and the bus
# released ($C7) after one of them; that its read caused the hang is inferred, not proven.
# What is reported (stderr "gate race #N" or "gate key-write candidate #N" even with the gate log
# off; gate_races, gate_key_candidates; the events around the last ones in every TimeoutError): a
# gated screen read or key write (a failed request too, if the caller polls on: its DMA may have
# run) whose idle verdict began within RACE_WINDOW of the busy sample of the
# verdict before, and whose next verdict began within RACE_WINDOW of its end and is busy (a DMA in
# a short gap between transfers). RACE_WINDOW is 1.0 s because the waits poll every 0.4-0.5 s plus
# the requests' round trips: the gap between two verdicts is never shorter (with 0.5, measured
# this way, replaying the 2026-11-10/11 gate logs lost real races). A key write's next busy
# verdict may be the command it typed, so a key-write race is counted apart, as a candidate.
# NOT seen: a transfer that starts after a long quiet stretch, one that starts and ends between two
# verdicts, a DMA that kills a transfer so the bus reads idle at once, and the paced 1-byte probes,
# which go on every few tenths of a second through Breadbin's own transfers (1-byte reads were
# harmless to its reads, session 2 arm O, 264 reads; during its writes they are unmeasured).
# A clean default output is therefore no proof that the harness disturbed nothing.
# Splitting reads into short requests is not the answer (b563d13, reverted): the later pieces land
# up to a second after the verdict and the screen stops being a snapshot.
# The key buffer is written without machine:pause (a pause halted the machine across five HTTP
# requests): only into an empty buffer, the bytes first and the count last.
RACE_WINDOW = 1.0
BOOT_QUIET = 20.0
MAX_QUIET = 600.0
MIN_QUIET = 5.0          # below this a boot is refused (the quiet must cover the load)
END_PTR = 0x00AE         # KERNAL end-of-load pointer ($AE/$AF)

CURSOR_ROW, SCREEN, COLS = 0x00D6, 0x0400, 40
SC_READY = bytes([0x12, 0x05, 0x01, 0x04, 0x19, 0x2E])   # "ready." as screen codes
SC_QUESTION = 0x3F                                        # '?': a BASIC error line starts with it
SC_BREAK = bytes([0x02, 0x12, 0x05, 0x01, 0x0B])          # "break"
# what a DMA read shows at READY with the default memory map: RAM below $A000 and in $C000-$CFFF;
# BASIC ROM, I/O and KERNAL ROM elsewhere, so a read-back cannot check those bytes
CHECKABLE = ((0x0000, 0xA000), (0xC000, 0xD000))


class LoadError(RuntimeError):
    """The machine printed a BASIC error ('?...' or BREAK) while we waited, or the loaded bytes differ from the disk."""


# ASCII -> the keys to hold together (one tap) on a C64 keyboard
SHIFTED = {"!": "1", '"': "2", "#": "3", "$": "4", "%": "5", "&": "6", "'": "7", "(": "8",
           ")": "9", "<": "comma", ">": "period", "?": "slash", "[": "colon",
           "]": "semicolon", "|": "minus"}
PLAIN = {" ": "space", "\n": "return", "+": "plus", "-": "minus", ".": "period",
         ",": "comma", ":": "colon", ";": "semicolon", "=": "equals", "/": "slash",
         "*": "star", "@": "at", "\x08": "inst_del", "_": "arrow_left", "^": "arrow_up"}

# the X key names the keyboard tests use -> the keys to hold
XNAMES = {"Return": ["return"], "space": ["space"], "BackSpace": ["inst_del"],
          "Escape": ["run_stop"], "Tab": ["commodore"],
          "Shift_L": ["left_shift"], "Shift_R": ["right_shift"],
          "Control_L": ["ctrl"], "Control_R": ["ctrl"],
          "exclam": ["left_shift", "1"]}


def keys_for(ch):
    """The keys that type one ASCII character."""
    if ch in PLAIN:
        return [PLAIN[ch]]
    if ch in SHIFTED:
        return ["left_shift", SHIFTED[ch]]
    if ch.isdigit() or ("a" <= ch <= "z"):
        return [ch]
    if "A" <= ch <= "Z":
        return ["left_shift", ch.lower()]
    raise ValueError(f"no key for {ch!r}")


def petscii(ch):
    """The PETSCII code the keyboard driver produces for an ASCII character."""
    if ch == "\n":
        return 0x0D
    if ch == "\x08":
        return 0x14
    if ch == "|":
        return 0xDD
    if "a" <= ch <= "z":
        return ord(ch) - 0x20
    if "A" <= ch <= "Z":
        return ord(ch) + 0x80
    return ord(ch)


class _RealClock:
    sleep = staticmethod(time.sleep)
    monotonic = staticmethod(time.monotonic)
    time = staticmethod(time.monotonic)      # deadlines must not follow wall-clock steps


class UltimateTarget(Target):
    sees_cpu_port = False
    # screen_lines() outside a wait: how long to wait for an idle bus. Longer than any caller's own
    # wait (tests poll for 30-60 s through legitimately long disk IO), so theirs fires first
    gate_timeout = 120.0

    def __init__(self, image=None, host=None, password=None, persist=False,
                 settle=2, client=None, load_quiet=None,
                 clock=None, _min_quiet=MIN_QUIET):
        """Mount `image` in drive A and boot it. persist=False mounts it so that
        writes are not written back to the file on the Ultimate ("unlinked").
        clock and _min_quiet are for the host tests only (a fake clock; a quiet below the floor)."""
        self._clock = clock or _RealClock()
        self.u = client or (Ultimate(host, password=password) if host else Ultimate.from_env())
        q = load_quiet if load_quiet is not None else os.environ.get("BREADBIN_ULTIMATE_LOAD_QUIET", BOOT_QUIET)
        try:
            q = float(q)
        except ValueError:
            raise ValueError(f"BREADBIN_ULTIMATE_LOAD_QUIET / load_quiet must be a number, not {q!r}") from None
        if not math.isfinite(q) or q < _min_quiet or q > MAX_QUIET:
            raise ValueError(f"load quiet {q!r} s refused: it must be a finite number of at least "
                             f"{_min_quiet} s and at most {MAX_QUIET:g} s (the machine's load must finish undisturbed)")
        self.load_quiet = q
        self.settle = settle
        self._gatelog = os.environ.get("BREADBIN_ULTIMATE_GATELOG") == "1"   # every gate verdict to stderr
        if image:
            self.boot(image, persist)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def close(self):
        try:
            self.u.release_all()
        except Exception:
            pass

    # ---- clock hooks the waits in vicetest.Target use
    def _time(self):
        return self._clock.time()

    def _pause(self, seconds):
        self._clock.sleep(seconds)

    # ---- the interface Target needs
    def mem(self, start, end):
        return list(self._dma_read(start, end - start + 1))

    _after_gate = False
    _bus_idle_values = BUS_IDLE_OWN      # boot() widens it while the machine's KERNAL owns the bus
    _gatelog = False
    gate_races = 0                       # gated reads that landed between two busy verdicts
    gate_key_candidates = 0              # key writes that did (the busy after may be the command)
    _last_busy = None                    # time of the busy sample of the last busy verdict
    _suspect = None                      # (description, end time) of a gated DMA right after a busy verdict
    _events = None
    _races = None                        # the event history up to each of the last RACES races

    def _event(self, text):
        """Remember a gate event (the last EVENTS go into TimeoutErrors); print it with the gate log."""
        if self._events is None:
            self._events = collections.deque(maxlen=EVENTS)
        self._events.append(text)
        if self._gatelog:
            print("gate " + text, file=sys.stderr)

    def _recent(self):
        out = "recent gate events (oldest first):\n  " + "\n  ".join(self._events or ["none"])
        for ctx in self._races or ():
            out += "\nevents up to " + ctx[-1].split(":")[0].split(" (")[0] + ":\n  " + "\n  ".join(ctx)
        return out

    def bus_idle(self):
        """True if the serial bus looked idle in IDLE_SAMPLES 1-byte reads, IDLE_GAP apart: every
        sample the same value, and one of the idle values of the current phase (see BUS_IDLE_OWN
        and BUS_IDLE_KERNAL). A transfer can still begin right after; this keeps big reads out of
        the transfers that are under way, which is what broke on 2026-11-07. After a True the next
        read is not delayed (the gated read follows the last sample at once, as in the 8/8 arm)."""
        self._after_gate = False
        raw, when = [], []
        for _ in range(IDLE_SAMPLES):
            raw.append(self._read1(CIA2_PA))
            when.append(self._clock.monotonic())
            if raw[-1] & BUS_MASK not in self._bus_idle_values:
                break
        idle = (len(raw) == IDLE_SAMPLES and len({v & BUS_MASK for v in raw}) == 1)
        self._event(("idle" if idle else "busy") + " raw=" + ",".join(f"${v:02X}" for v in raw)
                    + " t=" + ",".join(f"{t:.3f}" for t in when))
        if self._suspect:
            what, end = self._suspect
            self._suspect = None
            if not idle and when[0] - end <= RACE_WINDOW:
                bad = next((v for v in raw if v & BUS_MASK not in self._bus_idle_values), None)
                why = (f"the busy sample ${bad:02X}" if bad is not None else
                       "samples " + ",".join(f"${v:02X}" for v in raw) + " differ")
                if what.startswith("key write"):
                    self.gate_key_candidates += 1
                    head = (f"key-write candidate #{self.gate_key_candidates} (the busy verdict "
                            "may be the typed command's own I/O)")
                else:
                    self.gate_races += 1
                    head = f"race #{self.gate_races}"
                msg = (f"{head}: {what} landed between busy verdicts "
                       f"(busy again {when[0] - end:.2f} s after it, {why})")
                self._event(msg)
                if self._races is None:
                    self._races = collections.deque(maxlen=RACES)
                self._races.append(list(self._events))
                if not self._gatelog:
                    print("ultimatetest: gate " + msg, file=sys.stderr)
        if not idle:
            self._last_busy = when[-1]       # the sample that made it busy (the loop stops there)
        self._verdict_t = when[0]
        self._after_gate = idle
        return idle

    def _gated_dma_done(self, what):
        """A gated DMA just ended: suspect it if the verdict before it was close to a busy one."""
        if self._last_busy is not None and self._verdict_t - self._last_busy <= RACE_WINDOW:
            self._suspect = (what, self._last_read)

    _last_read = 0.0

    def _dma_read(self, address, length):
        """Every REST readmem goes through here: no sooner than IDLE_GAP after the previous one,
        except the read that directly follows an idle verdict. One request, one snapshot."""
        gated = self._after_gate
        if gated:
            self._after_gate = False
        else:
            wait = self._last_read + IDLE_GAP - self._clock.monotonic()
            if wait > 0:
                self._clock.sleep(wait)
        start = self._clock.monotonic()
        ok = False
        try:
            data = self.u.readmem(address, length)
            ok = True
            return data
        finally:
            self._last_read = self._clock.monotonic()
            self._event(f"{'read' if gated else 'paced read'} ${address:04X} len {length} "
                        f"t={start:.3f}-{self._last_read:.3f}" + ("" if ok else " FAILED"))
            if gated and length > 1:             # a 1-byte read (keybuf's count) is the harmless kind
                self._gated_dma_done(f"read ${address:04X} len {length}" + ("" if ok else " (failed)"))

    def _read1(self, address):
        return self._dma_read(address, 1)[0]

    def _is_error_row(self, at):
        """True if the screen row starting at `at` begins with '?' or "break" (1-byte reads)."""
        b = self._read1(at)
        if b == SC_QUESTION:
            return True
        return b == SC_BREAK[0] and all(self._read1(at + 1 + i) == c for i, c in enumerate(SC_BREAK[1:]))

    def _ready_step(self):
        """One check of the screen by 1-byte reads: "busy" (the line above the cursor is not
        ready.), "ready" (ready. confirmed, cursor still, no error line above it) or "other"
        (not usable this time). Raises LoadError on an error line."""
        row = self._read1(CURSOR_ROW)
        if not 1 <= row <= 24:
            return "other"
        at = SCREEN + COLS * (row - 1)
        b = self._read1(at)
        if b != SC_READY[0]:
            if b in (SC_QUESTION, SC_BREAK[0]) and self._is_error_row(at):
                raise LoadError(f"error line above the cursor (row {row - 1})")
            return "busy"
        if any(self._read1(at + 1 + i) != c for i, c in enumerate(SC_READY[1:])):
            return "other"
        if self._read1(CURSOR_ROW) != row:
            return "other"
        if row >= 2 and self._is_error_row(at - COLS):
            raise LoadError(f"error line above READY. (row {row - 2})")
        return "ready"

    def wait_ready_quiet(self, quiet):
        """Wait for the machine's load to finish with NO request to the machine for `quiet`
        seconds, then ONE check (see the note at BOOT_QUIET). Call right after the load command
        was typed. "ready." -> return. Anything else -> LoadError at once, the message saying
        whether the machine looked busy (still loading) or the screen was unreadable: the check
        itself may have disturbed a running load, and polling on would only make that worse.
        Also LoadError for an error line. A "ready." from before the command cannot pass for the
        result: after a quiet interval the command has long been consumed."""
        self._clock.sleep(quiet)
        state = self._ready_step()
        if state == "ready":
            return
        what = ("the load was still running" if state == "busy"
                else "the screen was not readable as ready. (cursor row or text unexpected)")
        raise LoadError(f"{what} after {quiet:g} s of quiet (one check); the check itself may have "
                        f"disturbed it. Raise BREADBIN_ULTIMATE_LOAD_QUIET")

    _last_screen = [""] * 25
    _last_fresh = None       # time.monotonic() of the last screen read that actually happened
    _skipped = 0             # screen polls the bus gate refused
    _wait_depth = 0
    _wait_skipped0 = 0
    _fresh_in_wait = False

    def screen_lines(self, gate_timeout=None):
        """The screen, read only when the bus is idle, the read straight after the idle verdict.
        Inside a wait (wait_for, wait_shell, run) one attempt per poll: if the gate is shut, a
        blank screen until the wait has had one fresh read, so a screen read before the wait cannot
        satisfy it. Outside a wait (tests that poll screen_lines() themselves, or look once) a stale
        screen would be silently wrong, so this waits for the gate up to gate_timeout (this call's
        argument, else the class default) and then raises TimeoutError, never a stale screen."""
        limit = self.gate_timeout if gate_timeout is None else gate_timeout
        if self._wait_depth:
            if not self.bus_idle():
                self._skipped += 1
                return self._last_screen if self._fresh_in_wait else [""] * 25
        else:
            deadline = self._clock.time() + limit
            while not self.bus_idle():
                self._skipped += 1
                if self._clock.time() >= deadline:
                    raise TimeoutError(f"serial bus never idle for a screen read in {limit:g} s "
                                       f"(last fresh read {self._age()})\n" + self._recent())
        self._last_screen = super().screen_lines()
        self._last_fresh = self._clock.monotonic()
        self._fresh_in_wait = True
        return self._last_screen

    def _age(self):
        return "never" if self._last_fresh is None else f"{self._clock.monotonic() - self._last_fresh:.1f} s ago"

    def _stale_note(self):
        return (f"[screen stale: last fresh read {self._age()}; the bus gate skipped "
                f"{self._skipped - self._wait_skipped0} polls in this wait; "
                f"{self.gate_races} gate races and {self.gate_key_candidates} key-write candidates so far]\n" + self._recent())

    def _in_wait(self, fn, *args, **kw):
        if self._wait_depth == 0:
            self._fresh_in_wait = False
            self._wait_skipped0 = self._skipped
        self._wait_depth += 1
        try:
            return fn(*args, **kw)
        except TimeoutError as e:
            if self._wait_depth > 1:        # the outermost wait adds the note, once
                raise
            note = self._stale_note()
            if "recent gate events" in str(e):   # the inner error already carries the history
                note = note.split("\nrecent gate events")[0]
            raise TimeoutError(f"{e}\n{note}") from None
        finally:
            self._wait_depth -= 1

    def wait_for(self, *a, **k):
        return self._in_wait(super().wait_for, *a, **k)

    def wait_shell(self, *a, **k):
        return self._in_wait(super().wait_shell, *a, **k)

    def _wait(self, *a, **k):
        return self._in_wait(super()._wait, *a, **k)

    def keybuf(self, data, timeout=30):
        """PETSCII bytes (1 to 10, what the buffer holds) into the key
        buffer, once it is EMPTY and the bus is idle. No machine:pause (a pause halts the machine
        for several HTTP requests): with the buffer empty the consumer (key_get, the KERNAL's
        GETIN) has nothing to take, and only a real keypress could add a key, so writing the
        bytes first and the count last is safe. Three short DMAs, the first straight after the
        idle verdict. Unlike VICE's keybuf this waits for an EMPTY buffer: keys typed ahead of a
        program that never reads the keyboard time out instead of queueing behind it."""
        data = bytes(data)
        if not 0 < len(data) <= 10:
            raise ValueError(f"keybuf takes 1 to 10 bytes, not {len(data)}")
        deadline = self._clock.time() + timeout
        while True:
            if not self.bus_idle():
                if self._clock.time() > deadline:
                    raise TimeoutError("serial bus never idle for the key buffer\n" + self._recent())
                continue                     # the next bus_idle() read is paced by _dma_read
            n = self._dma_read(KEYCNT, 1)[0]  # straight after the idle verdict
            if n == 0:
                t0 = self._clock.monotonic()
                ok = False
                try:
                    self.u.writemem(KEYD, data)
                    self.u.writemem(KEYCNT, bytes([len(data)]))
                    ok = True
                finally:
                    self._last_read = self._clock.monotonic()
                    self._event(f"keys len {len(data)} t={t0:.3f}-{self._last_read:.3f}" + ("" if ok else " FAILED"))
                    self._gated_dma_done(f"key write len {len(data)}" + ("" if ok else " (failed)"))
                return
            if self._clock.time() > deadline:
                raise TimeoutError("key buffer never drained\n" + self._recent())
            self._clock.sleep(0.1)

    def verify_loaded(self, disk, timeout=30):
        """Read back what the machine's load put in RAM and compare it with the first PRG in `disk`
        (the .d64 bytes boot() mounted), which is what `load"*",8,1` loads: its first two bytes
        are the load address. The KERNAL end pointer ($AE/$AF) must equal load address + length
        (a short load over stale RAM would otherwise match). Raises LoadError (first differing
        offset and the count; or the pointer), TimeoutError if the bus is never idle. Every read
        waits for an idle bus and follows the verdict at once. Bytes the CPU sees as ROM or I/O at
        READY ($A000-$BFFF, $D000-$FFFF) cannot be checked and are skipped."""
        import mkimage
        img = mkimage.Image(disk)
        prg = img.cbm_read(img.cbm_files()[0][0])
        base, payload = prg[0] | prg[1] << 8, prg[2:]

        def gated(address, length):
            deadline = self._clock.time() + timeout
            while not self.bus_idle():
                if self._clock.time() > deadline:
                    raise TimeoutError("serial bus never idle for the read-back\n" + self._recent())
            return self._dma_read(address, length)

        end = base + len(payload)
        ptr = gated(END_PTR, 2)
        got_end = ptr[0] | ptr[1] << 8
        print(f"verify_loaded: end pointer $AE/$AF = ${got_end:04X}, expected ${end:04X} "
              f"({len(payload)} bytes at ${base:04X})", file=sys.stderr)
        if got_end != end:
            raise LoadError(f"end pointer $AE/$AF is ${got_end:04X}, the disk's file ends at ${end:04X} "
                            f"({len(payload)} bytes at ${base:04X}): short or missing load")
        bad, first = 0, None
        for lo, hi in CHECKABLE:
            start, stop = max(lo, base), min(hi, end)
            pos = start
            while pos < stop:
                n = min(stop - pos, 4096)
                got = gated(pos, n)
                want = payload[pos - base:pos - base + n]
                for i, (g, w) in enumerate(zip(got, want)):
                    if g != w:
                        bad += 1
                        if first is None:
                            first = pos - base + i
                pos += n
        if bad:
            raise LoadError(f"loaded bytes differ from the disk: {bad} bytes differ, first at offset "
                            f"{first} (${base + first:04X}) of {len(payload)} loaded at ${base:04X}")

    def type(self, text):
        """Like Vice.type: ASCII text into the key buffer, a few keys at a time."""
        codes = bytes(petscii(c) for c in text)
        for i in range(0, len(codes), 8):
            self.keybuf(codes[i:i + 8])

    # ---- real keystrokes
    def focus(self):
        """Nothing to focus; but real keystrokes must exist on this product."""
        try:
            self.u.release_all()
        except KeyInjectionUnavailable as e:
            raise unittest.SkipTest(str(e))

    def _keys(self, name):
        return XNAMES[name] if name in XNAMES else keys_for(name)

    def xkey(self, *names, delay=0.15):
        for name in names:
            self.u.keyboard(self._keys(name), "tap")
            time.sleep(delay)

    def xtype(self, text, delay=0.15):
        for ch in text:
            self.u.keyboard(keys_for(ch), "tap")
            time.sleep(delay)

    def xdown(self, name):
        self.u.keyboard(self._keys(name), "press")

    def xup(self, name):
        self.u.keyboard(self._keys(name), "release")

    # ---- booting
    def boot(self, image, persist=False):
        with open(image, "rb") as f:
            data = f.read()
        self.u.mount("a", data, type="d64", mode="readwrite" if persist else "unlinked",
                     name=os.path.basename(image))
        self._bus_idle_values = BUS_IDLE_KERNAL   # the machine's KERNAL owns the bus until `run`
        # a new boot starts a new race history: an older test's races would read as this one's
        self.gate_races, self.gate_key_candidates = 0, 0
        self._races, self._suspect, self._last_busy = None, None, None
        try:
            self.u.resume()          # a reset leaves a paused machine paused (seen on hardware)
            self.u.reset()
            self._clock.sleep(self.settle)  # let the old screen go before waiting for the new one
            self.wait_for("ready.", timeout=60)
            # the bus of drive A on the Ultimate: 8 unless BREADBIN_ULTIMATE_BUS says otherwise (a bench with the
            # physical 1541 on bus 8 runs drive A on bus 9, so the load must name 9)
            bus = int(os.environ.get("BREADBIN_ULTIMATE_BUS", "8"))
            self.type(f'load"*",{bus},1\n')
            self.wait_ready_quiet(self.load_quiet)   # no DMA at all while the load runs; one check
            self.verify_loaded(data)                 # the guard if that check landed in the load
            self.type("run\n")
        finally:
            # Breadbin runs now, or the boot failed and what runs is unknown: $C0 only either way
            # (the narrow set can only refuse a read, never let one into a Breadbin send)
            self._bus_idle_values = BUS_IDLE_OWN


if __name__ == "__main__":
    img = sys.argv[1] if len(sys.argv) > 1 else "build/breadbin.d64"
    with UltimateTarget(img) as v:
        v.wait_shell()
        print(v.screen())
