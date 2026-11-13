#!/usr/bin/env python3
# /// block
# name = "lbl-sym"
# summary = "Look up ld65 -Ln label addresses by name, or the nearest label at or below an address."
# effects = "read"
# example = ["--path", "$FIXTURES/sample.lbl", "--name", "helper"]
# matches = ["open\\('build/kernel\\.lbl'\\)", "kernel\\.lbl"]
#
# [returns]
# keys = ["matches", "count", "truncated"]
# doc = "matches is a list of {name, addr}; with --addr it is the single nearest label at or below, plus offset; names match as substring, case-sensitive; at most 20 matches"
#
# [params]
# path = { type = "path", required = true, help = "ld65 -Ln label file, e.g. build/kernel.lbl" }
# name = { type = "str", default = "", help = "Substring of the label name" }
# addr = { type = "str", default = "", help = "Hex address; return the nearest label at or below it" }
#
# [provenance]
# created = "2026-11-13"
# source = "local"
#
# [stamp]
# verified = "3659cffaa8b7"
# ///
"""Answer label questions about an ld65 -Ln file without dumping it."""
import argparse
import json
import sys

MAX = 20


def load(path):
    """Return [(addr, name)] from lines like 'al 00C010 .name'; the last duplicate wins."""
    labels = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 3 and parts[0] == "al":
                labels[parts[2].lstrip(".")] = int(parts[1], 16)
    return [(a, n) for n, a in labels.items()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--addr", default="")
    args = ap.parse_args()
    try:
        labels = load(args.path)
        if args.addr:
            target = int(args.addr, 16)
            below = [(a, n) for a, n in labels if a <= target]
            best = max(below, default=None)
            found = [{"name": best[1], "addr": f"{best[0]:04X}", "offset": target - best[0]}] if best else []
        else:
            found = [{"name": n, "addr": f"{a:04X}"} for a, n in sorted(labels) if args.name in n]
        out = {"matches": found[:MAX], "count": len(found), "truncated": len(found) > MAX}
        print(json.dumps(out))
    except (OSError, ValueError) as err:
        print(json.dumps({"error": str(err)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
