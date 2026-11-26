#!/usr/bin/env python3
# /// block
# name = "code-search"
# summary = "Recursive search with ripgrep (ack fallback): total count and first hits as file, line, text."
# effects = "exec"
# example = ["--pattern", "iec_read", "--path", "src", "--limit", "5"]
# matches = ["\\bgrep\\s+(-[a-zA-Z]*[rR]|--recursive)"]
#
# [returns]
# keys = ["tool", "count", "hits", "truncated"]
# doc = "count is every match; hits is up to limit {file, line, text}, text cut at 200 characters; truncated is true when count exceeds limit"
#
# [params]
# pattern = { type = "str", required = true, help = "Regular expression (rg syntax); use fixed for literal text" }
# path = { type = "path", required = false, help = "Directory or file to search (default: .)" }
# ignore_case = { type = "bool", required = false, help = "Case-insensitive match" }
# fixed = { type = "bool", required = false, help = "Treat pattern as literal text" }
# limit = { type = "int", required = false, help = "Hits to return (default 20)" }
# tool = { type = "str", required = false, help = "rg or ack (default: rg if installed, else ack)" }
#
# [provenance]
# created = "2026-11-26"
# source = "local"
# ///
"""Recursive search that returns the count and a few hits, not the whole output."""
import argparse
import json
import re
import shutil
import subprocess
import sys

TEXT_MAX = 200
HIT = re.compile(r"^(.*?):(\d+):(.*)$")


def fail(message):
    print(json.dumps({"error": message}))
    sys.exit(1)


def build(tool, pattern, path, ignore_case, fixed):
    if tool == "rg":
        cmd = ["rg", "--line-number", "--no-heading", "--with-filename", "--color", "never"]
        if ignore_case:
            cmd.append("--ignore-case")
        if fixed:
            cmd.append("--fixed-strings")
        return cmd + ["-e", pattern, "--", path]
    cmd = ["ack", "--nogroup", "--nocolor"]
    if ignore_case:
        cmd.append("--ignore-case")
    if fixed:
        cmd.append("--literal")
    return cmd + ["--", pattern, path]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--path", default=".")
    ap.add_argument("--ignore_case", action="store_true")
    ap.add_argument("--fixed", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--tool", choices=["rg", "ack"], default=None)
    args = ap.parse_args()
    if args.limit < 1:
        fail("limit must be at least 1")

    tool = args.tool or ("rg" if shutil.which("rg") else "ack" if shutil.which("ack") else None)
    if tool is None:
        fail("neither rg nor ack is installed")
    if shutil.which(tool) is None:
        fail(f"{tool} is not installed")

    cmd = build(tool, args.pattern, args.path, args.ignore_case, args.fixed)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as err:
        fail(str(err))
    # rg: 0 = matches, 1 = none, 2 = error. ack: 0 = matches, 1 = none, other = error.
    if proc.returncode not in (0, 1):
        fail((proc.stderr.strip() or f"{tool} exited {proc.returncode}"))

    hits = []
    for line in proc.stdout.splitlines():
        m = HIT.match(line)
        if m:
            hits.append({"file": m.group(1), "line": int(m.group(2)), "text": m.group(3)[:TEXT_MAX]})
        elif line:
            hits.append({"file": args.path, "line": 0, "text": line[:TEXT_MAX]})
    print(json.dumps({
        "tool": tool,
        "count": len(hits),
        "hits": hits[: args.limit],
        "truncated": len(hits) > args.limit,
    }))


if __name__ == "__main__":
    main()
