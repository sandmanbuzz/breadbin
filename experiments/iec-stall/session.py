#!/usr/bin/env python3
"""Hardware trial runner for the IO attack, session 1 (docs/design/io-trial-protocol.md).

Runs a pre-registered plan against the Ultimate and the physical 1541, one TSV row per trial,
each row flushed and fsynced the moment the trial ends.

    BREADBIN_ULTIMATE=<set> tools/with-lock -r ultimate -- python3 experiments/iec-stall/session.py \\
        PLAN --image build/breadbin.prg --d64 build/breadbin.d64 --out RESULTS.tsv \\
        --disk-id ID --control-file NAME [--commit DESCRIBE] [--drive-on-minutes-ago N]
    session.py PLAN ... --dry-run        # prints the trial order and the hand actions; no network

Plan file: one entry per line, `BLOCK ARMS COUNT` (`#` starts a comment), e.g.

    1 C 12
    2 KBD 10        # ARMS is a cycle: K, B, D, K, B, D ... COUNT times through the cycle
    3 C 6

or JSON: a list of [block, arms, count] (or {"block":..,"arms":..,"count":..}).

Arms: C control (KERNAL load of a non-Breadbin file), K kernal-load of the Breadbin boot file
(byte compare), B boot (load, run, login, IOSTAT), D DMA kernel + root mount (plainboot logic).

The DMA rule (README): no screen-sized read while a disk transfer may be in progress. Every wait
below reads nothing for FIRST_READ seconds after a transfer starts, then one screen read per POLL
seconds (plainboot.py: 20 s and 10 s). bench_basic/plainboot cannot be imported (they read
BREADBIN_ULTIMATE and run at import), so their few lines are repeated here.

Exit status: 0 plan finished, 3 stopped (mechanical symptom, `stop`, Ctrl-C, signal), 2 usage.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import signal
import sys
import time
import urllib.parse
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

ARMS = "CKBD"
LIMITS = {"C": 120, "K": 120, "B": 150, "D": 170}      # seconds, protocol
FIRST_READ = 20           # no DMA read this long after a transfer starts (plainboot)
POLL = 10                 # then one screen read per this many seconds
BYTE_FIRST = 2            # --poll-mode byte, KERNAL load: first 1-byte read this long after the command
BYTE_EVERY = 2            # and at most one 1-byte read per this many seconds
SETTLE = 6                # after a reset, before the first read (stockload)
ARM_FAIL_LIMIT = 5
WEDGE_LIMIT = 3
COLUMNS = ["session", "block", "trial", "arm", "start_iso", "min_session", "min_drive_on",
           "image_sha", "commit", "disk_id", "outcome", "seconds", "io_nread", "io_nretry",
           "io_nfail", "io_neoi", "io_last", "detail", "dump", "note"]
IO_COUNTERS = ["io_nread", "io_nretry", "io_nfail", "io_neoi"]

# Protocol configuration: (category, item, value to set, normal value to fall back on at restore).
# Kernal ROM stays JiffyDOS (not touched: a change needs a reboot). Names are from cabletest.sh and
# ucirun.sh; "Drive Bus ID" is UNVERIFIED against the firmware, as is the GET reply shape.
CONFIG = [
    ("SoftIEC Drive Settings", "IEC Drive", "Disabled", "Enabled"),
    ("Drive A Settings", "Drive", "Enabled", "Enabled"),
    ("Drive A Settings", "Drive Bus ID", "9", "9"),
    ("C64 and Cartridge Settings", "DMA Load Mimics ID:", "8", "8"),
]
READBACK_ONLY = [("C64 and Cartridge Settings", "Kernal ROM")]


class StopSession(Exception):
    """The session stops now (mechanical symptom, `stop`, Ctrl-C, signal)."""


class Clock:
    def now(self):
        return time.monotonic()

    def sleep(self, s):
        if s > 0:
            time.sleep(s)


# ---------------------------------------------------------------- plan
def parse_plan(text):
    """-> [(block, arms, count)] in file order."""
    text = text.strip()
    out = []
    if text.startswith("["):
        for e in json.loads(text):
            if isinstance(e, dict):
                e = [e["block"], e["arms"], e["count"]]
            out.append((int(e[0]), str(e[1]).upper(), int(e[2])))
    else:
        for n, line in enumerate(text.splitlines(), 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            f = line.split()
            if len(f) != 3:
                raise ValueError(f"plan line {n}: want BLOCK ARMS COUNT, got {line!r}")
            out.append((int(f[0]), f[1].upper(), int(f[2])))
    for block, arms, count in out:
        if not arms or any(a not in ARMS for a in arms) or count < 1 or block < 0:
            raise ValueError(f"bad plan entry block={block} arms={arms!r} count={count}")
    return out


def expand(plan):
    """-> [(block, trial_index, arm)], trial index counted over the whole session from 1."""
    order = []
    for block, arms, count in plan:
        for _ in range(count):
            for a in arms:
                order.append((block, len(order) + 1, a))
    return order


def disk_kind(arm):
    return "control" if arm == "C" else "breadbin"


def hand_prompt(kind, disk_id):
    if kind == "control":
        return "insert the control disk in device 8, write-protected, then press Enter"
    return f"insert the Breadbin disk ({disk_id}) in device 8, then press Enter"


def dry_run(order, disk_id, out=print):
    kind = None
    for block, idx, arm in order:
        if disk_kind(arm) != kind:
            kind = disk_kind(arm)
            out(f"HAND  {hand_prompt(kind, disk_id)}")
        out(f"block {block}  trial {idx:3d}  arm {arm}  limit {LIMITS[arm]} s")
    out(f"{len(order)} trials; worst case {sum(LIMITS[a] for _, _, a in order) // 60} min if all time out")


# ---------------------------------------------------------------- d64, labels, screen
def d64_first_prg(data):
    """The file `load"*",8,1` would load: first closed PRG in the directory. -> (name, bytes) or None."""
    def off(t, s):
        if not 1 <= t <= 35:
            raise ValueError(f"bad track {t}")
        per = 21 if t <= 17 else 19 if t <= 24 else 18 if t <= 30 else 17
        return (sum(21 if x <= 17 else 19 if x <= 24 else 18 if x <= 30 else 17 for x in range(1, t))
                + s) * 256 if s < per else None

    t, s, seen = 18, 1, set()
    while t and (t, s) not in seen:
        seen.add((t, s))
        o = off(t, s)
        sec = data[o:o + 256]
        for i in range(8):
            e = sec[i * 32:(i + 1) * 32]
            if len(e) == 32 and e[2] & 0x87 == 0x82:
                name = e[5:21].rstrip(b"\xa0").decode("latin-1")
                body, bt, bs, hops = b"", e[3], e[4], 0
                while bt and hops < 800:
                    o2 = off(bt, bs)
                    blk = data[o2:o2 + 256]
                    if blk[0]:
                        body += blk[2:]
                        bt, bs = blk[0], blk[1]
                    else:
                        body += blk[2:blk[1] + 1]
                        bt = 0
                    hops += 1
                return name, body
        t, s = sec[0], sec[1]
    return None


def read_labels(path):
    """ld65 -Ln output (`al 00C123 .name`) -> {name: address}; {} if the file is absent."""
    try:
        with open(path) as f:
            return {m.group(2): int(m.group(1), 16) for l in f
                    for m in [re.match(r"al ([0-9A-F]{6}) \.(\S+)", l)] if m}
    except OSError:
        return {}


def label_width(labels, name, cap=4):
    """Bytes a label covers, guessed as the gap to the next label (at most `cap`)."""
    a = labels[name]
    later = [v for v in labels.values() if v > a]
    return max(1, min(cap, (min(later) - a) if later else 1))


def screen_lines(raw):
    """1000 screen codes -> the non-empty rows, lower case (plainboot.py's mapping)."""
    rows = ("".join(chr(c + 64) if 1 <= c <= 26 else chr(c) if 32 <= c < 64 else " "
                    for c in raw[r * 40:(r + 1) * 40]).rstrip().lower() for r in range(25))
    return [l for l in rows if l]


def classify_load(lines):
    """-> 'load_error', 'other_error', 'loaded' or None (still going)."""
    for l in lines:
        if l.startswith("?load") or "load error" in l:
            return "load_error"
        if l.startswith("?") and "error" in l:
            return "other_error"
    echo = [i for i, l in enumerate(lines) if l.startswith('load"')]
    if echo and lines[-1].strip() == "ready." and len(lines) - 1 - echo[-1] >= 2:
        return "loaded"
    return None


def classify_boot(lines):
    if any("login:" in l for l in lines):
        return "login"
    if any("panic" in l for l in lines):
        return "panic"
    return None


def clean(v):
    return re.sub(r"[\t\r\n]+", " ", str(v))


# ---------------------------------------------------------------- results file
class Results:
    def __init__(self, path):
        self.path = path
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        self.f = open(path, "a")
        self.new = new

    def raw(self, line):
        self.f.write(line + "\n")
        self.f.flush()
        os.fsync(self.f.fileno())

    def comment(self, text):
        for l in str(text).splitlines() or [""]:
            self.raw("# " + l)

    def header(self):
        if self.new:
            self.raw("\t".join(COLUMNS))
            self.new = False

    def row(self, **kw):
        self.header()
        self.raw("\t".join(clean(kw.get(c, "")) for c in COLUMNS))

    def close(self):
        self.f.close()


# ---------------------------------------------------------------- configuration
def quote_cfg(cat, item):
    return "/v1/configs/" + urllib.parse.quote(cat, safe="") + "/" + urllib.parse.quote(item, safe="")


def config_value(reply, cat, item):
    node = reply.get(cat, reply)
    node = node.get(item, node) if isinstance(node, dict) else node
    if isinstance(node, dict):
        node = node.get("current", node.get("value"))
    return None if node is None or isinstance(node, (dict, list)) else str(node)


class ConfigGuard:
    """Sets the protocol configuration, reads it back, restores what it found. restore() is
    idempotent and never raises, so try/finally and the signal path can both call it."""

    def __init__(self, u, clock, log, reboot_wait=15, extra=()):
        self.u, self.clock, self.log, self.reboot_wait = u, clock, log, reboot_wait
        self.items = list(CONFIG) + [(c, i, v, None) for c, i, v in extra]
        self.original = {}
        self.applied = False
        self.restored = False

    def get(self, cat, item):
        try:
            return config_value(self.u.call("GET", quote_cfg(cat, item)), cat, item)
        except Exception as e:           # noqa: BLE001 - a read-back must not stop the run
            return f"<unreadable: {clean(e)[:60]}>"

    def put(self, cat, item, value):
        self.u.call("PUT", quote_cfg(cat, item), {"value": value})

    def readback(self):
        keys = [(c, i) for c, i, _, _ in self.items] + READBACK_ONLY
        return {f"{c}/{i}": self.get(c, i) for c, i in keys}

    def apply(self):
        self.log.comment("config before: " + json.dumps(self.readback(), sort_keys=True))
        for c, i, v, _ in self.items:
            self.original[(c, i)] = self.get(c, i)
        self.applied = True               # from here a restore is owed, even if a PUT fails
        for c, i, v, _ in self.items:
            self.put(c, i, v)
        self.u.reboot()
        self.clock.sleep(self.reboot_wait)
        rb = self.readback()
        self.log.comment("config set, read back: " + json.dumps(rb, sort_keys=True))
        print("config read-back:", json.dumps(rb, sort_keys=True), flush=True)

    def restore(self):
        if not self.applied or self.restored:
            return
        self.restored = True
        for c, i, _, normal in self.items:
            orig = self.original.get((c, i))
            val = orig if orig is not None and not orig.startswith("<") else normal
            if val is None:
                continue
            try:
                self.put(c, i, val)
            except Exception as e:       # noqa: BLE001
                print(f"RESTORE FAILED {c}/{i}: {e}", file=sys.stderr, flush=True)
        try:
            self.u.resume()
            self.u.reboot()
            self.clock.sleep(self.reboot_wait)
        except Exception as e:           # noqa: BLE001
            print(f"RESTORE reboot failed: {e}", file=sys.stderr, flush=True)
        rb = self.readback()
        try:
            self.log.comment("config after restore: " + json.dumps(rb, sort_keys=True))
        except Exception:                # noqa: BLE001
            pass
        print("config after restore:", json.dumps(rb, sort_keys=True), flush=True)


# ---------------------------------------------------------------- the machine
class Rig:
    """Everything that touches the Ultimate for one trial."""

    def __init__(self, u, clock, image, labels, control_file, first_read=FIRST_READ, poll=POLL,
                 settle=SETTLE, limits=None, poll_mode="none"):
        self.u, self.clock = u, clock
        self.poll_mode = poll_mode
        self.r0 = 0                  # cursor row ($D6) read on the idle bus before the load command
        self.prg = image
        self.addr, self.body = image[0] | image[1] << 8, image[2:]
        self.labels = labels
        self.control_file = control_file
        self.first_read, self.poll, self.settle = first_read, poll, settle
        self.limits = dict(LIMITS, **(limits or {}))
        self.control_ref = None      # (length, crc32) of the first passing C load
        self.last_lines = []
        self.sidecar = []            # decode.py-format stall lines for the caller to write

    # -- small helpers
    def screen(self):
        self.last_lines = screen_lines(self.u.readmem(0x0400, 1000))
        return self.last_lines

    def feed(self, text, timeout=20):
        """ASCII to PETSCII into the key buffer, 8 keys at a time (bench_basic.feed)."""
        codes = [0x0D if c == "\n" else (ord(c.upper()) if c.isalpha() else ord(c)) for c in text]
        for i in range(0, len(codes), 8):
            chunk = bytes(codes[i:i + 8])
            t_end = self.clock.now() + timeout
            while True:
                self.u.pause()
                if self.u.readmem(0xC6, 1)[0] == 0:
                    self.u.writemem(0x0277, chunk)
                    self.u.writemem(0xC6, bytes([len(chunk)]))
                    self.u.resume()
                    break
                self.u.resume()
                if self.clock.now() > t_end:
                    raise TimeoutError("key buffer never drained")
                self.clock.sleep(0.05)

    def reset(self):
        self.u.resume()          # a reset leaves a paused machine paused
        self.u.reset()
        self.clock.sleep(self.settle)

    def feed_raw(self, data, check=True):
        """Bytes into the key buffer. check=False writes blind: no readmem at all."""
        self.u.pause()
        try:
            if check and self.u.readmem(0xC6, 1)[0] != 0:
                raise TimeoutError("key buffer not empty")
            self.u.writemem(0x0277, bytes(data))
            self.u.writemem(0xC6, bytes([len(data)]))
        finally:
            self.u.resume()

    def wait(self, t_from, t_end, classify, kind):
        """Wait for a terminal screen state, touching the machine as little as the poll mode allows.

        none: no readmem at all until t_end; then ONE screen read, classified.
        byte: one 1-byte readmem of $D6 (the cursor row) at most every BYTE_EVERY s; the screen is read
              in full only after that byte signals a terminal state, or at t_end.
          kind "load" (KERNAL LOAD, polling from t_from + BYTE_FIRST): the KERNAL prints SEARCHING,
              LOADING and READY. one line each, so the cursor row sits at r0+4 (r0 = the command's row,
              read before the command) only once READY. is printed; nothing before that can trigger.
          kind "boot" (Breadbin running or booting; polling starts FIRST_READ s in, like plainboot,
              so the root mount is not touched): the console may not keep $D6, so any change of $D6
              from its first value is taken as activity; if it never changes, the read at t_end
              decides. Returns the classifier's state or None (timeout).
        Never reads more than 1 byte before a terminal state or t_end."""
        if self.poll_mode == "none":
            self.clock.sleep(t_end - self.clock.now())
            return classify(self.screen())
        self.clock.sleep(t_from + (BYTE_FIRST if kind == "load" else self.first_read) - self.clock.now())
        base = None if kind == "boot" else self.r0
        fired = None
        while True:
            b = self.u.readmem(0xD6, 1)[0]
            if kind == "load":
                trig = b >= self.r0 + 4 and b != fired
            else:
                trig = base is not None and b != base
                base = b if base is None else base
            if trig:
                fired = b
                if kind == "boot":
                    base = b
                st = classify(self.screen())
                if st:
                    return st
            left = t_end - self.clock.now()
            if left <= 0:
                return classify(self.screen()) if not trig else None
            self.clock.sleep(min(BYTE_EVERY, left))

    def iostat(self):
        """Counter and last-event labels, read with short reads; blank where a label is absent."""
        out = {}
        for n in IO_COUNTERS:
            if n in self.labels:
                try:
                    w = label_width(self.labels, n)
                    out[n] = int.from_bytes(self.u.readmem(self.labels[n], w), "little")
                except Exception:        # noqa: BLE001
                    out[n] = ""
        last = []
        for n in sorted(k for k in self.labels if k.startswith("io_last")):
            try:
                w = label_width(self.labels, n, cap=2)
                last.append(f"{n}={self.u.readmem(self.labels[n], w).hex()}")
            except Exception:            # noqa: BLE001
                pass
        out["io_last"] = ";".join(last)
        return out

    def stall_dump(self, boot_phase):
        """Short reads only (dmaboot.py): $90, $BA, $DD00, and in the boot phase the IEC variables
        and the stack, which go to the sidecar in decode.py's format."""
        d = {}
        for n, a in (("st", 0x90), ("ba", 0xBA), ("dd00", 0xDD00)):
            try:
                d[n] = self.u.readmem(a, 1)[0]
            except Exception:            # noqa: BLE001
                d[n] = None
        txt = " ".join(f"{k}={'??' if v is None else format(v, '02x')}" for k, v in d.items())
        if boot_phase and "io_out" in self.labels:
            try:
                base = self.labels["io_out"]
                names = ("io_out io_base io_b io_n io_to io_pend io_held io_eoi io_inf io_sx io_sy "
                         "ie_dev ie_sa ie_len ie_len2").split()
                if self.labels.get("io_n") == base + 3 and self.labels.get("ie_dev") == base + 11:
                    v = self.u.readmem(base, 15)
                    stack = self.u.readmem(0x1C0, 64).hex()
                    self.sidecar.append(str({n: f"{b:02x}" for n, b in zip(names, v)})
                                        + " stack:" + stack)
                    txt += " iovars=" + v.hex()
                else:
                    txt += " iovars=layout-changed"
            except Exception:            # noqa: BLE001
                pass
        last = self.last_lines[-1] if self.last_lines else ""
        return txt + f" last={last!r}", d

    # -- arms
    def trial(self, arm):
        """-> dict(outcome, seconds, detail, dump, timed_out, iostat)."""
        self.sidecar = []
        self.last_lines = []
        res = dict(outcome="other", detail="", dump="", timed_out=False, iostat={})
        t0 = self.clock.now()
        if arm == "D":
            self._arm_d(res)
            return self._done(res, t0)
        self.reset()
        for _ in range(2):               # idle bus here: a screen read is safe
            if self.screen()[-1:] == ["ready."]:
                break
            self.clock.sleep(10)
        else:
            res.update(outcome="other", detail="no READY. after reset")
            return self._done(res, t0)
        self.r0 = self.u.readmem(0xD6, 1)[0]
        t0 = self.clock.now()
        self._arm_load(arm, res, t0)
        return self._done(res, t0)

    def _done(self, res, t0):
        res["seconds"] = round(self.clock.now() - t0, 1)
        return res

    def _arm_load(self, arm, res, t0):
        limit = self.limits[arm]
        if arm == "B" and self.poll_mode == "none":
            self._arm_b_blind(res)
            return
        cmd = f'load"{self.control_file}",8\n' if arm == "C" else 'load"*",8,1\n'
        self.feed(cmd)
        st = self.wait(t0, t0 + limit, classify_load, "load")
        if st == "load_error":
            res.update(outcome="LOAD ERROR", detail=self._errline())
            return
        if st == "other_error":
            res.update(outcome="other", detail=self._errline())
            return
        if st is None:
            self._timeout(res, "LOADING hang" if any(l.startswith(("loading", "searching"))
                                                     for l in self.last_lines) else "other",
                          boot_phase=False)
            if res["outcome"] == "other":
                res["detail"] = "no loading text; command not run? " + res["detail"]
            return
        # loaded: READY. is back
        if arm == "K":
            got = self.u.readmem(self.addr, len(self.body))
            bad = [i for i in range(len(self.body)) if got[i] != self.body[i]]
            if bad:
                res.update(outcome="mismatch",
                           detail=f"{len(bad)} bytes differ, first at +{bad[0]} of {len(self.body)}")
            else:
                res.update(outcome="pass", detail=f"{len(self.body)} bytes identical")
        elif arm == "C":
            lo = self.u.readmem(0x2B, 2)
            start = lo[0] | lo[1] << 8
            ae = self.u.readmem(0xAE, 2)
            end = ae[0] | ae[1] << 8
            n = end - start
            if not 0 < n <= 0xA000:
                res.update(outcome="other", detail=f"end pointer ${end:04x} start ${start:04x}")
                return
            crc = zlib.crc32(self.u.readmem(start, n))
            sig = (n, crc)
            res["detail"] = f"len={n} crc32={crc:08x}"
            if self.control_ref is None:
                self.control_ref = sig
                res["outcome"] = "pass"
                res["detail"] += " (reference)"
            elif sig == self.control_ref:
                res["outcome"] = "pass"
            else:
                res.update(outcome="mismatch",
                           detail=res["detail"] + f" ref len={self.control_ref[0]} crc32={self.control_ref[1]:08x}")
        else:  # B
            self.feed("run\n")
            t_run = self.clock.now()
            st = self.wait(t_run, t0 + self.limits["B"], classify_boot, "boot")
            self._boot_result(res, st, "B")

    def _arm_b_blind(self, res):
        """Arm B with no reads while the disk is busy: `run` has to be queued before the load starts.
        The key buffer holds 10 bytes, so: LOAD"*",8,1 as the abbreviation `l`+shift-O (9 bytes) is
        written first, one second is given for the editor to take it in, then Return and `r`+shift-U
        (RUN) and Return are written in one blind write. Return starts the load; the RUN stays in the
        buffer and is read by BASIC after READY. All writes precede the transfer."""
        self.feed_raw(bytes([0x4C, 0xCF]) + b'"*",8,1')
        self.clock.sleep(1)
        self.feed_raw(bytes([0x0D, 0x52, 0xD5, 0x0D]), check=False)
        t0 = self.clock.now()
        self.wait(t0, t0 + self.limits["B"], lambda lines: None, "boot")   # sleeps to the limit
        lines = self.last_lines
        st = classify_boot(lines)
        ld = classify_load(lines)
        if st:
            self._boot_result(res, st, "B")
        elif ld == "load_error":
            res.update(outcome="LOAD ERROR", detail=self._errline())
        elif ld == "other_error":
            res.update(outcome="other", detail=self._errline())
        elif any(l.startswith(("loading", "searching")) for l in lines):
            self._timeout(res, "LOADING hang", boot_phase=False)
        elif ld == "loaded":
            res.update(outcome="other", detail="load finished but RUN never started a boot")
        else:
            self._boot_result(res, None, "B")

    def _arm_d(self, res):
        self.u.resume()
        t0 = self.clock.now()
        self.u.run_prg(self.prg)         # reset, load by DMA, RUN; $BA mimics device 8
        st = self.wait(t0, t0 + self.limits["D"], classify_boot, "boot")
        self._boot_result(res, st, "D")

    def _boot_result(self, res, st, arm):
        if st == "login":
            res["outcome"] = "pass"
            res["iostat"] = self.iostat()
        elif st == "panic":
            res.update(outcome="root-mount panic", detail=self._line("panic"))
            res["iostat"] = self.iostat()
        else:
            self._timeout(res, "stall", boot_phase=True)
            res["iostat"] = self.iostat()

    def _timeout(self, res, outcome, boot_phase):
        dump, d = self.stall_dump(boot_phase)
        res.update(outcome=outcome, dump=dump, timed_out=True)
        if boot_phase and outcome == "stall" and not (d.get("st") or 0) & 0x03:
            # the class S signature is a timeout bit in ST ($90); without it say so
            res.update(outcome="other", detail="timeout in root-mount phase, no ST timeout bit")
        self.u.resume()
        self.u.reset()                   # then the owner is asked about the drive LED

    def _errline(self):
        return next((l for l in self.last_lines if l.startswith("?")), "")

    def _line(self, word):
        return next((l for l in self.last_lines if word in l), "")


# ---------------------------------------------------------------- the session
class Session:
    def __init__(self, rig, results, order, args, ask, clock, image_sha):
        self.rig, self.res, self.order, self.a = rig, results, order, args
        self.ask, self.clock = ask, clock
        self.image_sha = image_sha
        self.t_start = clock.now()
        self.fail = {a: 0 for a in ARMS}
        self.stopped_blocks = set()
        self.wedges = 0
        self.kind = None
        self.carry = ""

    def note(self, text, block="", trial="", arm="", outcome="NOTE"):
        self.res.row(session=self.a.session, block=block, trial=trial, arm=arm, outcome=outcome,
                     note=text, start_iso=now_iso(), min_session=self.minutes())

    def minutes(self):
        return round((self.clock.now() - self.t_start) / 60, 1)

    def prompt(self, text):
        ans = self.ask(text)
        if ans.strip().lower() == "stop":
            raise StopSession("owner typed stop")
        return ans.strip().lower()

    def run(self):
        try:
            for block, idx, arm in self.order:
                if block in self.stopped_blocks:
                    continue
                if self.fail[arm] >= ARM_FAIL_LIMIT:
                    self.note(f"skipped: arm {arm} reached {ARM_FAIL_LIMIT} failures", block, idx, arm,
                              outcome="skipped")
                    continue
                if disk_kind(arm) != self.kind:
                    self.kind = disk_kind(arm)
                    self.prompt(f"HAND ACTION (block {block}): " + hand_prompt(self.kind, self.a.disk_id)
                                + " [Enter / stop]: ")
                self.one(block, idx, arm)
        except (StopSession, KeyboardInterrupt) as e:
            self.note(f"STOP: {e or type(e).__name__}", outcome="STOP")
            return 3
        return 0

    def one(self, block, idx, arm):
        start_iso, m_sess = now_iso(), self.minutes()
        row = dict(session=self.a.session, block=block, trial=idx, arm=arm, start_iso=start_iso,
                   min_session=m_sess, min_drive_on=round(m_sess + self.a.drive_on_minutes_ago, 1),
                   image_sha=self.image_sha, commit=self.a.commit, disk_id=self.a.disk_id)
        note = [self.carry] if self.carry else []
        self.carry = ""
        interrupted = None
        try:
            r = self.rig.trial(arm)
        except (KeyboardInterrupt, StopSession) as e:
            interrupted = e
            r = dict(outcome="other", seconds="", detail="interrupted", dump="", timed_out=False,
                     iostat={})
            self.safe_reset()
        except Exception as e:            # noqa: BLE001 - one bad trial must not lose the others
            r = dict(outcome="other", seconds="", detail=f"harness error: {type(e).__name__}: {e}",
                     dump="", timed_out=False, iostat={})
            self.safe_reset()
        hands = False
        try:
            if r.get("timed_out") and interrupted is None:
                ans = self.prompt("Is the drive LED still on? [y/n/stop]: ")
                if ans.startswith("y"):
                    hands = True
                    note.append("wedge: drive LED on, owner power-cycled the drive")
                    self.prompt("power-cycle the drive now, then press Enter: ")
                    self.carry = "drive power-cycled before this trial"
                else:
                    note.append("drive LED off after reset")
        finally:
            io = r.get("iostat") or {}
            self.res.row(**row, outcome=r["outcome"], seconds=r.get("seconds", ""),
                         detail=(r.get("detail", "") + " poll=" + self.rig.poll_mode).strip(), dump=r.get("dump", ""),
                         io_nread=io.get("io_nread", ""), io_nretry=io.get("io_nretry", ""),
                         io_nfail=io.get("io_nfail", ""), io_neoi=io.get("io_neoi", ""),
                         io_last=io.get("io_last", ""), note="; ".join(note))
            if getattr(self.rig, "sidecar", None) and self.a.out:
                with open(self.a.out + ".stall", "a") as f:
                    f.write("\n".join(self.rig.sidecar) + "\n")
        if interrupted:
            raise interrupted
        if r["outcome"] != "pass":
            self.fail[arm] += 1
            if self.fail[arm] == ARM_FAIL_LIMIT:
                self.note(f"arm {arm} reached {ARM_FAIL_LIMIT} failures: stopped from now on", block,
                          idx, arm)
        self.wedges = self.wedges + 1 if hands else 0
        if self.wedges >= WEDGE_LIMIT:
            self.stopped_blocks.add(block)
            self.wedges = 0
            self.note(f"block {block} stopped: {WEDGE_LIMIT} wedges in a row needing hands", block, idx,
                      arm)

    def safe_reset(self):
        try:
            self.rig.u.resume()
            self.rig.u.reset()
        except Exception:                # noqa: BLE001
            pass


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- main
def check_name(name):
    if not name or '"' in name or len(name) > 16 or "\n" in name:
        raise SystemExit("--control-file: 1 to 16 characters, no double quote")


def main(argv=None, client=None, clock=None, ask=None, out=print):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("plan")
    ap.add_argument("--image", required=True, help="kernel PRG (build/breadbin.prg)")
    ap.add_argument("--d64", required=True, help="the Breadbin disk image: checked against --image")
    ap.add_argument("--out", required=True, help="results TSV (appended)")
    ap.add_argument("--disk-id", required=True)
    ap.add_argument("--control-file", required=True, help="file on the control disk for arm C")
    ap.add_argument("--commit", default="", help="kernel commit (git describe of the image's build)")
    ap.add_argument("--session", default="1")
    ap.add_argument("--drive-on-minutes-ago", type=float, default=0.0)
    ap.add_argument("--labels", help="label file (default: IMAGE.lbl)")
    ap.add_argument("--no-prompt", action="store_true",
                    help="tests: skip hand actions; the LED answer is 'n'")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--poll-mode", choices=("none", "byte"), default="none",
                    help="none: no readmem between a trial's start and its limit, then one screen read; "
                         "byte: 1-byte reads of $D6 at most every 2 s, full screen only on a terminal state")
    ap.add_argument("--reboot-wait", type=float, default=15)
    ap.add_argument("--set", action="append", default=[], metavar="CATEGORY/ITEM=VALUE",
                    help="extra config to set (and read back); restored to its prior value")
    a = ap.parse_args(argv)
    check_name(a.control_file)
    clock = clock or Clock()
    with open(a.plan) as f:
        plan = parse_plan(f.read())
    order = expand(plan)
    if a.dry_run:
        dry_run(order, a.disk_id, out)
        return 0

    prg = open(a.image, "rb").read()
    sha = hashlib.sha256(prg).hexdigest()[:16]
    first = d64_first_prg(open(a.d64, "rb").read())
    if first is None or first[1] != prg:
        raise SystemExit("the first PRG on --d64 is not --image: refusing to run with the wrong disk")
    labels = read_labels(a.labels or a.image[:-4] + ".lbl")

    extra = []
    for s in a.set:
        k, _, v = s.partition("=")
        c, _, i = k.partition("/")
        if not (c and i):
            raise SystemExit(f"--set wants CATEGORY/ITEM=VALUE, got {s!r}")
        extra.append((c, i, v))

    if client is None:
        sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
        from ultimate import Ultimate         # noqa: E402 - reads BREADBIN_ULTIMATE
        client = Ultimate.from_env()
    if ask is None:
        ask = (lambda text: "") if a.no_prompt else input
    if a.no_prompt:
        ask = (lambda text: "n" if text.startswith("Is the drive LED") else "")

    log = Results(a.out)
    rig = Rig(client, clock, prg, labels, a.control_file, poll_mode=a.poll_mode)
    log.comment(f"session {a.session}; plan {os.path.basename(a.plan)}: {len(order)} trials")
    log.comment(f"image {os.path.basename(a.image)} sha256 {sha}; commit {a.commit or '-'}; "
                f"disk {a.disk_id}; control file {a.control_file}")
    log.comment(f"labels: {'found, ' + str(len(labels)) if labels else 'absent'}; "
                f"iostat labels present: {[n for n in IO_COUNTERS if n in labels] or 'none'}")
    log.comment(f"drive powered on {a.drive_on_minutes_ago:g} min before session start")
    log.comment(f"poll mode {a.poll_mode} (none: no readmem during a trial until its limit; byte: "
                f"1-byte reads of $D6 every {BYTE_EVERY} s, boot phases from {rig.first_read} s); "
                f"limits {rig.limits}")
    guard = ConfigGuard(client, clock, log, a.reboot_wait, extra)

    def cfg_dump(tag):                        # read-only, redacted (cfgdump.py); never stops a run
        try:
            sys.path.insert(0, HERE)
            import cfgdump
            path = f"{a.out}.cfg-{tag}.json"
            d = cfgdump.write_dump(client, path)
            log.comment(f"config dump {tag}: {os.path.basename(path)}; "
                        f"{len(cfgdump.non_defaults(d))} item(s) differ from default")
        except Exception as e:                # noqa: BLE001
            print(f"config dump {tag} failed: {e}", file=sys.stderr, flush=True)

    def on_signal(signum, frame):
        raise StopSession(f"signal {signum}")

    old = {}
    for sg in (signal.SIGTERM, signal.SIGHUP):
        try:
            old[sg] = signal.signal(sg, on_signal)
        except ValueError:                    # not the main thread
            pass
    status = 3
    try:
        cfg_dump("start")
        guard.apply()
        sess = Session(rig, log, order, a, ask, clock, sha)
        status = sess.run()
    except (StopSession, KeyboardInterrupt) as e:
        try:
            log.row(session=a.session, outcome="STOP", note=f"STOP during setup: {e}")
        except Exception:                      # noqa: BLE001
            pass
        status = 3
    finally:
        guard.restore()
        cfg_dump("end")
        for sg, h in old.items():
            signal.signal(sg, h)
        log.close()
    return status


if __name__ == "__main__":
    sys.exit(main())
