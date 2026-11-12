#!/usr/bin/env python3
"""Session 5 acceptance runner (docs/design/io-trial-protocol.md, "Session 5": W, B, R).

Run every arm under the lock, with the address only in the environment:

    export BREADBIN_ULTIMATE=<host>      # never written to any file by this script
    tools/with-lock -r ultimate -- python3 experiments/iec-stall/session5.py w --tree TREE --rev REV
    tools/with-lock -r ultimate -- python3 experiments/iec-stall/session5.py b --tree TREE --rev REV
    tools/with-lock -r ultimate -- python3 experiments/iec-stall/session5.py r --tree TREE --rev REV
    tools/with-lock -r ultimate -- python3 experiments/iec-stall/session5.py plan experiments/iec-stall/plans/session5.plan --tree TREE --rev REV
    python3 experiments/iec-stall/session5.py tools --tree TREE     # build the tools disk only; no network
    python3 experiments/iec-stall/session5.py plan PLAN --tree TREE --dry-run

REV must equal TREE/build/rev.txt and must not end in "+" (a dirty build): the run refuses otherwise.
--no-prompt is refused for a plan that has W together with B or R (the disk in drive 8 changes between them);
EOF at a prompt stops the run.

TREE is the frozen release worktree (fix/io-release), built: TREE/build/breadbin.prg, breadbin.d64 (the image
on the physical 1541), kernel.lbl, lib/breadbin.lib, and its include/, src/prog.cfg and tools/cx.py, which
build the two helper programs (session5/wv.s, session5/cksum.s) into a tools disk.

Arms (counts: -n; defaults 300, 300, 50):
  W  ROM-KERNAL write-verify: the BASIC program W_PROGRAM (below) is tokenized here, written to $0801 by DMA
     while the bus is idle at READY, and RUN on the machine's own KERNAL against the physical 1541 on drive 8.
     It keeps its counts at $C000 (W_FIELDS) and prints them. The harness then makes NO request for the wait
     (estimate times 3, plus a margin; --wait), gates on an idle bus and reads $C000 once.
     The program first reads the BAM (U1 into a "#" buffer) and refuses to start (state 4, not a failure;
     nothing is written) if the disk has no free CBM blocks: the Breadbin release disk has none (c64fs marks
     every block used in the CBM BAM). W needs a CBM disk with free blocks in drive 8 (see the prompt).
  B  our kernel write-verify: boot as R does, `mount 9 /mnt` (the tools disk in drive A, bus 9), run
     `/mnt/wv N /home/s5b /bin/as <io_nread>` (session5/wv.s says what one cycle does), NO request for the wait,
     then one gated screen read; the IOSTAT counters before and after.
  R  boot cycle: per cycle a new tools/ultimatetest.UltimateTarget (reset; the machine's own `load"*",8,1`
     of the release image from the physical 1541, no request during it; the loaded bytes read back and
     compared; run), gate log on; login; `mount 9 /mnt`; `ls /bin` (the image's names, and the same text as
     cycle 1); `/mnt/cksum /bin/as` against the value computed here from the image; IOSTAT read back.
A wait that ends with the workload unfinished is a HANG: the arm then polls every 30 s (paced, gated reads)
until the workload ends or stops moving, and records that in the after_limit column; the outcome stays HANG.
Outcomes per row: PASS, FAIL, HANG, SETUP (W: the program never reached READY/ran; stop), STOP (a network
error to the Ultimate or a signal; the row is written, then the run stops), REFUSED (W), INVALID (B).
Every arm: stop at the first failure (protocol "Failures"); capture $90/$BA/$DD00, the IEC variables and
the stack (decode.py), the screen and the counters to results/session5/<arm>.capture.txt; one TSV per arm
(results/session5/<arm>.tsv, appended, fsynced per row); the gate log to <arm>.gate.log. The Ultimate
config is the sessions 1-4 one (session.CONFIG: SoftIEC off, drive A on bus 9, DMA load mimics 8), set and
read back at the start, restored in a finally with signals ignored and read back (session.ConfigGuard). The
run refuses unless the Kernal ROM is JiffyDOS-C64.bin.

Exit status: 0 pass, 1 failure (an arm failed), 3 stopped (signal, Ctrl-C, setup problem, network error), 5 W refused
(no free blocks; nothing ran), 6 B invalid (its read-backs did not reach the bus), 2 usage,
4 the Kernal ROM was not restored (wins).
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "..", "tools")
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)
import session  # noqa: E402  ConfigGuard, CONFIG, signal helpers (no side effects at import)
from ultimate import UltimateError  # noqa: E402
from ultimatetest import IDLE_GAP  # noqa: E402

RESULTS = os.path.join(HERE, "results", "session5")
DEFAULT_N = {"W": 300, "B": 300, "R": 50}
EXIT_PASS, EXIT_FAIL, EXIT_STOP, EXIT_REFUSED, EXIT_INVALID = 0, 1, 3, 5, 6

# ---------------------------------------------------------------- arm W: the BASIC program
# Steps (W_FIELDS "step"): 1 open 15 "i0"; 2 open the "#" buffer; 3 U1 of 18/0 (the BAM); 4 scratch;
# 5 open for writing; 6 write 254 bytes; 7 close; 8 open for reading; 9 read + compare (ST must be 0 before
# the last byte); 10 ST at the last byte must be 64 (EOI); 11 close; 12 the final scratch.
# ST ($90, 144) is cleared before each step that is not an OPEN (OPEN clears it; CLOSE and PRINT# do not, and
# the KERNAL ORs bits into it, so the EOI of the last INPUT#15 would otherwise still read as 64: seen under VICE).
# After every step: ST (saved before the DOS status is read, which changes ST) must be 0 and the DOS status
# (INPUT#15) 00, or 01 with exactly 1 file scratched (0 allowed on cycle 1; the final scratch must remove 1);
# the status read itself must leave ST clear but for EOI (line 800: else an ST error, via 610). Pattern: byte i of cycle k is
# (k*7 + i*13) AND 255, the same as wv.s. Lines 600-690 count the failure and stop. No "@0:" anywhere.
W_RESULT = 0xC000
W_PROGRAM = """\
10 r=49152:n={n}:for i=0 to 28:poke r+i,0:next
20 poke r,83:poke r+1,53:poke r+2,87:poke r+3,1:poke r+14,1
30 t=ti:gosub 900:poke r+20,t1:poke r+21,t2:poke r+22,t3
40 p=1:open 15,8,15,"i0":q=st:gosub 800:if q then 600
45 if e then 620
50 p=2:open 2,8,2,"#":q=st:gosub 800:if q then 600
55 if e then 620
60 p=3:poke 144,0:print#15,"u1:2,0,18,0":q=st:gosub 800:if q then 600
65 if e then 620
70 c=0:for i=0 to 143:get#2,a$:a=asc(a$+chr$(0)):if i>3 and (i and 3)=0 and i<>72 then c=c+a
75 next:close 2:poke r+18,c and 255:poke r+19,int(c/256)
80 if c<1 then poke r+14,4:print "s5w refused: 0 blocks free":goto 950
100 for k=1 to n:poke r+15,k and 255:poke r+16,int(k/256)
110 p=4:poke 144,0:print#15,"s0:s5w":q=st:gosub 800:if q then 600
115 if e<>1 then 620
120 if u<>1 and not (k=1 and u=0) then poke r+26,u:goto 620
200 p=5:open 3,8,3,"s5w,s,w":q=st:gosub 800:if q then 600
205 if e then 620
210 p=6:q=0:poke 144,0:for i=0 to 253:print#3,chr$((k*7+i*13) and 255);:q=q or st:next
215 gosub 800:if q then 600
217 if e then 620
220 p=7:poke 144,0:close 3:q=st:gosub 800:if q then 600
225 if e then 620
300 p=8:open 3,8,3,"s5w,s,r":q=st:gosub 800:if q then 600
305 if e then 620
310 p=9:poke 144,0:for i=0 to 253:get#3,a$:q=st:a=asc(a$+chr$(0)):w=(k*7+i*13) and 255
315 if a<>w then 640
320 if i<253 and q then 600
325 next:p=10:if q<>64 then 600
330 gosub 800:if e then 620
335 p=11:poke 144,0:close 3:q=st:gosub 800:if q then 600
340 if e then 620
345 poke r+4,k and 255:poke r+5,int(k/256):if k-int(k/25)*25=0 then print "s5w";k
350 next k
400 p=12:poke 144,0:print#15,"s0:s5w":q=st:gosub 800:if q then 600
405 if e<>1 then 620
407 if u<>1 then poke r+26,u:goto 620
410 poke r+14,2:goto 950
600 poke r+12,q:x=r+8:goto 680
610 q=s:goto 600
620 poke r+13,e:x=r+10:goto 680
640 poke r+26,i:poke r+27,a:poke r+28,w:x=r+6
680 y=peek(x)+256*peek(x+1)+1:poke x,y and 255:poke x+1,int(y/256):poke r+17,p:poke r+14,3
690 goto 950
800 poke 144,0:input#15,e,m$,u,v:s=st and 191:poke r+13,e:if s then 610
805 return
900 t1=int(t/65536):t=t-t1*65536:t2=int(t/256):t3=t-t2*256:return
950 close 3:close 2:close 15:t=ti:gosub 900:poke r+23,t1:poke r+24,t2:poke r+25,t3
960 print "s5w end n";n;"done";peek(r+4)+256*peek(r+5);"mis";peek(r+6);"st";peek(r+8);"dos";peek(r+10)
965 print "s5w state";peek(r+14);"free";peek(r+18)+256*peek(r+19)
970 if peek(r+14)=3 then print "s5w fail cycle";k;"step";p;"st";q;"dos";e;m$;u;v
980 end
"""
# offset, width, name (little endian; ti_* are 3 bytes, most significant first, as line 900 splits them)
W_FIELDS = [(0, 3, "magic"), (3, 1, "version"), (4, 2, "done"), (6, 2, "mismatches"), (8, 2, "st_errors"),
            (10, 2, "dos_errors"), (12, 1, "last_st"), (13, 1, "last_dos"), (14, 1, "state"),
            (15, 2, "cycle"), (17, 1, "step"), (18, 2, "blocks_free"), (20, 3, "ti_start"),
            (23, 3, "ti_end"), (26, 1, "index"), (27, 1, "got"), (28, 1, "want")]
W_LEN = 29
W_MAGIC = b"S5W"
W_STATES = {0: "not started", 1: "running", 2: "done", 3: "stopped at a failure", 4: "refused (no free blocks)"}
# Per-cycle time on the stock KERNAL under VICE (tests/session5_vice.py, W_CYCLE_VICE there); the wait is
# W_WAIT_FACTOR times it per cycle plus W_WAIT_BASE. JiffyDOS on hardware is faster, the stock KERNAL slower.
W_CYCLE_EST = 4.0
W_WAIT_FACTOR = 3.0
W_WAIT_BASE = 60.0
B_CYCLE_EST = 3.0
B_WAIT_FACTOR = 3.0
B_WAIT_BASE = 60.0

# ---------------------------------------------------------------- C64 BASIC V2 tokenizer
TOKENS = ("end for next data input# input dim read let goto run if restore gosub return rem stop on wait "
          "load save verify def poke print# print cont list clr cmd sys open close get new tab( to fn spc( "
          "then not step + - * / ^ and or > = < sgn int abs usr fre pos sqr rnd log exp cos sin tan atn "
          "peek len str$ val asc chr$ left$ right$ mid$ go").split()
T_DATA, T_REM, T_PRINT = 0x83, 0x8F, 0x99


def petscii_char(c):
    if "a" <= c <= "z":
        return ord(c) - 0x20
    if "A" <= c <= "Z":
        raise ValueError("upper case (shifted) letters are not used in the program text")
    o = ord(c)
    if not 0x20 <= o < 0x60:
        raise ValueError(f"character {c!r} not in the program alphabet")
    return o


def tokenize_line(body):
    """One line's text (after the number) as the ROM's CRUNCH stores it: keywords outside quotes become
    tokens, the first table entry that matches wins (table order, not longest match); after REM the rest
    of the line, after DATA up to a colon, are left alone; '?' is PRINT."""
    out = bytearray()
    i, quote, mode = 0, False, None
    while i < len(body):
        c = body[i]
        if c == '"':
            quote = not quote
            out.append(0x22)
            i += 1
            continue
        if quote or mode == "rem":
            out.append(petscii_char(c))
            i += 1
            continue
        if mode == "data":
            if c == ":":
                mode = None
            out.append(petscii_char(c))
            i += 1
            continue
        if c == " " or "0" <= c <= ";":
            out.append(petscii_char(c))
            i += 1
            continue
        if c == "?":
            out.append(T_PRINT)
            i += 1
            continue
        for n, kw in enumerate(TOKENS):
            if body.startswith(kw, i):
                tok = 0x80 + n
                out.append(tok)
                i += len(kw)
                if tok == T_REM:
                    mode = "rem"
                elif tok == T_DATA:
                    mode = "data"
                break
        else:
            out.append(petscii_char(c))
            i += 1
    return bytes(out)


def tokenize(text, start=0x0801):
    """Program text -> (bytes as they sit in RAM from `start`, end address = the new $2D)."""
    out = bytearray()
    addr = start
    last = -1
    for ln in text.strip("\n").split("\n"):
        m = re.match(r"\s*(\d+)\s*(.*)$", ln)
        if not m:
            raise ValueError(f"no line number: {ln!r}")
        num = int(m.group(1))
        if not last < num <= 63999:
            raise ValueError(f"line number {num} out of order or range")
        last = num
        body = tokenize_line(m.group(2).rstrip())
        if len(body) > 250:
            raise ValueError(f"line {num} too long when tokenized ({len(body)} bytes)")
        nxt = addr + 4 + len(body) + 1
        out += bytes([nxt & 255, nxt >> 8, num & 255, num >> 8]) + body + b"\0"
        addr = nxt
    out += b"\0\0"
    return bytes(out), start + len(out)


def w_program(n):
    if not 1 <= n <= 4000:
        raise ValueError("W: N must be 1 to 4000 (k*7+i*13 must stay inside AND's 16-bit signed range)")
    return W_PROGRAM.format(n=n)


def parse_w(raw):
    raw = bytes(raw)
    d = {}
    for off, w, name in W_FIELDS:
        b = raw[off:off + w]
        if name == "magic":
            d[name] = b.decode("latin-1")
        elif name.startswith("ti_"):
            d[name] = int.from_bytes(b, "big")
        else:
            d[name] = int.from_bytes(b, "little")
    d["state_text"] = W_STATES.get(d["state"], f"unknown {d['state']}")
    return d


def judge_w(d, n):
    """-> (outcome, failed). outcome: pass | refused | FAIL | HANG | NO_RESULT."""
    if d["magic"] != W_MAGIC.decode():
        return "NO_RESULT", True
    if d["state"] == 4:
        return "refused", False
    if d["state"] == 2 and d["done"] == n and not (d["mismatches"] or d["st_errors"] or d["dos_errors"]):
        return "pass", False
    if d["state"] in (0, 1):
        return "HANG", True
    return "FAIL", True


# ---------------------------------------------------------------- the tools disk (arms B and R)
def tree_paths(tree):
    b = os.path.join(tree, "build")
    p = dict(prg=os.path.join(b, "breadbin.prg"), d64=os.path.join(b, "breadbin.d64"),
             lbl=os.path.join(b, "kernel.lbl"), lib=os.path.join(b, "lib", "breadbin.lib"),
             inc=os.path.join(tree, "include"), cfg=os.path.join(tree, "src", "prog.cfg"),
             cx=os.path.join(tree, "tools", "cx.py"), mkimage=os.path.join(tree, "tools"))
    missing = [k for k, v in p.items() if not os.path.exists(v)]
    if missing:
        raise SystemExit(f"--tree {tree}: missing {', '.join(missing)} (build the release tree with make)")
    return p


def build_program(src, out, p, work):
    name = os.path.splitext(os.path.basename(src))[0]
    o, l0, l1, lbl = (os.path.join(work, name + x) for x in (".o", ".0", ".1", ".lbl"))
    for cmd in (["ca65", "-g", "-I", p["inc"], src, "-o", o],
                ["ld65", "-C", p["cfg"], "-S", "0", "-Ln", lbl, "-o", l0, o, p["lib"]],
                ["ld65", "-C", p["cfg"], "-S", "256", "-o", l1, o, p["lib"]],
                [sys.executable, p["cx"], l0, l1, lbl, out]):
        subprocess.run(cmd, check=True)


def load_mkimage(p):
    """The release tree's mkimage (the one that built the image on the drive)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mkimage_release", os.path.join(p["mkimage"], "mkimage.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_tools(tree, out):
    """The tools disk: the release boot PRG (so the harness's load check still holds, and drive A could even
    boot it) and a c64fs root with wv and cksum. -> its path."""
    p = tree_paths(tree)
    mk = load_mkimage(p)
    with tempfile.TemporaryDirectory() as work:
        root = os.path.join(work, "root")
        os.makedirs(root)
        for prog in ("wv", "cksum"):
            build_program(os.path.join(HERE, "session5", prog + ".s"), os.path.join(root, prog), p, work)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        mk.build(out, p["prg"], root, [], rev="s5tools")
    return out


