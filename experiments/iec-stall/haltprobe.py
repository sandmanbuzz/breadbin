"""Hardware driver for haltprobe.s: is the C64's CPU halted for long stretches (100-600 us)?

Loads the probe at $C000 on the stock KERNAL's BASIC, starts it with SYS 49152 and runs five arms,
each starting with the results cleared:

  1. idle           no REST traffic at all
  2. read 1 byte    every 1 s
  3. read 1 byte    every 0.1 s
  4. read 1000      bytes every 2 s
  5. REU            a 256-byte C64->REU transfer every REUEV x 256 loops (skipped if no REU)

and prints one row per arm: loops, the histogram of stolen cycles (delta - loop period), the
largest gap in cycles and microseconds. Changes no configuration; leaves the machine resumed.

    BREADBIN_ULTIMATE=host tools/with-lock -r ultimate -- \
        python3 experiments/iec-stall/haltprobe.py [--idle 60 --r1 60 --r01 30 --r1000 60 --reu 30] [--blank]

Importable: run(u, ...) takes any object with the Ultimate client's methods (tools/fake_ultimate.py
stands in for it in tools/test_haltprobe.py).
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "tools"))

BASE = 0xC000
MODE, STOP, LIMLO, LIMHI, REUEV, CLEAR = 0xC800, 0xC801, 0xC802, 0xC803, 0xC804, 0xC805
RES = 0xC810                      # results block: $C810-$C843
NBUCKET = 9
LABELS = ["<=20", "21-40", "41-65", "66-100", "101-200", "201-400", "401-800", "801-1600", ">1600"]
FLAG_BLANK, FLAG_REU = 1, 2


def assemble(work=None):
    """haltprobe.s -> raw bytes for $C000 (needs cc65)."""
    work = work or tempfile.mkdtemp(prefix="haltprobe")
    obj, binf = os.path.join(work, "haltprobe.o"), os.path.join(work, "haltprobe.bin")
    subprocess.run(["ca65", os.path.join(here, "haltprobe.s"), "-o", obj], check=True)
    subprocess.run(["ld65", "-t", "none", "-S", hex(BASE), "-o", binf, obj], check=True)
    with open(binf, "rb") as f:
        return f.read()


def parse(block):
    """The 64 bytes at $C810 -> dict."""
    le = lambda o, n: int.from_bytes(block[o:o + n], "little")      # noqa: E731
    r = {"done": block[0], "reu_present": block[1], "xfers": le(2, 2), "max": le(4, 2),
         "max_at": le(6, 2), "timer_b": le(8, 2), "timer_a_end": le(10, 2), "p": block[12],
         "running": block[13]}
    r["buckets"] = [le(0x10 + 4 * i, 4) for i in range(NBUCKET)]
    return r


def feed(u, text, timeout=10):
    """PETSCII into the KERNAL key buffer by DMA, 8 keys at a time (as bench_basic.feed)."""
    codes = [0x0D if c == "\n" else (ord(c.upper()) if c.isalpha() else ord(c)) for c in text]
    for i in range(0, len(codes), 8):
        chunk = bytes(codes[i:i + 8])
        deadline = time.time() + timeout
        while True:
            u.pause()
            if u.readmem(0xC6, 1)[0] == 0:
                u.writemem(0x0277, chunk)
                u.writemem(0xC6, bytes([len(chunk)]))
                u.resume()
                break
            u.resume()
            if time.time() > deadline:
                raise RuntimeError("the probe did not start (the key buffer never drained: not at BASIC?)")
            time.sleep(0.05)


def start(u, code, boot_wait=6.0, blank=False, reuev=1, say=print, timeout=20):
    """Reset, wait for BASIC, DMA the probe in, SYS it, wait until it reports RUNNING."""
    u.resume()
    u.reset()
    time.sleep(boot_wait)
    u.pause()
    u.writemem(BASE, code)
    u.writemem(MODE, bytes([FLAG_BLANK if blank else 0, 0, 0, 0, reuev, 0]))
    u.writemem(RES, bytes(0x44))
    u.resume()
    feed(u, "sys49152\n", timeout=timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if u.readmem(RES + 0x0D, 1)[0]:
            say("probe running")
            return
        time.sleep(0.2)
    raise RuntimeError("the probe did not start (screen not at BASIC? reset and retry)")


def clear(u, settle=0.3):
    """Zero the histogram. No read after it: the request is acknowledged by CLEAR going to 0,
    which the end-of-arm read checks."""
    u.writemem(CLEAR, b"\x01")
    time.sleep(settle)


def arm(u, name, seconds, stimulus=None, mode=None, settle=0.3, sleep=time.sleep, clock=time.time):
    """One arm: set the mode byte (if given), clear, run the stimulus for `seconds`, read."""
    if mode is not None:
        u.writemem(MODE, bytes([mode]))
    clear(u, settle)
    t0 = clock()
    n = 0
    if stimulus is None:
        sleep(seconds)
    else:
        interval, length = stimulus
        nxt = t0
        while clock() - t0 < seconds:
            u.readmem(0x0400, length)           # screen RAM: harmless
            n += 1
            nxt += interval
            sleep(max(0.0, nxt - clock()))
    wall = clock() - t0
    block = u.readmem(RES, 0x44)
    r = parse(block)
    r.update(name=name, wall=wall, requests=n, clear_acked=u.readmem(CLEAR, 1)[0] == 0)
    return r


def table(rows, pnom):
    out = []
    head = f"{'arm':<14}{'wall s':>7}{'reqs':>6}{'loops':>11} " + "".join(f"{l:>9}" for l in LABELS[1:]) \
           + f"{'max cyc':>9}{'max us':>8}"
    out.append(head)
    for r in rows:
        if r.get("skipped"):
            out.append(f"{r['name']:<14}  skipped: {r['skipped']}")
            continue
        b = r["buckets"]
        loops = sum(b)
        extra = max(r["max"] - pnom, 0) if r["max"] else 0
        out.append(f"{r['name']:<14}{r['wall']:>7.1f}{r['requests']:>6}{loops:>11} "
                   + "".join(f"{c:>9}" for c in b[1:]) + f"{r['max']:>9}{r['max'] / 0.985:>8.0f}"
                   + ("" if r["clear_acked"] else "  (clear NOT acked)")
                   + (f"  [{r['xfers']} REU xfers]" if r.get("xfers") else ""))
    out.append(f"loops = sum of all buckets (bucket '<=20' is the quiet loop, one per {pnom} cycles); columns are "
               f"stolen cycles = delta - {pnom}. 'max cyc' is the raw delta of the worst loop "
               f"(its stolen part: that minus {pnom}); us at 0.985 MHz (PAL).")
    return "\n".join(out)


def run(u, idle=60, r1=60, r01=30, r1000=60, reu=30, blank=False, reuev=1, boot_wait=6.0,
        settle=0.3, say=print, sleep=time.sleep, clock=time.time, code=None, start_timeout=20):
    """All five arms; returns the rows. Always stops the probe and resumes the machine."""
    code = code if code is not None else assemble()
    blankflag = FLAG_BLANK if blank else 0
    rows = []
    try:
        start(u, code, boot_wait=boot_wait, blank=blank, reuev=reuev, say=say, timeout=start_timeout)
        pre = u.readmem(RES, 0x44)
        pnom = parse(pre)["p"]
        rows.append(arm(u, "1 idle", idle, None, blankflag, settle, sleep, clock))
        rows.append(arm(u, "2 1B/1s", r1, (1.0, 1), blankflag, settle, sleep, clock))
        rows.append(arm(u, "3 1B/0.1s", r01, (0.1, 1), blankflag, settle, sleep, clock))
        rows.append(arm(u, "4 1000B/2s", r1000, (2.0, 1000), blankflag, settle, sleep, clock))
        have_reu = u.readmem(RES + 1, 1)[0]
        if have_reu:
            rows.append(arm(u, "5 REU", reu, None, blankflag | FLAG_REU, settle, sleep, clock))
        else:
            rows.append({"name": "5 REU", "skipped": "no REU found by the probe"})
        say(table(rows, pnom))
        return rows
    finally:
        try:
            u.writemem(STOP, b"\x01")
            for _ in range(40):
                time.sleep(0.1)
                if u.readmem(RES, 1)[0]:
                    break
        finally:
            u.resume()          # whatever happened, leave the machine running


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--idle", type=float, default=60)
    ap.add_argument("--r1", type=float, default=60)
    ap.add_argument("--r01", type=float, default=30)
    ap.add_argument("--r1000", type=float, default=60)
    ap.add_argument("--reu", type=float, default=30)
    ap.add_argument("--reuev", type=int, default=1, help="REU transfer every N x 256 loops")
    ap.add_argument("--blank", action="store_true", help="screen blanked: no badlines")
    a = ap.parse_args(argv)
    from ultimate import Ultimate
    u = Ultimate.from_env()
    run(u, a.idle, a.r1, a.r01, a.r1000, a.reu, a.blank, a.reuev)


if __name__ == "__main__":
    main()
