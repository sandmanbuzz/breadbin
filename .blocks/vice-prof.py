#!/usr/bin/env python3
# /// block
# name = "vice-prof"
# summary = "Sum the vice-profile lines of a BREADBIN_VICE_PROFILE=1 run: where VICE test time goes."
# effects = "read"
# example = ["--path", "$FIXTURES/vice-prof.log", "--top", "3"]
#
# [returns]
# keys = ["processes", "wall", "methods", "sleeps", "sleep_total", "cmd_total"]
# doc = "wall sums the processes' lifetimes; methods and sleeps are the top N [name, calls, seconds, avg] by seconds (methods are inclusive: type contains its _cmd calls); sleep_total is every time.sleep, cmd_total every monitor command"
#
# [params]
# path = { type = "path", required = true, help = "log with `vice-profile {json}` lines (podman output or a shard log)" }
# top = { type = "int", default = 12, help = "rows per table" }
#
# [provenance]
# created = "2026-11-23"
# source = "local"
#
# [stamp]
# verified = "9cf890bb4ff4"
# ///
"""Add up the profile lines from tools/vicetest.py; one small answer, not the log."""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    meth, slp, wall, n = {}, {}, 0.0, 0
    try:
        lines = open(a.path, errors="replace").read().splitlines()
    except OSError as e:
        print(json.dumps({"error": str(e)}))
        return 1
    for ln in lines:
        i = ln.find("vice-profile {")
        if i < 0:
            continue
        try:
            d = json.loads(ln[i + 13:])
        except ValueError:
            continue
        n += 1
        wall += d.get("wall", 0)
        for src, dst in ((d.get("methods", {}), meth), (d.get("sleeps", {}), slp)):
            for k, (c, s) in src.items():
                e = dst.setdefault(k, [0, 0.0])
                e[0] += c
                e[1] += s

    def top(t):
        rows = sorted(t.items(), key=lambda kv: -kv[1][1])[:a.top]
        return [[k, c, round(s, 1), round(s / c, 3) if c else 0] for k, (c, s) in rows]
    if not n:
        print(json.dumps({"error": "no vice-profile lines (run with BREADBIN_VICE_PROFILE=1)"}))
        return 1
    print(json.dumps({
        "processes": n, "wall": round(wall, 1), "methods": top(meth), "sleeps": top(slp),
        "sleep_total": round(sum(s for _, s in slp.values()), 1),
        "cmd_total": round(sum(s for k, (_, s) in meth.items() if k.startswith("_cmd:")), 1)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
