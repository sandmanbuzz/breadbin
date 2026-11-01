"""Boot a Breadbin kernel image (build/breadbin.prg) by DMA with the root on device 8, wait for
the login prompt, and on a stall dump the IEC driver's variables and the stack.

    BREADBIN_ULTIMATE=host python3 dmaboot.py IMAGE.prg     # needs IMAGE.lbl next to it
    BLANK=1 ...                                              # screen off (no badlines) at start

Loading by DMA leaves the physical drive untouched, so a C64 reset does not reset it, and
"DMA Load Mimics ID: 8" makes $BA = 8. Prints one line: OK, or STUCK with $90 ($02 is a receive
timeout) and $DD00 ($87: the drive holds CLK, we hold nothing). A stall appends to IMAGE.prg.stall;
decode.py reads it. No DMA read happens until 20 s after the start, so the first seconds (the
root mount) are never disturbed; polling during a disk load can corrupt it.
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_basic import u  # noqa: E402

img = sys.argv[1]
u.resume()
t0 = time.time()
u.run_prg(open(img, "rb").read())
if os.environ.get("BLANK"):
    for _ in range(40):                      # DEN is bit 4 of $D011; ~14 s of tiny writes
        d = u.readmem(0xD011, 1)[0]
        if d & 0x10:
            u.writemem(0xD011, bytes([d & 0xEF]))
        time.sleep(0.35)


def lines():
    d = u.readmem(0x0400, 1000)
    row = lambda r: "".join(chr(c + 64) if 1 <= c <= 26 else chr(c) if 32 <= c < 64 else " "
                            for c in d[r * 40:(r + 1) * 40]).rstrip().lower()
    return [l for l in (row(r) for r in range(25)) if l]


time.sleep(max(0, 20 - (time.time() - t0)))
while time.time() - t0 < 170:
    if any("login:" in l for l in lines()):
        print(f"OK    login after {time.time() - t0:.0f}s")
        sys.exit(0)
    time.sleep(10)
dd = u.readmem(0xDD00, 1)[0]
lbl = {m.group(2): int(m.group(1), 16) for l in open(img[:-4] + ".lbl")
       for m in [re.match(r"al ([0-9A-F]{6}) \.(\S+)", l)] if m}
base = lbl["io_out"]            # the variables move with every build: read them from the labels
names = "io_out io_base io_b io_n io_to io_pend io_held io_eoi io_inf io_sx io_sy ie_dev ie_sa ie_len ie_len2".split()
assert lbl["io_n"] == base + 3 and lbl["ie_dev"] == base + 11, "variable layout changed: fix the dump"
v = u.readmem(base, 15)
open(img + ".stall", "a").write(str({n: f"{b:02x}" for n, b in zip(names, v)})
                                 + " stack:" + u.readmem(0x1C0, 64).hex() + "\n")
print(f"STUCK after 170s; last line {lines()[-1]!r}; $90={u.readmem(0x90, 1).hex()} "
      f"$BA={u.readmem(0xBA, 1).hex()} $DD00={dd:02x}")
