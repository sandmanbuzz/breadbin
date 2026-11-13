#!/usr/bin/env python3
# /// block
# name = "wt-state"
# summary = "Worktree hygiene: counts, which trees are safe to remove, which carry unlanded or dirty work."
# effects = "exec"
# example = ["--base", "HEAD"]
# matches = ["worktree.{1,6}list", "merge-base.{1,6}--is-ancestor"]
#
# [returns]
# keys = ["base", "count", "landed_clean", "removable", "pending", "truncated"]
# doc = "removable is up to 15 paths of trees whose tip is on base and that are clean (relative to the current directory); pending is up to 10 {path, branch, dirty, ahead} for trees with unlanded commits or dirty files; landed_clean is the full removable count"
#
# [params]
# base = { type = "str", default = "main", help = "Ref that counts as landed" }
#
# [provenance]
# created = "2026-11-13"
# source = "local"
#
# [stamp]
# verified = "a843f3eb8b38"
# ///
"""Worktree hygiene in one call: which trees exist, which are dirty, which are already on base."""
import argparse
import json
import os
import subprocess
import sys



def git(*cmd, cwd=None, check=True):
    return subprocess.run(["git", *cmd], capture_output=True, text=True, check=check, cwd=cwd)


def worktrees():
    """Yield (path, tip, branch or None) from `git worktree list --porcelain`."""
    for block in git("worktree", "list", "--porcelain").stdout.strip().split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        if "worktree" in fields:
            branch = fields.get("branch", "").removeprefix("refs/heads/") or None
            yield fields["worktree"], fields.get("HEAD", "")[:7], branch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="main")
    args = ap.parse_args()
    try:
        git("rev-parse", "--verify", "--quiet", args.base)
        rows = []
        for path, tip, branch in worktrees():
            dirty = len(git("status", "--porcelain", cwd=path).stdout.splitlines())
            ahead = int(git("rev-list", "--count", f"{args.base}..{tip}").stdout)
            landed = git("merge-base", "--is-ancestor", tip, args.base, check=False).returncode == 0
            rows.append({"path": os.path.relpath(path), "branch": branch, "tip": tip,
                         "dirty": dirty, "ahead": ahead, "landed": landed})
    except (subprocess.CalledProcessError, OSError) as err:
        print(json.dumps({"error": str(getattr(err, "stderr", "") or err).strip() or "bad base ref"}))
        sys.exit(1)
    removable = [r["path"] for r in rows if r["landed"] and not r["dirty"]]
    pending = [{k: r[k] for k in ("path", "branch", "dirty", "ahead")} for r in rows if not r["landed"] or r["dirty"]]
    print(json.dumps({"base": args.base, "count": len(rows), "landed_clean": len(removable),
                      "removable": removable[:15], "pending": pending[:10],
                      "truncated": len(removable) > 15 or len(pending) > 10}))


if __name__ == "__main__":
    main()
