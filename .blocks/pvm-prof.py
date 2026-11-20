#!/usr/bin/env python3
# /// block
# name = "pvm-prof"
# summary = "Profile a mini C p-code program under py65: 6502 cycles per function, for a given stdin."
# effects = "exec"
# example = ["--src", "src/pc/bas.c", "--natives", "src/pc/bas-rt.s", "--stdin", "$FIXTURES/bas-run.txt", "--top", "10"]
#
# [returns]
# keys = ["total", "top", "out"]
# doc = "total: 6502 cycles of the run (syscalls excluded); top: the N costliest labels as {name, cycles, pct}; bytecode is charged to the function whose opcode runs (the VM's own cycles included), native code by its PC; out is the program's last 200 bytes of output"
#
# [params]
# src = { type = "path", required = true, help = "mini C source, compiled with cc.py --pcode" }
# natives = { type = "path", default = "", help = "ca65 source linked beside it (extern routines)" }
# stdin = { type = "path", default = "", help = "file fed to the program's stdin" }
# top = { type = "int", default = 15, help = "how many labels to print" }
# limit = { type = "int", default = 2000000000, help = "most 6502 steps" }
#
# [provenance]
# created = "2026-11-19"
# source = "local"
# ///
"""Where a p-code program's time goes, without a listing: run it once with asim's profile hook
and add the cycles up per label of the -Ln file (built with ca65 -g; cc.py's branch labels, L and a number, are not functions)."""
import argparse
import bisect
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--natives", default="")
    ap.add_argument("--stdin", default="")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--limit", type=int, default=2_000_000_000)
    a = ap.parse_args()
    try:
        import asim
        import pvmlink
        import test_cc_pcode
        import test_pvm
        with open(a.src) as f:
            src = f.read()
        natives = open(a.natives).read() if a.natives else None
        stdin = open(a.stdin, "rb").read() if a.stdin else b""
        prof = {}
        with tempfile.TemporaryDirectory(prefix="pvmprof-") as d:
            path = test_cc_pcode.build(src, d, natives=natives)
            r = asim.run("p", [], path=path, stdin=stdin, limit=a.limit, profile=prof,
                         libs={pvmlink.LIBPATH: os.path.join(test_pvm.lib_dir(), "pvm")})
            labels = []
            with open(os.path.join(d, "p.cx.lbl")) as f:
                for line in f:
                    p = line.split()
                    if len(p) == 3 and not p[2].startswith((".@", ".__")) and not re.match(r"\.L\d+$", p[2]):
                        labels.append((int(p[1], 16), p[2].lstrip(".")))
        labels.sort()
        addrs = [x for x, _ in labels]
        by = {}
        for off, c in prof.items():
            i = bisect.bisect_right(addrs, off) - 1
            name = labels[i][1] if i >= 0 and off >= 0 else "(vm before the first opcode)"
            by[name] = by.get(name, 0) + c
        total = sum(by.values())
        top = sorted(by.items(), key=lambda kv: -kv[1])[:a.top]
        print(json.dumps({"total": total,
                          "top": [{"name": n, "cycles": c, "pct": round(100 * c / total, 1)} for n, c in top],
                          "out": r.out[-200:].decode("latin-1")}))
    except Exception as e:  # noqa: BLE001 - one JSON error object, as blocks do
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
