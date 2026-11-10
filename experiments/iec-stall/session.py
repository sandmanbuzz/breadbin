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
(byte compare), B boot (load, run, login, IOSTAT), D DMA kernel + root mount (plainboot logic),
P as D but with one 1000-byte screen read every 2 s from 3 s after the start (block 2b, the causal
poll arm; its own failure count, 4 failures end the block). A block may be a word ("2b", "dry").
Session 2 poll arms (table POLL_ARMS; each has its own failure count, 4 stop that arm; they can end
early when the screen shows the login / READY., as P does):
  Q  as D plus a 1000-byte screen read every 0.5 s from the start (the old test backends' wait_for);
     limit 170 s.
  J  as K (machine's own `load"*",8,1`, bytes compared; outcomes LOADING hang / LOAD ERROR / mismatch /
     pass) plus a 1000-byte read every 0.5 s from the moment the load command is typed; limit 120 s.
  O  as D plus a 1-byte read of $D6 every 0.1 s from the start; limit 170 s (one screen read at the
     limit). The detail column names the poll (poll=1000b/0.5s, poll=1b/0.1s).
Session 3 arms (docs/design/io-trial-protocol.md):
  Z  as D plus, every 0.5 s from the start, machine:pause, one 1000-byte screen read, machine:resume
     (resume in a finally; the restore trap resumes too).
  S  as J with the STOCK Kernal ROM selected in the Ultimate config for the trial; T = K with the stock
     KERNAL (control, no polling). The stock value is discovered from the item's allowed values (GET on
     "C64 and Cartridge Settings/Kernal ROM"); with no obvious stock/original entry the run refuses
     before changing anything. The original value is put back before the next non-stock arm and by the
     restore trap (read back).
  G  as Q but gated: three 1-byte reads of $DD00 0.1 s apart before each screen read, which happens only
     if all show (v & $F8) == $C0; else the poll is skipped.  H  as J, gated the same way.
     Gated arms record screen reads done / skipped and the $DD00 value histogram in `detail`.
--dma-image: the kernel arms D, P, Q, O, Z and G load by DMA, when it is not the one on the disk (--image,
--d64: what K compares and B boots). Each has its own labels file (IOSTAT counters, `ticks`).

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
sys.path.insert(0, HERE)
import iostat  # noqa: E402 - uptime(); no side effects at import

