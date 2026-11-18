#!/usr/bin/env python3
# /// block
# name = "routine-sizes"
# summary = "Byte span of each global label in an ld65 build, per segment, from the -Ln and -m files."
# effects = "write-workspace"
# example = ["--lbl", "build/kernel.lbl", "--map", "build/kernel.map", "--top", "5"]
#
# [returns]
# keys = ["segments", "top", "total_labels", "out"]
# doc = "segments: {name: [start, end, size]} for segments with code; top: the N largest spans as {name, seg, addr, size}; a span runs from a global label to the next label of any kind that is global, or the segment end; cheap locals (@x) never start a span. --out writes every span as TSV (seg, addr, size, name), largest first"
#
# [params]
# lbl = { type = "path", required = true, help = "ld65 -Ln label file" }
# map = { type = "path", required = true, help = "ld65 -m map file (for the segment list)" }
# segs = { type = "str", default = "IECBUS,CODE,RODATA,DATA,JUMPTAB,CODEHI,INIT,BSS", help = "Comma-separated segments to cover" }
# top = { type = "int", default = 15, help = "How many of the largest spans to print" }
# out = { type = "str", default = "", help = "Write the full TSV here" }
#
# [provenance]
# created = "2026-11-18"
# source = "local"
# ///
"""Where the bytes are: the size of every routine and table, without dumping the listing."""
import argparse
import json
import re
import sys


def segments(path, wanted):
    out = {}
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    block = text.split("Segment list:", 1)[1].split("Exports list", 1)[0]
    for m in re.finditer(r"^(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+([0-9A-F]{6})", block, re.M):
        name, start, end, size = m.group(1), int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16)
        if name in wanted and size:
            out[name] = (start, end, size)
    return out


def labels(path):
    seen = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            p = line.split()
            if len(p) == 3 and p[0] == "al":
                name = p[2].lstrip(".")
                if "@" in name or name.startswith("__"):
                    continue
                seen.setdefault(int(p[1], 16), name)   # first name at an address wins
    return sorted(seen.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lbl", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--segs", default="IECBUS,CODE,RODATA,DATA,JUMPTAB,CODEHI,INIT,BSS")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    try:
        segs = segments(a.map, set(a.segs.split(",")))
        labs = labels(a.lbl)
    except (OSError, IndexError) as e:
        print(json.dumps({"error": str(e)}))
        return 1
    spans = []
    for seg, (start, end, _) in segs.items():
        inside = [(ad, n) for ad, n in labs if start <= ad <= end]
        if not inside or inside[0][0] != start:
            inside.insert(0, (start, f"<{seg} start>"))
        for i, (ad, n) in enumerate(inside):
            nxt = inside[i + 1][0] if i + 1 < len(inside) else end + 1
            spans.append({"name": n, "seg": seg, "addr": f"${ad:04X}", "size": nxt - ad})
    spans.sort(key=lambda s: -s["size"])
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            for s in spans:
                fh.write(f"{s['seg']}\t{s['addr']}\t{s['size']}\t{s['name']}\n")
    print(json.dumps({"segments": {k: list(v) for k, v in segs.items()},
                      "top": spans[:a.top], "total_labels": len(spans), "out": a.out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
