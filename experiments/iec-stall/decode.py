"""Decode IMAGE.prg.stall written by dmaboot.py, using IMAGE.lbl (ld65 -Ln output of that build).
The stack page is shown as return addresses; only the top few are live. io_n is the number of
bits still expected in the byte being received when the first timeout hit.

    python3 decode.py IMAGE.prg [...]
"""
import bisect
import re
import sys

for img in sys.argv[1:]:
    syms = sorted({(int(m.group(1), 16), m.group(2)) for l in open(img[:-4] + ".lbl")
                   for m in [re.match(r"al ([0-9A-F]{6}) \.(\S+)", l)] if m})
    addrs = [a for a, _ in syms]

    def lab(a):
        i = bisect.bisect_right(addrs, a) - 1
        return f"{syms[i][1]}+{a - syms[i][0]}"

    for ln in open(img + ".stall").read().strip().split("\n"):
        d, _, stk = ln.partition(" stack:")
        print(img, d)
        st = bytes.fromhex(stk)
        out = [lab(((st[i] << 8) | st[i - 1]) + 1) for i in range(len(st) - 1, 0, -1)
               if 0x8000 <= ((st[i] << 8) | st[i - 1]) + 1 < 0xD000]
        print("    stack:", " < ".join(out[:9]))
