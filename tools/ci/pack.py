#!/usr/bin/env python3
"""Pack tools/ci/shards.txt from measured per-test times (the TIMING lines of tools/ci/timed_unittest.py).

  tools/ci/pack.py LOG [LOG...] [--shards N] [--write]

Reads "TIMING <seconds> <test id>" lines from the given logs (a sharded run's shard logs or merged.log;
a test with no timing counts the mean of the measured ones). Units: Boot in two halves (each half a
contiguous run of Boot's sorted methods); Cache, IecFault, IecRestart and Drives per method; Console and
Keyboard whole modules; other classes whole. Greedy longest-first into N bins. Inside a shard the order is
Boot halves, other classes, Cache, IecFault/IecRestart, Drives last (Drives writes the master image). The
bin holding Boot's first half is listed first, so Boot reads in order across the file.
Without --write it prints the estimate per shard. With --write it rewrites tools/ci/shards.txt (header kept)
and tools/ci/shards.py check must pass. The durations come from one measured run; re-measure after a big change.
"""
import argparse
import collections
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shards as S  # noqa: E402

TIMING = re.compile(r"TIMING (\d+(?:\.\d+)?) (\S+)$")
WHOLE_MODULES = ("tests.test_console", "tests.test_keyboard")


def measured(paths):
    d = {}
    for p in paths:
        with open(p, errors="replace") as f:
            for line in f:
                m = TIMING.search(line.rstrip("\n"))
                if m:
                    d[m.group(2)] = float(m.group(1))   # a re-run of the same test: last one wins
    return d


def pack(ids, dur, n):
    mean = sum(dur.values()) / len(dur) if dur else 60.0
    boot = sorted(i for i in ids if ".Boot." in i)
    half = {i: (0 if k < len(boot) // 2 else 1) for k, i in enumerate(boot)}

    def unit(i):
        if i in half:
            return "Boot.half%d" % half[i]
        if i.startswith(WHOLE_MODULES):
            return ".".join(i.split(".")[:2])
        cls = i.rsplit(".", 1)[0]
        if cls.endswith((".Cache", ".IecFault", ".IecRestart", ".Drives")):
            return i
        return cls

    def cat(i):
        if ".Boot." in i:
            return 0
        if ".Drives." in i:
            return 4
        if ".Cache." in i:
            return 2
        if ".IecFault." in i or ".IecRestart." in i:
            return 3
        return 1

    units = collections.defaultdict(lambda: [0.0, []])
    for i in ids:
        u = unit(i)
        units[u][0] += dur.get(i, mean)
        units[u][1].append(i)
    bins = [[0.0, []] for _ in range(n)]
    for name, (d, _) in sorted(units.items(), key=lambda kv: -kv[1][0]):
        b = min(bins, key=lambda b: b[0])
        b[0] += d
        b[1].append(name)
    if n >= 2 and boot:
        def bin_of(name):
            return next(k for k, (_, ms) in enumerate(bins) if name in ms)
        b0, b1 = bin_of("Boot.half0"), bin_of("Boot.half1")
        if b1 < b0:
            bins[b0], bins[b1] = bins[b1], bins[b0]

    def specs(names):
        out = []
        for u in names:
            if u.startswith("Boot.half"):
                h = int(u[-1])
                out += [i for i in boot if half[i] == h]
            else:
                out.append(u)
        return sorted(out, key=lambda s: (cat(s), s))
    return [(d, specs(ms)) for d, ms in bins]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--shards", type=int, default=6)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    dur = measured(a.logs)
    ids = S.discovered()
    if not dur:
        print("no TIMING lines in the logs (run with tools/ci/timed_unittest.py)", file=sys.stderr)
        return 2
    missing = [i for i in ids if i not in dur]
    bins = pack(ids, dur, a.shards)
    for n, (d, sp) in enumerate(bins, 1):
        print("s%d est %6.0f s, %d specs" % (n, d, len(sp)))
    print("timed %d of %d tests; estimate for the slowest shard %.0f s" % (len(ids) - len(missing), len(ids),
          max(d for d, _ in bins)))
    if a.write:
        head = subprocess.run(["git", "show", "HEAD:tools/ci/shards.txt"], capture_output=True, text=True,
                              cwd=HERE).stdout.splitlines()
        keep = [l for l in head if l.startswith("#")]
        body = ["s%d|%s" % (n, " ".join(sp)) for n, (_, sp) in enumerate(bins, 1)]
        with open(os.path.join(HERE, "shards.txt"), "w") as f:
            f.write("\n".join(keep + body) + "\n")
        print("wrote tools/ci/shards.txt; run tools/ci/shards.py check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