def posix_cksum(data):
    crc = 0
    def upd(b):
        nonlocal crc
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    for b in data:
        upd(b)
    n = len(data)
    while n:
        upd(n & 255)
        n >>= 8
    return (~crc) & 0xFFFFFFFF


def release_facts(p):
    """What R compares against, from the release image: /bin names, cksum and wc of /bin/as."""
    mk = load_mkimage(p)
    img = mk.load(p["d64"])
    fs = mk.FS(img)
    names = sorted(n.decode() for n, _ in fs.dir_entries(fs.lookup("/bin")) if not n.startswith(b"."))
    data = fs.read_file(fs.lookup("/bin/as"))
    words = len(re.findall(rb"[\x21-\xff]+", data))
    prg = open(p["prg"], "rb").read()
    first = img.cbm_read(img.cbm_files()[0][0])
    if first != prg:
        raise SystemExit("the first PRG on TREE/build/breadbin.d64 is not TREE/build/breadbin.prg")
    return dict(bin=names, cksum=f"{posix_cksum(data)} {len(data)} /bin/as",
                wc=f"{data.count(10):6d}{words:7d}{len(data):7d} /bin/as",
                d64_sha=hashlib.sha256(open(p["d64"], "rb").read()).hexdigest()[:16],
                prg_sha=hashlib.sha256(prg).hexdigest()[:16])


