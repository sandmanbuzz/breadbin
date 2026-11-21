#!/usr/bin/env python3
# /// block
# name = "lib-weight"
# summary = "Per-module weight of the user library: sizes, programs linking it, bytes summed over programs."
# effects = "exec"
# example = ["--objs", "build/p", "--lib", "build/lib/breadbin.lib", "--cfg", "src/prog.cfg"]
#
# [returns]
# keys = ["programs", "modules", "lib_bytes_total", "cx_bytes_total"]
# doc = "modules: {name: {code, rodata, bss, programs, summed}} where summed is (code+rodata) over every program that links it; lib_bytes_total is the sum of summed; cx_bytes_total is the size of every file in --bin (0 when absent). Links each program object from --objs against --lib into a scratch dir that is removed afterwards"
#
# [params]
# objs = { type = "path", default = "build/p", help = "Directory of program objects (*.o)" }
# lib = { type = "path", default = "build/lib/breadbin.lib", help = "The user library archive" }
# cfg = { type = "path", default = "src/prog.cfg", help = "ld65 config for programs" }
# bin = { type = "path", default = "build/root/bin", help = "Directory of built CX programs, for the on-disk total" }
#
# [provenance]
# created = "2026-11-21"
# source = "local"
#
# [stamp]
# verified = "9734539e3340"
# ///
"""Where the library's bytes go: link every program with a map, tally the library modules it pulled in."""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

MOD = re.compile(r"^(?:\S+/)?breadbin\.lib\((\w+)\.o\):\n((?:[ \t]+\w+[ \t]+Offs=\S+[ \t]+Size=[0-9A-F]+.*\n)+)", re.M)
SEG = re.compile(r"(\w+)[ \t]+Offs=\S+[ \t]+Size=([0-9A-F]+)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--objs", default="build/p")
    ap.add_argument("--lib", default="build/lib/breadbin.lib")
    ap.add_argument("--cfg", default="src/prog.cfg")
    ap.add_argument("--bin", default="build/root/bin")
    a = ap.parse_args()
    objs = sorted(glob.glob(os.path.join(a.objs, "*.o")))
    if not objs or not os.path.exists(a.lib):
        print(json.dumps({"error": "no program objects or no library: run make"}))
        sys.exit(1)
    mods = {}
    linked = 0
    with tempfile.TemporaryDirectory() as tmp:
        for o in objs:
            m = os.path.join(tmp, "m.map")
            r = subprocess.run(["ld65", "-C", a.cfg, "-S", "0", "-m", m, "-o", os.path.join(tmp, "x"), o, a.lib],
                               capture_output=True, text=True)
            if r.returncode or not os.path.exists(m):
                continue                      # a program that is not a plain format-1 link (the VM's): skip
            linked += 1
            txt = open(m, errors="replace").read().split("Modules list:")[-1].split("Segment list:")[0]
            for g in MOD.finditer(txt):
                seg = {k: int(v, 16) for k, v in SEG.findall(g.group(2))}
                d = mods.setdefault(g.group(1), {"code": seg.get("CODE", 0), "rodata": seg.get("RODATA", 0),
                                                 "bss": seg.get("BSS", 0), "programs": 0, "summed": 0})
                d["programs"] += 1
                d["summed"] += seg.get("CODE", 0) + seg.get("RODATA", 0)
    cx = sum(os.path.getsize(p) for p in glob.glob(os.path.join(a.bin, "*")) if os.path.isfile(p))
    print(json.dumps({"programs": linked, "modules": dict(sorted(mods.items(), key=lambda kv: -kv[1]["summed"])),
                      "lib_bytes_total": sum(d["summed"] for d in mods.values()), "cx_bytes_total": cx}))


if __name__ == "__main__":
    main()