# Poll arms: a base arm plus a deliberate poll of the machine while the transfer runs. One dict row each.
#   base      the arm whose steps it runs (D: DMA kernel + root mount; K: KERNAL load, bytes compared)
#   nbytes    bytes per read: 1000 = the whole screen (classified, so the arm can end early on the
#             login / READY.), 1 = the byte at $D6 only (nothing classified until the limit)
#   accept    (all poll arms: ACCEPT_AFTER) a screen read earlier than this many seconds after the start
#             is never classified: the previous trial's login / READY. may still be on screen
#   every     seconds between reads;  first  seconds from the start (D bases: the DMA run) or from the
#             typed load command (K base) to the first read;  limit  seconds;  fail  failures that
#             stop the arm;  end_block  that many failures end the whole block (P only, amendment 1)
POLL_ARMS = {
    "P": dict(base="D", nbytes=1000, every=2, first=3, limit=170, fail=4, end_block=True),
    "Q": dict(base="D", nbytes=1000, every=0.5, first=0, limit=170, fail=4, end_block=False),
    "J": dict(base="K", nbytes=1000, every=0.5, first=0, limit=120, fail=4, end_block=False),
    "O": dict(base="D", nbytes=1, every=0.1, first=0, limit=170, fail=4, end_block=False),
    # Session 3 (docs/design/io-trial-protocol.md). Extra keys:
    #   pause  each read is wrapped in machine:pause / machine:resume (resume in a finally)
    #   gate   before each screen read, three 1-byte reads of $DD00 0.1 s apart; the screen is read only if
    #          every one has (v & $F8) == $C0 (DATA and CLK in high, DATA/CLK/ATN out not driven), else the
    #          poll is skipped. The reads done and skipped, and the $DD00 value histogram, go in `detail`.
    #   stock  the Ultimate's Kernal ROM is the stock one for the trial (discovered, see ConfigGuard)
    "Z": dict(base="D", nbytes=1000, every=0.5, first=0, limit=170, fail=4, end_block=False, pause=True),
    "S": dict(base="K", nbytes=1000, every=0.5, first=0, limit=120, fail=4, end_block=False, stock=True),
    "G": dict(base="D", nbytes=1000, every=0.5, first=0, limit=170, fail=4, end_block=False, gate=True),
    "H": dict(base="K", nbytes=1000, every=0.5, first=0, limit=120, fail=4, end_block=False, gate=True),
}
# Arms that do not poll but are a base arm with a variation: T = K with the stock KERNAL (control for S).
VARIANT_ARMS = {"T": dict(base="K", limit=120, stock=True)}
GATE_READS = 3            # arms G, H: 1-byte $DD00 reads before a screen read ...
GATE_SPACING = 0.1        # ... this many seconds apart
GATE_MASK, GATE_IDLE = 0xF8, 0xC0
KERNAL_ITEM = ("C64 and Cartridge Settings", "Kernal ROM")
ACCEPT_AFTER = 3          # poll arms: no screen classification from a read earlier than this after the start
ARMS = "CKBD" + "".join(POLL_ARMS) + "".join(VARIANT_ARMS)
LIMITS = {"C": 120, "K": 120, "B": 150, "D": 170}      # seconds, protocol
LIMITS.update({a: v["limit"] for a, v in POLL_ARMS.items()})
LIMITS.update({a: v["limit"] for a, v in VARIANT_ARMS.items()})
FIRST_READ = 20           # no DMA read this long after a transfer starts (plainboot)
POLL = 10                 # then one screen read per this many seconds
BYTE_FIRST = 2            # --poll-mode byte, KERNAL load: first 1-byte read this long after the command
BYTE_EVERY = 2            # and at most one 1-byte read per this many seconds
SETTLE = 6                # after a reset, before the first read (stockload)
ARM_FAIL_LIMIT = 5
ARM_FAIL_LIMITS = {a: v["fail"] for a, v in POLL_ARMS.items()}   # P: protocol amendment 1
WEDGE_LIMIT = 3
IO_RECORD = ("io_ltrk", "io_lsct", "io_lidx", "io_ltry", "io_lst", "io_lwn")
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
READBACK_ONLY = [KERNAL_ITEM]


class StopSession(Exception):
    """The session stops now (mechanical symptom, `stop`, Ctrl-C, signal)."""


class Clock:
    def now(self):
        return time.monotonic()

    def sleep(self, s):
        if s > 0:
            time.sleep(s)


# ---------------------------------------------------------------- plan
def block_id(v):
    """A block is an int (1, 2, 3) or a word ("2b", "dry"); the order in the file is the order run."""
    v = str(v).strip()
    return int(v) if v.isdigit() else v