# ---------------------------------------------------------------- results
class Tsv:
    def __init__(self, path, columns):
        self.path, self.columns = path, columns
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        self.f = open(path, "a")
        if new:
            self.raw("\t".join(columns))

    def raw(self, line):
        self.f.write(line + "\n")
        self.f.flush()
        os.fsync(self.f.fileno())

    def comment(self, text):
        for l in str(text).splitlines() or [""]:
            self.raw("# " + l)

    def row(self, **kw):
        self.raw("\t".join(session.clean(kw.get(c, "")) for c in self.columns))

    def close(self):
        self.f.close()


class Tee:
    """stderr to the terminal and a file (the gate log)."""
    def __init__(self, a, path):
        self.a, self.f = a, open(path, "a")

    def write(self, s):
        self.a.write(s)
        self.f.write(s)
        self.f.flush()

    def flush(self):
        self.a.flush()
        self.f.flush()

    def close(self):
        self.f.close()


W_COLS = ["arm", "start_iso", "n", "outcome", "seconds", "wait_s", "state", "done", "mismatches", "st_errors",
          "dos_errors", "last_st", "last_dos", "fail_cycle", "fail_step", "index", "got", "want", "blocks_free",
          "ti_jiffies", "s_per_cycle", "screen_tail", "gate_races", "after_limit", "note"]
