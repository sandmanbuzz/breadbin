#!/usr/bin/env python3
# /// block
# name = "leak-scan"
# summary = "Scan the lines a diff adds for machine-identifying details before anything leaves the machine."
# effects = "exec"
# example = ["--base", "HEAD", "--head", "HEAD"]
# matches = ["git.{1,8}diff.{1,40}added", "re[.]search.{1,30}Users"]
#
# [returns]
# keys = ["clean", "count", "hits", "truncated"]
# doc = "hits is up to 10 {file, line, kind, text}; kind is home-path, tmp-path, ipv4, local-host, user-name or mail; text is cut to 80 chars; only added lines are scanned. --head empty means the working tree (staged and unstaged) against --base"
#
# [params]
# base = { type = "str", default = "main", help = "Ref the change is measured against" }
# head = { type = "str", default = "HEAD", help = "Ref with the change; empty for the working tree" }
#
# [provenance]
# created = "2026-11-13"
# source = "local"
#
# [stamp]
# verified = "6c185ea991be"
# ///
"""Outward-privacy check: absolute home paths, scratch paths, internal IPs, hostnames, local names."""
import argparse
import json
import re
import subprocess
import sys

MAX_HITS = 10
# Character classes keep this file from matching itself when it is the diff.
KINDS = [
    ("home-path", r"[/]Users[/][A-Za-z]|[/]home[/]m[a]jick|[/]private[/]"),
    ("tmp-path", r"[/]tmp[/]claude|[/]var[/]folders[/]"),
    ("ipv4", r"\b(10|192[.]168|172[.](1[6-9]|2[0-9]|3[01]))[.][0-9]{1,3}[.][0-9]{1,3}([.][0-9]{1,3})?\b"),
    ("local-host", r"[A-Za-z0-9-][.]local\b"),
    ("user-name", r"\bm[a]jick\b"),
    ("mail", r"icl[o]ud[.]com|noreply[.]codeberg"),
]


def added_lines(base, head):
    """Yield (file, line number, text) for every added line in the diff."""
    cmd = ["git", "diff", "-U0", "--no-color", base] + ([head] if head else [])
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    path, line = None, 0
    for row in out.splitlines():
        if row.startswith("+++ "):
            path = row[6:] if row.startswith("+++ b/") else None
        elif row.startswith("@@"):
            line = int(re.search(r"\+(\d+)", row).group(1)) - 1
        elif row.startswith("+") and path:
            line += 1
            yield path, line, row[1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="main")
    ap.add_argument("--head", default="HEAD")
    args = ap.parse_args()
    try:
        hits = []
        for path, line, text in added_lines(args.base, args.head):
            for kind, pat in KINDS:
                if re.search(pat, text):
                    hits.append({"file": path, "line": line, "kind": kind, "text": text.strip()[:80]})
                    break
    except (subprocess.CalledProcessError, OSError) as err:
        print(json.dumps({"error": str(getattr(err, "stderr", "") or err).strip()}))
        sys.exit(1)
    print(json.dumps({"clean": not hits, "count": len(hits), "hits": hits[:MAX_HITS], "truncated": len(hits) > MAX_HITS}))


if __name__ == "__main__":
    main()
