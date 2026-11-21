#!/usr/bin/env python3
# /// block
# name = "vice-profile"
# summary = "Where emulated time goes: VICE tracepoints at labels, phases between them per anchor hit."
# effects = "exec"
# example = ["--trace", "$FIXTURES/trace.txt", "--points", "bread iec_read", "--anchor", "iec_read"]
# matches = ["tr [0-9a-f]{4}", "Trace\\s+exec"]
#
# [returns]
# keys = ["anchors", "window_ms", "window_ms_per_anchor", "phases", "events"]
# doc = "phases is a list of {from, to, n, ms_per_anchor} sorted by ms_per_anchor (the phase's total over all anchors, divided by the anchor count; they add up to window_ms_per_anchor); a live run adds image, command, wall_s and peek. Labels are in build/kernel.lbl, or MODULE:LABEL from build/mod/MODULE.lbl; LABEL+N is N bytes past one. Live runs need xvfb-run and the VICE ROMs, run at real speed, and are slow (boot about 2 minutes); do not trace hot labels."
#
# [params]
# image = { type = "str", default = "build/breadbin.d64", help = "Disk image to boot (live run)" }
# command = { type = "str", default = "", help = "Shell command to time (live run)" }
# setup = { type = "str", default = "", help = "One command run first, untraced, e.g. mod load /lib/km/fast" }
# points = { type = "str", default = "bread iec_read", help = "Space-separated labels to trace" }
# anchor = { type = "str", default = "iec_read", help = "The label whose hits count blocks (or calls)" }
# trace = { type = "path", default = "", help = "Analyse a saved monitor log instead of running" }
# base = { type = "str", default = "", help = "Space-separated MODULE=ADDR load addresses, with trace" }
# top = { type = "int", default = 12, help = "Most phases to list" }
#
# [provenance]
# created = "2026-11-20"
# source = "local"
#
# [stamp]
# verified = "e8069748fec0"
# ///
"""Thin wrapper: the engine is tools/vprof.py (also the command line, docs/testing.md)."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="build/breadbin.d64")
    ap.add_argument("--command", default="")
    ap.add_argument("--setup", default="")
    ap.add_argument("--points", default="bread iec_read")
    ap.add_argument("--anchor", default="iec_read")
    ap.add_argument("--trace", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    cmd = [sys.executable, os.path.join(ROOT, "tools", "vprof.py"), a.image, a.command,
           "--points", *a.points.split(), "--anchor", a.anchor, "--top", str(a.top)]
    if a.setup:
        cmd += ["--setup", a.setup]
    if a.trace:
        cmd += ["--trace", a.trace]
    for b in a.base.split():
        cmd += ["--base", b]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout[-1900:] if r.stdout else json.dumps({"error": r.stderr[-300:] or "no output"}))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