IO_COLS = ["io_nread", "io_nretry", "io_nfail", "io_neoi", "io_nwretry", "io_nwfail"]
IO_REC = ["io_ltrk", "io_lsct", "io_lidx", "io_ltry", "io_lst", "io_lwn"]
B_COLS = (["arm", "start_iso", "n", "outcome", "seconds", "wait_s", "wv_n", "wv_ok", "wv_mis", "wv_err",
           "wv_nobus", "wv_fail", "ticks", "s_per_cycle"] + IO_COLS + [c + "_delta" for c in IO_COLS[:3]]
          + ["io_last", "gate_races", "key_candidates", "d64_sha", "after_limit", "note"])
R_COLS = (["arm", "cycle", "start_iso", "outcome", "seconds", "load", "ls_bin", "sum_got", "sum_want", "cache"] + IO_COLS
          + ["io_last", "gate_races", "key_candidates", "d64_sha", "note"])
W_IO_SIZES = {"io_nwfail": 1}


def now_iso():
    """UTC: a local offset in committed results would say where the bench is."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def join_rows(lines):
    """Screen rows back into printed lines: a full 40-column row continues on the next one."""
    out, cur = [], ""
    for ln in lines:
        cur += ln
        if len(ln) < 40:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return "\n".join(out)


NET_ERRORS = (UltimateError, OSError)   # the link to the Ultimate, not the machine: a STOP, not a failure


class NetStop(session.StopSession):
    """A STOP because the link failed (its TSV row is written first)."""


class Clock:
    sleep = staticmethod(lambda s: time.sleep(s) if s > 0 else None)
    monotonic = staticmethod(time.monotonic)
    time = staticmethod(time.monotonic)

    def now(self):
        return time.monotonic()


# ---------------------------------------------------------------- machine access through the gate
def gated_read(t, address, length, timeout=120.0):
    """A read straight after an idle verdict (tools/ultimatetest.py's gate); TimeoutError if never idle."""
    deadline = t._time() + timeout
    while not t.bus_idle():
        if t._time() > deadline:
            raise TimeoutError(f"serial bus never idle for a read of ${address:04X} in {timeout:g} s\n" + t._recent())
    return bytes(t._dma_read(address, length))


def gated_write(t, address, data, timeout=120.0):
    deadline = t._time() + timeout
    while not t.bus_idle():
        if t._time() > deadline:
            raise TimeoutError(f"serial bus never idle for a write to ${address:04X}\n" + t._recent())
    t0 = t._clock.monotonic()
    try:
        t.u.writemem(address, data)
    finally:
        t._last_read = t._clock.monotonic()
        t._event(f"write ${address:04X} len {len(data)} t={t0:.3f}-{t._last_read:.3f}")
        t._gated_dma_done(f"write ${address:04X} len {len(data)}")


def read_iostat(t, labels, gated=True):
    """The IOSTAT counters and the last-timeout record in one short read (they are contiguous in blk.s)."""
    names = [n for n in IO_COLS + IO_REC if n in labels]
    if not names:
        return {}
    lo = min(labels[n] for n in names)
    hi = max(labels[n] + (2 if n in IO_COLS and n != "io_nwfail" else 1) for n in names)
    if hi - lo > 64:
        raise RuntimeError("IOSTAT labels are not contiguous")
    raw = gated_read(t, lo, hi - lo) if gated else bytes(t.u.readmem(lo, hi - lo))
    out = {}
    for n in names:
        o = labels[n] - lo
        out[n] = raw[o] | raw[o + 1] << 8 if n in IO_COLS and n != "io_nwfail" else raw[o]
    out["io_last"] = ";".join(f"{n[3:]}={out[n]:02x}" for n in IO_REC if n in out)
    return out


def capture(t, arm, labels, outdir, why, extra=None, kernel=True):
    """After a failure: short reads of $90, $BA, $DD00; with our kernel the IEC variables and the stack (the
    sidecar decode.py reads), IOSTAT; the screen (gated, then ungated if the bus never goes idle: the arm has
    already failed). Everything to <arm>.capture.txt. Never raises."""
    lines = [f"capture {arm} {now_iso()}: {why}"]
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {v}")

    def tryit(what, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            lines.append(f"{what}: unreadable ({type(e).__name__}: {session.clean(e)[:120]})")
            return None
    gate = "never idle in 30 s: reads ungated"
    try:
        deadline = t._time() + 30
        while not t.bus_idle():
            if t._time() > deadline:
                raise TimeoutError
        gate = "after an idle verdict"
    except Exception:  # noqa: BLE001
        pass
    lines.append(f"capture reads: {gate}, paced {IDLE_GAP} s apart")

    def readmem(a, n):
        t._clock.sleep(IDLE_GAP)
        return t.u.readmem(a, n)
    d = {}
    for n, a in (("st", 0x90), ("ba", 0xBA), ("dd00", 0xDD00)):
        v = tryit(n, lambda a=a: readmem(a, 1)[0])
        d[n] = "??" if v is None else f"{v:02x}"
    lines.append("bytes: " + " ".join(f"{k}={v}" for k, v in d.items()))
    if kernel and labels:
        base = labels.get("io_out")
        names = "io_out io_base io_b io_n io_to io_pend io_held io_eoi io_inf io_sx io_sy ie_dev ie_sa ie_len ie_len2".split()
        if base is not None and labels.get("io_n") == base + 3 and labels.get("ie_dev") == base + 11:
            v = tryit("iovars", lambda: readmem(base, 15))
            stk = tryit("stack", lambda: readmem(0x1C0, 64))
            if v is not None and stk is not None:
                img = os.path.join(outdir, f"{arm.lower()}-kernel.prg")
                with open(img + ".stall", "a") as f:
                    f.write(str({n: f"{b:02x}" for n, b in zip(names, v)}) + " stack:" + bytes(stk).hex() + "\n")
                shutil.copyfile(labels["__file__"], img[:-4] + ".lbl")
                r = subprocess.run([sys.executable, os.path.join(HERE, "decode.py"), img],
                                   capture_output=True, text=True)
                lines.append("decode.py:\n" + r.stdout + r.stderr)
        else:
            lines.append("iovars: label layout changed, not read")
        t._clock.sleep(IDLE_GAP)
        io = tryit("iostat", lambda: read_iostat(t, labels, gated=False))
        if io:
            lines.append("iostat: " + json.dumps(io))
        ticks = tryit("ticks", lambda: int.from_bytes(readmem(labels.get("ticks", 0x4A), 3), "little"))
        if ticks is not None:
            lines.append(f"ticks_jiffies={ticks}")
    scr = None
    try:
        scr = t.screen_lines(gate_timeout=30)
    except Exception as e:  # noqa: BLE001
        lines.append(f"screen: gate never idle in 30 s ({type(e).__name__}); read ungated")
        scr = tryit("screen", lambda: session.screen_lines(readmem(0x0400, 1000)))
    if scr is not None:
        lines.append("screen:\n" + "\n".join(scr))
    lines.append(f"gate_races={t.gate_races} key_candidates={t.gate_key_candidates}")
    try:
        lines.append(t._recent())
    except Exception:  # noqa: BLE001
        pass
    text = "\n".join(lines) + "\n"
    with open(os.path.join(outdir, f"{arm.lower()}.capture.txt"), "a") as f:
        f.write(text + "\n")
    return text


def labels_of(path):
    lb = session.read_labels(path)
    lb["__file__"] = path
    return lb


# ---------------------------------------------------------------- the arms
class Arms:
    def __init__(self, a, client, clock, out, target_factory):
        self.a, self.client, self.clock, self.out = a, client, clock, out
        self.target = target_factory
        self.dir = a.results
        os.makedirs(self.dir, exist_ok=True)

    # ---------------- shared
    def drain(self, t, probe, limit, every=30.0):
        """After a limit verdict (the arm has already failed): was the workload still moving? Gated probes
        every `every` s until the progress value is unchanged twice running, the workload says it finished,
        or `limit` s pass; so the config restore's reboot does not land in a write that is still going, and
        the record says whether the limit was too short. -> a note for the TSV."""
        t0, last, same, seen = self.clock.monotonic(), None, 0, []
        while self.clock.monotonic() - t0 < limit:
            self.clock.sleep(every)
            at = self.clock.monotonic() - t0
            try:
                value, finished = probe()
            except TimeoutError:
                seen.append(f"+{at:.0f}s busy")
                continue
            seen.append(f"+{at:.0f}s {value}")
            if finished:
                return "finished after the limit: " + "; ".join(seen)
            same = same + 1 if value == last else 0
            last = value
            if same >= 2:
                return "not moving: " + "; ".join(seen)
        return f"still moving {limit:.0f} s after the limit: " + "; ".join(seen)

    def w_probe(self, t):
        d = parse_w(gated_read(t, W_RESULT, W_LEN, timeout=20))
        return f"done={d['done']} state={d['state']}", d["state"] not in (0, 1)

    def b_probe(self, t, labels):
        """io_nread moves with every bus read (wv prints progress only every 50 cycles)."""
        io = read_iostat(t, labels)
        text = join_rows(t.screen_lines(gate_timeout=20))
        prog = re.findall(r"wv (?:c=\d+|end [^\n]*|fail [^\n]*)", text)
        return f"io_nread={io.get('io_nread')} {prog[-1] if prog else 'no progress line'}", "wv end" in text

    def net_stop(self, tsv, row, t0, stage, e):
        row.update(outcome="STOP", seconds=f"{self.clock.monotonic() - t0:.0f}",
                   note=f"{stage}: link to the Ultimate failed: {type(e).__name__}: {session.clean(e)[:160]}")
        tsv.row(**row)
        tsv.close()
        raise NetStop(row["note"])

    # ---------------- W
    def w(self, n):
        prog, end = tokenize(w_program(n))
        wait = self.a.wait if self.a.wait is not None else W_WAIT_BASE + n * W_CYCLE_EST * W_WAIT_FACTOR
        tsv = Tsv(os.path.join(self.dir, "w.tsv"), W_COLS)
        tsv.comment(f"arm W: N={n}, program {len(prog)} bytes at $0801-${end - 1:04X}, results at ${W_RESULT:04X}; "
                    f"wait {wait:.0f} s with no request; program sha256 {hashlib.sha256(prog).hexdigest()[:16]}")
        start, t0 = now_iso(), self.clock.monotonic()
        t = self.target(None)
        t._bus_idle_values = (0xC0, 0x90)          # the machine's KERNAL owns the bus throughout W
        row = dict(arm="W", start_iso=start, n=n, wait_s=f"{wait:.0f}")
        stage = "setup"
        try:
            t.u.resume()
            t.u.reset()
            self.clock.sleep(t.settle)
            t.wait_for("ready.", timeout=60)
            gated_write(t, W_RESULT, bytes(W_LEN))                 # no stale result can pass
            gated_write(t, 0x0801, prog)
            ptr = bytes([end & 255, end >> 8])
            gated_write(t, 0x2D, ptr * 3)                          # $2D, $2F, $31: start of variables, arrays, end
            gated_write(t, 0xAE, ptr)
            back = gated_read(t, 0x0801, len(prog))
            if back != prog:
                raise session.StopSession("the program read back differs from what was written: W not started")
            t.type("run\n")
            stage = "workload"
            t0 = self.clock.monotonic()
            self.out(f"W: running {n} cycles; no request to the machine for {wait:.0f} s", flush=True)
            self.clock.sleep(wait)
            stage = "result"
            raw = gated_read(t, W_RESULT, W_LEN)
        except TimeoutError as e:
            note = f"{stage}: {str(e).splitlines()[0]}"
            if stage == "setup":                   # nothing ran: not a result of the arm
                row.update(outcome="SETUP", seconds=f"{self.clock.monotonic() - t0:.0f}", note=note)
                capture(t, "W", None, self.dir, note, kernel=False)
                tsv.row(**row)
                tsv.close()
                self.out(f"W: SETUP problem, W did not start: {note}", flush=True)
                return EXIT_STOP
            # the bus was busy for the whole gate timeout at the limit: still running (or stuck mid-transfer)
            row.update(outcome="HANG", seconds=f"{self.clock.monotonic() - t0:.0f}", note=note,
                       after_limit=self.drain(t, lambda: self.w_probe(t), wait))
            capture(t, "W", None, self.dir, note, kernel=False)
            tsv.row(**row)
            tsv.close()
            return EXIT_FAIL
        except NET_ERRORS as e:
            self.net_stop(tsv, row, t0, stage, e)
        secs = self.clock.monotonic() - t0
        d = parse_w(raw)
        outcome, failed = judge_w(d, n)
        try:
            scr = t.screen_lines(gate_timeout=60)
        except TimeoutError:
            scr = ["<screen: bus never idle>"]
        text = join_rows(scr)
        if outcome == "HANG" and re.search(r"\?.*error", text):
            outcome = "FAIL"                       # BASIC stopped on an error (state stays 1): not a hang
            d["state_text"] = "BASIC error: " + next(l for l in text.splitlines() if re.search(r"\?.*error", l))
        elif outcome == "HANG":
            row["after_limit"] = self.drain(t, lambda: self.w_probe(t), wait)
        jiff = (d["ti_end"] - d["ti_start"]) % 5184000 if d["state"] in (2, 3, 4) else ""
        row.update(outcome=outcome, seconds=f"{secs:.0f}", state=d["state"], done=d["done"],
                   mismatches=d["mismatches"], st_errors=d["st_errors"], dos_errors=d["dos_errors"],
                   last_st=d["last_st"], last_dos=d["last_dos"], fail_cycle=d["cycle"] if d["state"] == 3 else "",
                   fail_step=d["step"] if d["state"] == 3 else "", index=d["index"], got=d["got"], want=d["want"],
                   blocks_free=d["blocks_free"], ti_jiffies=jiff,
                   s_per_cycle=f"{jiff / 60 / d['done']:.2f}" if jiff != "" and d["done"] else "",
                   screen_tail=" | ".join(l for l in scr if l)[-300:], gate_races=t.gate_races,
                   note=d["state_text"])
        if failed:
            capture(t, "W", None, self.dir, outcome, {"result": json.dumps(d), "raw": raw.hex()}, kernel=False)
        tsv.row(**row)
        tsv.close()
        self.out(f"W: {outcome} ({d['state_text']}): done {d['done']}/{n}, mismatches {d['mismatches']}, "
                 f"ST errors {d['st_errors']}, DOS errors {d['dos_errors']}, blocks free {d['blocks_free']}", flush=True)
        if outcome == "refused":
            self.out("W refused: the disk in drive 8 has no free CBM blocks; nothing was written. W needs a CBM "
                     "disk with free blocks (the Breadbin release disk has none).", flush=True)
            return EXIT_REFUSED
        return EXIT_FAIL if failed else EXIT_PASS

    # ---------------- boot helper (B and R)
    def target_for_boot(self):
        """A new UltimateTarget, not booted yet: the caller boots it inside its try, so a failed load still
        leaves a target to capture with (the boot load comes from the physical drive, bus 8; the tools disk
        is what is mounted in drive A, bus 9)."""
        return self.target(None)

    # ---------------- B
    def b(self, n, tools_d64, labels, facts):
        wait = self.a.wait if self.a.wait is not None else B_WAIT_BASE + n * B_CYCLE_EST * B_WAIT_FACTOR
        tsv = Tsv(os.path.join(self.dir, "b.tsv"), B_COLS)
        nread = labels["io_nread"]
        cmd = f"/mnt/wv {n} /home/s5b /bin/as {nread}"
        tsv.comment(f"arm B: N={n}; command {cmd!r}; wait {wait:.0f} s with no request; "
                    f"program experiments/iec-stall/session5/wv.s, built against the release tree")
        start, t0 = now_iso(), self.clock.monotonic()
        row = dict(arm="B", start_iso=start, n=n, wait_s=f"{wait:.0f}", d64_sha=facts["d64_sha"])
        t = self.target_for_boot()
        stage = "boot"
        try:
            t.boot(tools_d64)
            stage = "login"
            t.wait_shell(timeout=120)
            stage = "mount"
            got = t.run("mount 9 /mnt", timeout=60)
            if got.strip():
                raise RuntimeError(f"mount 9 /mnt said {got.strip()!r}")
            stage = "iostat before"
            io0 = read_iostat(t, labels)
            tk0 = int.from_bytes(gated_read(t, labels.get("ticks", 0x4A), 3), "little")
            stage = "typing"
            t.type("clear\n")                    # a clean screen, so the result is the only thing on it

            def cleared(ls):
                body = [l for l in ls if l]
                return len(body) == 1 and t.PROMPT.match(body[0]) is not None
            t._wait(cleared, 30, "clear")
            t.type(cmd + "\n")
            t0 = self.clock.monotonic()
            stage = "workload"
            self.out(f"B: running {n} cycles; no request to the machine for {wait:.0f} s", flush=True)
            self.clock.sleep(wait)
            scr = t.screen_lines(gate_timeout=120)
            stage = "iostat after"
            io1 = read_iostat(t, labels)
            tk1 = int.from_bytes(gated_read(t, labels.get("ticks", 0x4A), 3), "little")
        except session.StopSession:
            raise                                # a signal: the session stops, not this arm's failure
        except Exception as e:  # noqa: BLE001 - LoadError, TimeoutError, anything: a failure of this arm
            if isinstance(e, NET_ERRORS) and not isinstance(e, TimeoutError):
                t.close()
                self.net_stop(tsv, row, t0, stage, e)
            kind = type(e).__name__
            outcome = {"LoadError": "LOAD_ERROR", "TimeoutError": "HANG"}.get(kind, "ERROR")
            row.update(outcome=outcome, seconds=f"{self.clock.monotonic() - t0:.0f}",
                       note=f"{stage}: {kind}: {str(e).splitlines()[0] if str(e) else ''}")
            capture(t, "B", labels, self.dir, row["note"], kernel=stage != "boot")
            row.update(gate_races=t.gate_races, key_candidates=t.gate_key_candidates)
            t.close()
            tsv.row(**row)
            tsv.close()
            self.out(f"B: {outcome} at {stage}: {row['note']}", flush=True)
            return EXIT_FAIL
        secs = self.clock.monotonic() - t0
        text = join_rows(scr)
        m = re.search(r"wv end n=(\d+) ok=(\d+) mis=(\d+) err=(\d+) nobus=(\d+)", text)
        fl = re.search(r"wv fail [^\n]*", text)
        row.update(seconds=f"{secs:.0f}", ticks=(tk1 - tk0) & 0xFFFFFF, gate_races=t.gate_races,
                   key_candidates=t.gate_key_candidates, wv_fail=fl.group(0) if fl else "",
                   io_last=io1.get("io_last", ""))
        for c in IO_COLS:
            row[c] = io1.get(c, "")
        for c in IO_COLS[:3]:
            if c in io0 and c in io1:
                row[c + "_delta"] = (io1[c] - io0[c]) & 0xFFFF
        why = []
        if m:
            vn, ok, mis, err, nob = map(int, m.groups())
            row.update(wv_n=vn, wv_ok=ok, wv_mis=mis, wv_err=err, wv_nobus=nob,
                       s_per_cycle=f"{row['ticks'] / 60 / max(ok, 1):.2f}")
            if vn != n or ok != n or mis or err:
                why.append(f"wv: n={vn} ok={ok} mis={mis} err={err}")
        else:
            why.append("no 'wv end' line on the screen at the limit (hang)")
        if "panic" in text:
            why.append("panic on screen")
        if io1.get("io_nfail", 0) or io1.get("io_nwfail", 0):
            why.append(f"io_nfail={io1.get('io_nfail')} io_nwfail={io1.get('io_nwfail')}")
        if why:
            outcome = "HANG" if not m and "panic" not in text else "FAIL"
            row.update(outcome=outcome, note="; ".join(why))
            if outcome == "HANG":
                row["after_limit"] = self.drain(t, lambda: self.b_probe(t, labels), wait)
            capture(t, "B", labels, self.dir, row["note"], {"screen_at_limit": " | ".join(scr)})
            status = EXIT_FAIL
        elif row.get("wv_nobus"):
            row.update(outcome="INVALID", note=f"{row['wv_nobus']} read-backs did not reach the bus (io_nread unchanged)")
            status = EXIT_INVALID
        else:
            row.update(outcome="pass", note=f"retries: io_nretry={io1.get('io_nretry')} io_nwretry={io1.get('io_nwretry')}")
            status = EXIT_PASS
        tsv.row(**row)
        tsv.close()
        t.close()
        self.out(f"B: {row['outcome']}: {row.get('note', '')}; IOSTAT {json.dumps({c: io1.get(c) for c in IO_COLS})}",
                 flush=True)
        return status

    # ---------------- R
    def r(self, n, tools_d64, labels, facts):
        tsv = Tsv(os.path.join(self.dir, "r.tsv"), R_COLS)
        sum_cmd = "/mnt/cksum /bin/as" if self.a.sum == "cksum" else "wc /bin/as"
        want_sum = facts["cksum"] if self.a.sum == "cksum" else facts["wc"]
        tsv.comment(f"arm R: N={n}; sum command {sum_cmd!r}, expected {want_sum!r}; /bin: {len(facts['bin'])} names; "
                    f"release d64 sha256 {facts['d64_sha']}, prg {facts['prg_sha']}")
        first_ls = None
        for k in range(1, n + 1):
            start, t0 = now_iso(), self.clock.monotonic()
            row = dict(arm="R", cycle=k, start_iso=start, d64_sha=facts["d64_sha"], sum_want=want_sum)
            t, stage, why = self.target_for_boot(), "boot", []
            try:
                t.boot(tools_d64)
                row["load"] = "verified"
                stage = "login"
                t.wait_shell(timeout=120)
                stage = "mount"
                got = t.run("mount 9 /mnt", timeout=60)
                if got.strip():
                    why.append(f"mount 9 /mnt said {got.strip()!r}")
                stage = "ls"
                ls = t.run("ls /bin", timeout=90)
                toks = sorted(ls.split())
                if toks != facts["bin"]:
                    miss = sorted(set(facts["bin"]) - set(toks))
                    more = sorted(set(toks) - set(facts["bin"]))
                    why.append(f"ls /bin: missing {miss} extra {more}")
                    row["ls_bin"] = "WRONG"
                elif first_ls is not None and ls != first_ls:
                    why.append("ls /bin text differs from cycle 1")
                    row["ls_bin"] = "DIFFERS"
                else:
                    row["ls_bin"] = f"ok {len(toks)}"
                first_ls = first_ls if first_ls is not None else ls
                stage = "sum"
                got = t.run(sum_cmd, timeout=90).strip()
                row["sum_got"] = got
                if got.split() != want_sum.split():          # wc right-aligns its counts
                    why.append(f"{sum_cmd}: {got!r}")
                stage = "cache"                  # a record only (hits vs bus reads: where ls and the sum came from)
                row["cache"] = " ".join(t.run("cache", timeout=60).split())
                stage = "iostat"
                io = read_iostat(t, labels)
                for c in IO_COLS:
                    row[c] = io.get(c, "")
                row["io_last"] = io.get("io_last", "")
                if io.get("io_nfail", 0) or io.get("io_nwfail", 0):
                    why.append(f"io_nfail={io.get('io_nfail')} io_nwfail={io.get('io_nwfail')}")
                scr = "\n".join(t.screen_lines(gate_timeout=60))
                if "panic" in scr:
                    why.append("panic on screen")
            except session.StopSession:
                raise
            except Exception as e:  # noqa: BLE001
                if isinstance(e, NET_ERRORS) and not isinstance(e, TimeoutError):
                    t.close()
                    self.net_stop(tsv, row, t0, stage, e)
                kind = type(e).__name__
                outcome = {"LoadError": "LOAD_ERROR", "TimeoutError": "HANG"}.get(kind, "ERROR")
                if stage == "boot":
                    row["load"] = outcome
                why.insert(0, f"{stage}: {kind}: {str(e).splitlines()[0] if str(e) else ''}")
                row["outcome"] = outcome
            row["seconds"] = f"{self.clock.monotonic() - t0:.0f}"
            row.update(gate_races=t.gate_races, key_candidates=t.gate_key_candidates)
            if why:
                row.setdefault("outcome", "FAIL")
                row["note"] = "; ".join(why)
                capture(t, "R", labels, self.dir, f"cycle {k}: {row['note']}", kernel=stage != "boot")
                tsv.row(**row)
                tsv.close()
                t.close()
                self.out(f"R cycle {k}: {row['outcome']}: {row['note']}", flush=True)
                return EXIT_FAIL
            row["outcome"] = "pass"
            tsv.row(**row)
            t.close()
            self.out(f"R cycle {k}/{n}: pass ({row['seconds']} s; io_nread {row.get('io_nread')} "
                     f"io_nretry {row.get('io_nretry')} io_nwretry {row.get('io_nwretry')})", flush=True)
        tsv.close()
        return EXIT_PASS


# ---------------------------------------------------------------- plan, main
def parse_plan(text):
    out = []
    for ln in text.splitlines():
        ln = ln.split("#")[0].strip()
        if not ln:
            continue
        f = ln.split()
        if len(f) != 3 or f[1] not in ("W", "B", "R") or not f[2].isdigit():
            raise SystemExit(f"plan line {ln!r}: want BLOCK ARM COUNT, ARM one of W B R")
        out.append((f[0], f[1], int(f[2])))
    return out


DISK_PROMPT = {
    "W": "Arm W writes and scratches a file S5W on the disk in drive 8 and needs free CBM blocks (the release "
         "disk has none: W refuses on it). Put the W disk in drive 8, then press Enter: ",
    "B": "Arms B and R need the release image on the disk in drive 8 (B writes /home/s5b on it). Put the release "
         "disk in drive 8, then press Enter: ",
}


def main(argv=None, client=None, clock=None, ask=None, out=print, target_factory=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("w", "b", "r", "plan", "tools"))
    ap.add_argument("plan", nargs="?")
    ap.add_argument("--tree", required=True, help="the built release worktree")
    ap.add_argument("-n", type=int, help="cycles (default W 300, B 300, R 50)")
    ap.add_argument("--results", default=RESULTS)
    ap.add_argument("--tools-d64", help="default RESULTS/tools.d64, built now")
    ap.add_argument("--wait", type=float, help="W, B: seconds with no request (default from the VICE estimate)")
    ap.add_argument("--sum", choices=("cksum", "wc"), default="cksum")
    ap.add_argument("--reboot-wait", type=float, default=15)
    ap.add_argument("--no-prompt", action="store_true", help="no disk-swap prompts (plan)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rev", help="the frozen release revision: TREE/build/rev.txt must say exactly this "
                                  "(and not end in '+', a dirty build); required to run")
    a = ap.parse_args(argv)
    clock = clock or Clock()
    if a.cmd == "plan":
        if not a.plan:
            raise SystemExit("plan needs a plan file")
        order = parse_plan(open(a.plan).read())
    else:
        order = [("-", a.cmd.upper(), a.n or DEFAULT_N[a.cmd.upper()])] if a.cmd != "tools" else []
    p = tree_paths(a.tree)
    revf = os.path.join(a.tree, "build", "rev.txt")
    rev = open(revf).read().strip() if os.path.exists(revf) else None
    if a.cmd != "tools" and not a.dry_run:
        if rev is None or rev.endswith("+") or a.rev is None or rev != a.rev:
            raise SystemExit(f"refusing: TREE/build/rev.txt is {rev!r}, --rev {a.rev!r}: the tree must be a clean "
                             "build of the frozen release (rev.txt without '+', given again as --rev)")
        arms_in = {arm for _, arm, _ in order}
        if a.no_prompt and "W" in arms_in and arms_in & {"B", "R"}:
            raise SystemExit("refusing --no-prompt: this plan needs a disk swap between W (scratch disk) and B/R "
                             "(release disk)")
    if a.dry_run:
        for blk, arm, n in order:
            out(f"block {blk}: arm {arm} x {n}")
        return 0
    os.makedirs(a.results, exist_ok=True)
    tools_d64 = a.tools_d64 or os.path.join(a.results, "tools.d64")
    if any(arm in "BR" for _, arm, _ in order) or a.cmd == "tools":
        if not a.tools_d64:
            build_tools(a.tree, tools_d64)
        facts = release_facts(p)
        out(f"tools disk {tools_d64}; expected cksum {facts['cksum']!r}; /bin {len(facts['bin'])} names", flush=True)
    else:
        facts = None
    if a.cmd == "tools":
        return 0
    bus = os.environ.setdefault("BREADBIN_ULTIMATE_BUS", "8")
    if bus != "8":
        raise SystemExit(f"BREADBIN_ULTIMATE_BUS={bus}: session 5 boots from the physical 1541 on bus 8")
    os.environ["BREADBIN_ULTIMATE_GATELOG"] = "1"
    labels = labels_of(p["lbl"])
    missing = [x for x in IO_COLS if x not in labels]
    if missing:
        raise SystemExit(f"kernel.lbl has no {missing}: not an IOSTAT release build")
    if client is None:
        from ultimate import Ultimate
        client = Ultimate.from_env()
    if target_factory is None:
        from ultimatetest import UltimateTarget

        def target_factory(image):
            return UltimateTarget(image, client=client)
    if ask is None:
        ask = (lambda text: "") if a.no_prompt else input

    def prompt(text):
        try:
            return ask(text)
        except EOFError:
            raise session.StopSession("no terminal for the disk-swap prompt (EOF): run the arms one by one") from None
    log = Tsv(os.path.join(a.results, "session5.log.tsv"), ["note"])
    guard = session.ConfigGuard(client, clock, log, a.reboot_wait)
    cur = guard.get(*session.KERNAL_ITEM)
    if cur != session.NORMAL_KERNAL:
        log.close()
        raise SystemExit(f"refusing to start: the Kernal ROM is {cur!r}, expected {session.NORMAL_KERNAL!r}")
    log.comment(f"session 5 {now_iso()}: {a.cmd} {order}; tree build {rev}")
    arms = Arms(a, client, clock, out, target_factory)

    def on_signal(signum, frame):
        raise session.StopSession(f"signal {signum}")
    old = {}
    for sg in (signal.SIGTERM, signal.SIGHUP):
        try:
            old[sg] = signal.signal(sg, on_signal)
        except ValueError:
            pass
    status = EXIT_STOP
    prev = None
    try:
        guard.apply()
        for blk, arm, n in order:
            if a.cmd == "plan" and arm in DISK_PROMPT and prev != ("W" if arm == "W" else "BR"):
                prompt(DISK_PROMPT[arm])
            prev = "W" if arm == "W" else "BR"
            err = sys.stderr
            tee = Tee(err, os.path.join(a.results, f"{arm.lower()}.gate.log"))
            sys.stderr = tee
            try:
                log.comment(f"arm {arm} x {n} start {now_iso()}")
                if arm == "W":
                    status = arms.w(n)
                elif arm == "B":
                    status = arms.b(n, tools_d64, labels, facts)
                else:
                    status = arms.r(n, tools_d64, labels, facts)
                log.comment(f"arm {arm} end {now_iso()}: exit {status}")
            finally:
                sys.stderr = err
                tee.close()
            if status != EXIT_PASS:
                out(f"stopping after arm {arm} (exit {status}): nothing more runs until it is understood. "
                    "The protocol runs B and R after a W failure once it is understood: run them with the "
                    "b and r subcommands.", flush=True)
                break
    except (session.StopSession, KeyboardInterrupt) as e:
        out(f"STOP: {e}", flush=True)
        log.comment(f"STOP: {e}")
        status = EXIT_STOP
    finally:
        quiet = session.ignore_signals()
        try:
            guard.restore()
        finally:
            session.restore_signals(quiet)
            for sg, h in old.items():
                signal.signal(sg, h)
            log.close()
    if guard.kernal_not_restored:
        return session.EXIT_KERNAL_NOT_RESTORED
    return status


if __name__ == "__main__":
    sys.exit(main())