def parse_plan(text):
    """-> [(block, arms, count)] in file order."""
    text = text.strip()
    out = []
    if text.startswith("["):
        for e in json.loads(text):
            if isinstance(e, dict):
                e = [e["block"], e["arms"], e["count"]]
            out.append((block_id(e[0]), str(e[1]).upper(), int(e[2])))
    else:
        for n, line in enumerate(text.splitlines(), 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            f = line.split()
            if len(f) != 3:
                raise ValueError(f"plan line {n}: want BLOCK ARMS COUNT, got {line!r}")
            out.append((block_id(f[0]), f[1].upper(), int(f[2])))
    for block, arms, count in out:
        if not arms or any(a not in ARMS for a in arms) or count < 1 or block == "":
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


def base_arm(arm):
    """The arm whose steps `arm` runs: itself, or for a poll arm its base (D or K)."""
    if arm in POLL_ARMS:
        return POLL_ARMS[arm]["base"]
    return VARIANT_ARMS[arm]["base"] if arm in VARIANT_ARMS else arm


def arm_stock(arm):
    """True for the arms that run with the stock KERNAL ROM selected in the Ultimate (S, T)."""
    return bool((POLL_ARMS.get(arm) or VARIANT_ARMS.get(arm) or {}).get("stock"))


def poll_label(arm):
    """'1000b/2s', '1b/0.1s', or None for an arm that does not poll."""
    v = POLL_ARMS.get(arm)
    if not v:
        return None
    return (f"{v['nbytes']}b/{v['every']:g}s" + ("+pause" if v.get("pause") else "")
            + (f"+gate{GATE_READS}x1b" if v.get("gate") else ""))


def arm_kernel(arm):
    return "dma" if base_arm(arm) == "D" else "disk"


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
        out(f"block {block}  trial {idx:3d}  arm {arm}  limit {LIMITS[arm]} s"
            + (f"  poll {poll_label(arm)}" if arm in POLL_ARMS else "")
            + ("  stock KERNAL" if arm_stock(arm) else ""))
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


def config_allowed(reply, cat, item):
    """The allowed values a config item's GET reports (a list under values / allowed / options), or None."""
    node = reply.get(cat, reply)
    node = node.get(item, node) if isinstance(node, dict) else node
    if isinstance(node, dict):
        for k in ("values", "allowed", "options", "allowed_values"):
            if isinstance(node.get(k), list):
                return [str(x) for x in node[k]]
    return None


STOCK_WORDS = ("original", "stock")


def pick_stock_kernal(allowed):
    """-> (value, why) for the stock KERNAL among the allowed values, else (None, reason). Never a guess:
    an entry whose name says original / stock (and no JiffyDOS), else the empty entry when the item lists
    one (the firmware's 'no replacement' value, seen to work 2026-10-31); two candidates is a refusal."""
    if not allowed:
        return None, "the item reports no allowed values"
    named = [v for v in allowed if any(w in v.lower() for w in STOCK_WORDS) and "jiffy" not in v.lower()]
    if len(named) == 1:
        return named[0], "named entry"
    if len(named) > 1:
        return None, f"several stock-looking entries {named}"
    if "" in allowed:
        return "", "empty entry"
    return None, f"no original/stock entry among {allowed}"


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
        self.kernal_orig = None           # the Kernal ROM value found at apply(); set only if we change it
        self.kernal_touched = False
        self.stock_value = None

    def get(self, cat, item):
        try:
            return config_value(self.u.call("GET", quote_cfg(cat, item)), cat, item)
        except Exception as e:           # noqa: BLE001 - a read-back must not stop the run
            return f"<unreadable: {clean(e)[:60]}>"

    def put(self, cat, item, value):
        self.u.call("PUT", quote_cfg(cat, item), {"value": value})

    def stock_kernal(self):
        """The stock Kernal ROM value, discovered from the item's allowed values at run time. SystemExit
        with a clear message if it cannot be told (arms S and T then refuse to run). Reads only."""
        try:
            allowed = config_allowed(self.u.call("GET", quote_cfg(*KERNAL_ITEM)), *KERNAL_ITEM)
        except Exception as e:           # noqa: BLE001
            raise SystemExit(f"arms S and T refuse to run: cannot read the Kernal ROM item ({clean(e)[:80]})")
        val, why = pick_stock_kernal(allowed)
        if val is None:
            raise SystemExit("arms S and T refuse to run: no stock KERNAL value in the Ultimate config "
                             f"({why}); choose it by hand and rerun with it set")
        self.stock_value = val
        self.log.comment(f"stock Kernal ROM value discovered: {val!r} ({why}) from allowed values {allowed}")
        return val

    def select_kernal(self, stock):
        """Make the Kernal ROM the stock one (stock=True) or the value found at start; reboot if it
        changed (a change does not take effect on reset); read back. restore() puts the original back."""
        if not stock and not self.kernal_touched:
            return                        # nothing of ours to put back
        if self.stock_value is None:
            self.stock_kernal()
        if self.kernal_orig is None or self.kernal_orig.startswith("<"):
            raise RuntimeError(f"original Kernal ROM unreadable ({self.kernal_orig!r}): not changing it")
        want = self.stock_value if stock else self.kernal_orig
        if self.get(*KERNAL_ITEM) == want:
            return
        self.kernal_touched = True
        self.put(*KERNAL_ITEM, want)
        self.u.reboot()
        self.clock.sleep(self.reboot_wait)
        got = self.get(*KERNAL_ITEM)
        self.log.comment(f"Kernal ROM set to {want!r} ({'stock' if stock else 'original'}), read back {got!r}")
        if got != want:
            raise RuntimeError(f"Kernal ROM read back {got!r}, wanted {want!r}")

    def readback(self):
        keys = [(c, i) for c, i, _, _ in self.items] + READBACK_ONLY
        return {f"{c}/{i}": self.get(c, i) for c, i in keys}

    def apply(self):
        self.log.comment("config before: " + json.dumps(self.readback(), sort_keys=True))
        for c, i, v, _ in self.items:
            self.original[(c, i)] = self.get(c, i)
        self.kernal_orig = self.get(*KERNAL_ITEM)
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
        if self.kernal_touched:
            try:
                self.put(*KERNAL_ITEM, self.kernal_orig)
            except Exception as e:       # noqa: BLE001
                print(f"RESTORE FAILED {KERNAL_ITEM[0]}/{KERNAL_ITEM[1]}: {e}", file=sys.stderr, flush=True)
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
                 settle=SETTLE, limits=None, poll_mode="none", dma_image=None, labels_dma=None, kernal=None):
        self.u, self.clock = u, clock
        self.kernal = kernal         # ConfigGuard (select_kernal) for arms S and T
        self.dd00 = {}               # gated arms: $DD00 value -> count, this trial
        self.gate = [0, 0]           # gated arms: screen reads done, skipped, this trial
        self.poll_mode = poll_mode
        self.dma_prg = dma_image if dma_image is not None else image
        self.labels_dma = labels_dma if labels_dma is not None else labels
        self.cur_labels = labels      # the labels of the kernel the current trial runs
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
        lb = self.cur_labels
        for n in IO_COUNTERS:
            if n in lb:
                try:
                    w = label_width(lb, n)
                    out[n] = int.from_bytes(self.u.readmem(lb[n], w), "little")
                except Exception:        # noqa: BLE001
                    out[n] = ""
        last = []
        # the last-stall record (blk.s): one byte each; a code label "io_last" exists in iec.s, so
        # match the record's names exactly (the old prefix match read two bytes of that routine)
        for n in IO_RECORD:
            if n in lb:
                try:
                    last.append(f"{n[3:]}={self.u.readmem(lb[n], 1).hex()}")
                except Exception:        # noqa: BLE001
                    pass
        out["io_last"] = ";".join(last) or ("" if any(n in lb for n in IO_COUNTERS) else "iostat absent")
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
        lb = self.cur_labels
        if boot_phase and "io_out" in lb:
            try:
                base = lb["io_out"]
                names = ("io_out io_base io_b io_n io_to io_pend io_held io_eoi io_inf io_sx io_sy "
                         "ie_dev ie_sa ie_len ie_len2").split()
                if lb.get("io_n") == base + 3 and lb.get("ie_dev") == base + 11:
                    v = self.u.readmem(base, 15)
                    stack = self.u.readmem(0x1C0, 64).hex()
                    self.sidecar.append(str({n: f"{b:02x}" for n, b in zip(names, v)})
                                        + " stack:" + stack)
                    txt += " iovars=" + v.hex()
                else:
                    txt += " iovars=layout-changed"
            except Exception:            # noqa: BLE001
                pass
        txt += " " + self.uptime()
        last = self.last_lines[-1] if self.last_lines else ""
        return txt + f" last={last!r}", d

    def uptime(self):
        """Protocol amendment 1: the kernel's jiffy count in every stall dump, so the onset of a stall
        is known relative to the first DMA read. Two 3-byte reads, only here (after the limit)."""
        return iostat.uptime(self.u, self.cur_labels)

    # -- arms
    def trial(self, arm):
        """-> dict(outcome, seconds, detail, dump, timed_out, iostat)."""
        self.sidecar = []
        self.last_lines = []
        self.dd00, self.gate = {}, [0, 0]
        if self.kernal is not None:       # also puts the original back after a stock-KERNAL arm
            self.kernal.select_kernal(arm_stock(arm))
        elif arm_stock(arm):
            raise RuntimeError("arm needs the stock KERNAL but no config guard was given")
        self.cur_labels = self.labels_dma if arm_kernel(arm) == "dma" else self.labels
        res = dict(outcome="other", detail="", dump="", timed_out=False, iostat={})
        t0 = self.clock.now()
        if base_arm(arm) == "D":
            self._arm_d(res, arm)
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
        if self.dd00 or self.gate != [0, 0]:        # only the gated arms leave anything here
            hist = ",".join(f"{k:02x}:{n}" for k, n in sorted(self.dd00.items(), key=lambda kv: (-kv[1], kv[0])))
            res["detail"] = (res.get("detail", "") + f" screen_reads={self.gate[0]} skipped={self.gate[1]}"
                             f" dd00={hist or '-'}").strip()
        return res

    def _arm_load(self, arm, res, t0):
        limit = self.limits[arm]
        if arm == "B" and self.poll_mode == "none":
            self._arm_b_blind(res)
            return
        cmd = f'load"{self.control_file}",8\n' if arm == "C" else 'load"*",8,1\n'
        self.feed(cmd)
        if arm in POLL_ARMS:
            st = self.poll_wait(arm, self.clock.now(), t0 + limit, classify_load)
        else:
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
        if base_arm(arm) == "K":
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

    def _arm_d(self, res, arm="D"):
        self.u.resume()
        t0 = self.clock.now()
        self.u.run_prg(self.dma_prg)     # reset, load by DMA, RUN; $BA mimics device 8
        if arm in POLL_ARMS:
            st = self.poll_wait(arm, t0, t0 + self.limits[arm], classify_boot)
        else:
            st = self.wait(t0, t0 + self.limits["D"], classify_boot, "boot")
        self._boot_result(res, st, arm)

    def poll_wait(self, arm, t_from, t_end, classify):
        """Poll arms (POLL_ARMS): one read of nbytes every `every` s from `first` s after t_from to the
        limit (the deliberate poll the arm exists to test). 1000 bytes: the screen, classified; a
        terminal state ends the wait early. 1 byte: $D6 only, then one screen read at the limit.
        pause arms wrap the screen read in machine:pause / resume; gate arms read $DD00 three times
        first and skip the poll unless the bus looks idle (see POLL_ARMS). Returns the state or None."""
        v = POLL_ARMS[arm]
        self.clock.sleep(t_from + v["first"] - self.clock.now())
        while True:
            ts = self.clock.now()
            if v["nbytes"] > 1:
                lines = self.poll_screen(v)      # always read (the poll is the point) ...
                if lines is not None and self.clock.now() >= t_from + ACCEPT_AFTER:
                    st = classify(lines)         # ... but a stale screen is not believed
                    if st:
                        return st
            else:
                self.u.readmem(0xD6, v["nbytes"])
            left = t_end - self.clock.now()
            if left <= 0:
                return None if v["nbytes"] > 1 else classify(self.screen())
            gap = v["every"] - (self.clock.now() - ts) if v.get("gate") else v["every"]
            self.clock.sleep(min(max(gap, 0), left))

    def poll_screen(self, v):
        """One poll of the screen for arm table row v: the lines read, or None if a gate skipped it."""
        if v.get("gate"):
            idle = True
            for k in range(GATE_READS):          # all three are read: the histogram wants every value
                b = self.u.readmem(0xDD00, 1)[0]
                self.dd00[b] = self.dd00.get(b, 0) + 1
                idle = idle and (b & GATE_MASK) == GATE_IDLE
                if k < GATE_READS - 1:
                    self.clock.sleep(GATE_SPACING)
            if not idle:
                self.gate[1] += 1
                return None
            self.gate[0] += 1
        if v.get("pause"):
            self.u.pause()
            try:
                return self.screen()
            finally:
                self.u.resume()                  # always: a paused machine never gets its IEC bytes
        return self.screen()

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
        self.image_sha = image_sha if isinstance(image_sha, dict) else {"disk": image_sha, "dma": image_sha}
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
                if self.fail[arm] >= ARM_FAIL_LIMITS.get(arm, ARM_FAIL_LIMIT):
                    self.note(f"skipped: arm {arm} reached {ARM_FAIL_LIMITS.get(arm, ARM_FAIL_LIMIT)} failures", block, idx, arm,
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
                   image_sha=self.image_sha[arm_kernel(arm)], commit=self.a.commit, disk_id=self.a.disk_id)
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
                         detail=(r.get("detail", "") + " poll=" + (poll_label(arm) or self.rig.poll_mode)).strip(), dump=r.get("dump", ""),
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
            lim = ARM_FAIL_LIMITS.get(arm, ARM_FAIL_LIMIT)
            if self.fail[arm] == lim:
                self.note(f"arm {arm} reached {lim} failures: stopped from now on", block, idx, arm)
                if POLL_ARMS.get(arm, {}).get("end_block"):    # P: the point is made; spare the drive: the whole block ends
                    self.stopped_blocks.add(block)
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
    ap.add_argument("--dma-image", help="kernel PRG for arms D, P, Q and O (loaded by DMA) when it is not the "
                    "one on the disk (--image); default: --image")
    ap.add_argument("--labels", help="label file of the DMA kernel (default: DMA-IMAGE.lbl, or IMAGE.lbl)")
    ap.add_argument("--labels-disk", help="label file of the kernel on the disk, arms B (default: IMAGE.lbl)")
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
    dma_prg = open(a.dma_image, "rb").read() if a.dma_image else prg
    dma_sha = hashlib.sha256(dma_prg).hexdigest()[:16]
    labels = read_labels(a.labels_disk or a.image[:-4] + ".lbl")
    labels_dma = read_labels(a.labels or ((a.dma_image or a.image)[:-4] + ".lbl")) if (a.labels or a.dma_image) else labels

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
    guard = ConfigGuard(client, clock, log, a.reboot_wait, extra)
    if any(arm_stock(x) for _, _, x in order):      # S, T: refuse now, before anything is changed
        try:
            guard.stock_kernal()
        except SystemExit:
            log.close()
            raise
    rig = Rig(client, clock, prg, labels, a.control_file, poll_mode=a.poll_mode, dma_image=dma_prg,
              labels_dma=labels_dma, kernal=guard)
    log.comment(f"session {a.session}; plan {os.path.basename(a.plan)}: {len(order)} trials")
    log.comment(f"image {os.path.basename(a.image)} sha256 {sha}; commit {a.commit or '-'}; "
                f"disk {a.disk_id}; control file {a.control_file}")
    if a.dma_image:
        log.comment(f"dma image {os.path.basename(a.dma_image)} sha256 {dma_sha} (arms D, P); "
                    f"disk image {os.path.basename(a.image)} sha256 {sha} (arms K, B)")
    for nm, lb in (("disk kernel (K, B)", labels), ("dma kernel (D, P)", labels_dma)):
        log.comment(f"labels {nm}: {'found, ' + str(len(lb)) if lb else 'absent'}; "
                    f"iostat labels present: {[n for n in IO_COUNTERS if n in lb] or 'none (counters recorded as absent)'}; "
                    f"ticks label: {'$%04x' % lb['ticks'] if 'ticks' in lb else 'absent (reads $004a)'}")
    log.comment(f"drive powered on {a.drive_on_minutes_ago:g} min before session start")
    log.comment(f"poll mode {a.poll_mode} (none: no readmem during a trial until its limit; byte: "
                f"1-byte reads of $D6 every {BYTE_EVERY} s, boot phases from {rig.first_read} s); "
                f"limits {rig.limits}")

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
        sess = Session(rig, log, order, a, ask, clock, {"disk": sha, "dma": dma_sha})
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
