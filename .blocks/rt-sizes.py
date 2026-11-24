#!/usr/bin/env python3
# /// block
# name = "rt-sizes"
# summary = "Bytes per global label (to the next global label) of a ca65 listing of a source: where the bytes of a hand-written routine file go."
# effects = "write-workspace"
# example = ["--src", "src/pc/bas-rt.s", "--top", "5"]
#
# [returns]
# keys = ["total", "top"]
# doc = "total: bytes in the listing's code and data; top: the N largest spans as {name, size}; a span runs from a global label to the next; cheap locals (@x) and :: do not start one"
#
# [params]
# src = { type = "path", required = true, help = "ca65 source" }
# top = { type = "int", default = 25, help = "how many spans to print" }
#
# [provenance]
# created = "2026-11-23"
# source = "local"
# ///
import argparse, json, os, re, subprocess, sys, tempfile

ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--top", type=int, default=25)
a = ap.parse_args()
d = tempfile.mkdtemp(prefix="rts-")
lst = os.path.join(d, "x.lst")
r = subprocess.run(["ca65", "-I", "include", "-I", "src/pvm", "-l", lst, "-o", os.path.join(d, "x.o"), a.src],
                   capture_output=True, text=True)
if r.returncode:
    print(json.dumps({"error": r.stderr[-300:]})); sys.exit(1)
cur, sz = None, {}
for l in open(lst):
    if not re.match(r"[0-9A-F]{6}r? \d", l):
        continue
    b = l[11:23].split()
    t = l[24:]
    m = re.match(r"([A-Za-z_]\w*):", t.lstrip())
    if m:
        cur = m[1]; sz.setdefault(cur, 0)
    if cur:
        sz[cur] += len(b)
top = sorted(sz.items(), key=lambda x: -x[1])[:a.top]
print(json.dumps({"total": sum(sz.values()), "top": [{"name": k, "size": v} for k, v in top]}))
