"""Snapshot the C64's hardware state by DMA (no register is read that a read would change) and compare two snapshots.

    BREADBIN_ULTIMATE=host python3 envdump.py snap NAME            # dump into $SCRATCH/env-NAME.json
    python3 envdump.py diff A B                                    # registers that differ (volatile ones are marked ~)
Use it on a machine that is stopped (a stalled kernel) and on a stock BASIC machine, to see what the kernel changed.
Skipped: the CIA interrupt control registers ($DC0D, $DD0D) and VIC $D019, which a read can clear, and the timers' counters
(they change). Those are listed as volatile in the diff if they differ.
"""
import json
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

SKIP = {0xDC0D, 0xDD0D}
VOLATILE = {0xDC04, 0xDC05, 0xDC06, 0xDC07, 0xDC08, 0xDC09, 0xDC0A, 0xDC0B, 0xDD04, 0xDD05, 0xDD06, 0xDD07, 0xDD08,
            0xDD09, 0xDD0A, 0xDD0B, 0xD012, 0xD011, 0xD019, 0xD01E, 0xD01F, 0xD41B, 0xD41C, 0xDC00, 0xDC01, 0xDD00}
RANGES = [(0x0000, 0x0002), (0x0090, 0x00B0), (0x0314, 0x0320), (0x0286, 0x0287), (0xD000, 0xD02F),
          (0xD400, 0xD41D), (0xDC00, 0xDC10), (0xDD00, 0xDD10), (0xFFFA, 0x10000)]


def snap(name):
    from bench_basic import u
    d = {}
    for lo, hi in RANGES:
        data = u.readmem(lo, hi - lo)
        for i, b in enumerate(data):
            if lo + i not in SKIP:
                d[f"{lo + i:04X}"] = b
    path = os.path.join(os.environ.get("SCRATCH", "."), f"env-{name}.json")
    json.dump(d, open(path, "w"))
    print(f"{len(d)} bytes saved to {path}")


def diff(a, b):
    w = os.environ.get("SCRATCH", ".")
    A, B = (json.load(open(os.path.join(w, f"env-{x}.json"))) for x in (a, b))
    n = 0
    for k in sorted(A):
        if A[k] != B.get(k):
            n += 1
            mark = "~" if int(k, 16) in VOLATILE else " "
            print(f"{mark} ${k}: {a} {A[k]:02X}   {b} {B[k]:02X}")
    print(n, "bytes differ")


if sys.argv[1] == "snap":
    snap(sys.argv[2])
else:
    diff(sys.argv[2], sys.argv[3])
