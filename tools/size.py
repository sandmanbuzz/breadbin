#!/usr/bin/env python3
"""Where the kernel's bytes go: per module, from build/kernel.map.

    make size          (or: python3 tools/size.py [build/kernel.map])

Prints code, read-only data and BSS per module, the totals, and the headroom
left below the syscall table at $CF00. Run it in every story that adds or
removes kernel code, and quote the numbers in the commit message.
"""
import os
import re
import sys

KRAM_TOP = 0xCF00      # the syscall jump table
HI_TOP = 0xFFFA        # the hardware vectors


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "build/kernel.map"
    text = open(path).read()
    mods = {}
    sect = text.split("Modules list:")[1].split("Segment list:")[0]
    cur = None
    for line in sect.splitlines():
        m = re.match(r"^(\S+\.o):", line)
        if m:
            cur = m.group(1)[:-2]
            mods[cur] = {}
            continue
        m = re.match(r"^\s+(\w+)\s+Offs=\w+\s+Size=([0-9A-F]+)", line)
        if m and cur:
            mods[cur][m.group(1)] = int(m.group(2), 16)
    cols = ("CODE", "RODATA", "DATA", "BSS")
    print(f"{'module':10s}" + "".join(f"{c:>8s}" for c in cols) + f"{'total':>8s}")
    tot = dict.fromkeys(cols, 0)
    for name, s in sorted(mods.items(), key=lambda kv: -sum(kv[1].values())):
        row = [s.get(c, 0) for c in cols]
        for c, v in zip(cols, row):
            tot[c] += v
        print(f"{name:10s}" + "".join(f"{v:8d}" for v in row) + f"{sum(row):8d}")
    print(f"{'total':10s}" + "".join(f"{tot[c]:8d}" for c in cols) + f"{sum(tot.values()):8d}")
    def end(seg):
        m = re.search(r"^%s\s+([0-9A-F]+)\s+([0-9A-F]+)" % seg, text, re.M)
        return int(m.group(2), 16) if m else None
    code_end = max(end(sg) or 0 for sg in ("CODE", "RODATA", "DATA"))
    bss_end = end("BSS")
    print(f"\ncode and data end at ${code_end:04X}; room below ${KRAM_TOP:04X}: {KRAM_TOP - code_end - 1} bytes")
    if bss_end and bss_end >= 0xE000:
        print(f"BSS ends at ${bss_end:04X}; room below ${HI_TOP:04X}: {HI_TOP - bss_end - 1} bytes")
    elif bss_end:
        print(f"BSS ends at ${bss_end:04X} (in the code region)")
    progs = "build/root/bin"
    if os.path.isdir(progs):
        sizes = sorted(((os.path.getsize(os.path.join(progs, f)), f) for f in os.listdir(progs)), reverse=True)
        print("largest programs: " + ", ".join(f"{f} {n}" for n, f in sizes[:6]))


if __name__ == "__main__":
    main()
