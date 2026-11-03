#!/usr/bin/env python3
"""Pack the workspace for a move to another machine, and verify it after the unpack.

  tools/workspace.py plan   [--parent] [--with-secrets]
  tools/workspace.py pack   OUTDIR [--parent] [--with-secrets] [--only NAME,...] [--force]
  tools/workspace.py verify OUTDIR DEST

A best-effort definition of "the workspace" (docs/runner-move.md): the clone with
everything in it (.git, build/, dotfiles, cruft), the session scratchpads, this project's
Claude directory (memory and transcripts), the global Claude files, the ROM cache and the
VICE logs. Each is its own tarball made with plain `tar` (the commands are printed), with
a manifest of every file (type, mode, sha256, symlink target) taken just before the tar,
and a SHA256SUMS of the tarballs. `verify` checks the tarball hashes, unpacks into DEST,
and compares a fresh manifest with the stored one: a clean pass means the same bytes.

`pack` stops unless the clone is READY (tools/readiness) and nothing else holds files
open under the packed trees; --force overrides both. Secrets (gh config, git config) are
packed only with --with-secrets. Not packed, because they are the user's decision: the
signing key (~/.gnupg), ssh keys (~/.ssh), plugins, shell snapshots, credentials.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile

HOME = os.path.expanduser("~")
SKIP_CLAUDE = {"projects", "plugins", "cache", "shell-snapshots", ".DS_Store", ".credentials.json"}
TAR_ENV = dict(os.environ, COPYFILE_DISABLE="1")   # macOS tar: no AppleDouble (._*) entries


def primary():
    common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], text=True).strip()
    return os.path.dirname(os.path.realpath(common))


def project_key(path):
    """Claude's directory name for a path: every character that is not a letter, a digit or
    '-' becomes '-' ('/', '.', '_' and the rest)."""
    return re.sub(r"[^A-Za-z0-9-]", "-", path)


def mine(name, key):
    """The clone's own entry or one of its worktree sessions' (<key>--claude-worktrees-...),
    not a sibling clone whose path merely starts the same."""
    return name == key or name.startswith(key + "--claude-worktrees-")


def packages(parent=False, secrets=False):
    """[(name, base, items, note)] for what exists on this machine, plus a list of notes."""
    repo = primary()
    key = project_key(repo)
    root = os.path.dirname(repo) if parent else repo
    proj = os.path.join(HOME, ".claude", "projects")
    claude = os.path.join(HOME, ".claude")
    sdir = f"/tmp/claude-{os.getuid()}"
    scratch = sorted(f"claude-{os.getuid()}/{d}" for d in os.listdir(sdir) if mine(d, key)) if os.path.isdir(sdir) else []
    want = [
        ("repo", os.path.dirname(root), [os.path.basename(root)],
         "the clone, .git, build/, worktrees inside it" + (" and its parent directory" if parent else "")),
        ("scratch", "/tmp", scratch,
         "session scratchpads, including those of worktree sessions: worktrees, logs, ROM directories"),
        ("claude-project", proj, sorted(d for d in os.listdir(proj) if mine(d, key))
         if os.path.isdir(proj) else [], "memory and transcripts of this project"),
        ("claude-global", claude, sorted(set(os.listdir(claude)) - SKIP_CLAUDE) if os.path.isdir(claude) else [],
         "global CLAUDE.md, settings, skills, history (not plugins, caches or credentials)"),
        ("roms", os.path.join(HOME, ".cache"), ["breadbin-ci"], "the stock ROM cache"),
        ("vicelogs", tempfile.gettempdir(),
         sorted(os.path.basename(f) for f in glob.glob(os.path.join(tempfile.gettempdir(), "vice*.log"))),
         "VICE logs left by the test harness"),
    ]
    if secrets:
        want.append(("secrets", HOME, [".gitconfig", ".config/gh-sandmanbuzz"],
                     "git config and the public identity's gh config: SECRET, encrypt in transit"))
    have, notes = [], []
    for name, base, items, note in want:
        items = [i for i in items if os.path.lexists(os.path.join(base, i))]
        if items:
            have.append((name, base, items, note))
        else:
            notes.append(f"{name}: nothing found")
    if not secrets:
        notes.append("secrets: not packed (use --with-secrets for git config and gh config)")
    notes.append("never packed, the user decides: ~/.gnupg (signing key), ~/.ssh, plugins, credentials")
    return have, notes


def esc(name):
    return name.replace("\\", "\\\\").replace("\n", "\\n")


def entry(base, rel):
    p = os.path.join(base, rel)
    shown = esc(rel)
    st = os.lstat(p)
    if stat.S_ISLNK(st.st_mode):
        return f"l - - {shown} -> {esc(os.readlink(p))}"
    if stat.S_ISDIR(st.st_mode):
        return f"d {st.st_mode & 0o7777:o} - {shown}"
    if stat.S_ISREG(st.st_mode):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return f"f {st.st_mode & 0o7777:o} {h.hexdigest()} {shown}"
    return None     # socket, fifo, device: tar does not carry them either


def manifest(base, items):
    """Sorted lines, one per file, directory and symlink under each item; raises on
    anything unreadable so a package with a hole cannot pass."""
    errors, lines = [], []
    for item in items:
        rels = [item]
        top = os.path.join(base, item)
        if os.path.isdir(top) and not os.path.islink(top):      # an item may be a single file
            for path, dirs, files in os.walk(top, followlinks=False, onerror=errors.append):
                dirs.sort()
                rels += [os.path.relpath(os.path.join(path, n), base) for n in dirs + files]
        for rel in rels:
            try:
                e = entry(base, rel)
            except OSError as ex:
                errors.append(ex)
                continue
            if e:
                lines.append(e)
    if errors:
        raise OSError(f"{len(errors)} unreadable path(s), first: {errors[0]}")
    return sorted(lines, key=lambda l: l.split(" ", 3)[3])


def tar_cmd(out, base, items, extract=False):
    # "--": the Claude project directory is named like -Users-..., which tar reads as an option
    return ["tar", "-xpf", out, "-C", base] if extract else ["tar", "-cf", out, "-C", base, "--"] + items


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_size(base, items):
    n = 0
    for item in items:
        top = os.path.join(base, item)
        if not os.path.isdir(top) or os.path.islink(top):
            n += 0 if os.path.islink(top) else os.lstat(top).st_size
            continue
        for path, _, files in os.walk(top):
            n += sum(os.lstat(os.path.join(path, f)).st_size for f in files if not os.path.islink(os.path.join(path, f)))
    return n


def ancestors():
    pids, pid = {os.getpid()}, os.getppid()
    while pid > 1 and pid not in pids:
        pids.add(pid)
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        pid = int(out) if out.isdigit() else 0
    return pids


def open_holders(trees):
    """(pid, command) of other processes holding files open under the trees."""
    if not trees:
        return {}
    me, found = ancestors(), {}
    for t in trees:
        r = subprocess.run(["lsof", "-F", "pc", "+D", t], capture_output=True, text=True)
        pid = None
        for l in r.stdout.splitlines():
            if l.startswith("p"):
                pid = int(l[1:])
            elif l.startswith("c") and pid not in me and l[1:] != "lsof":
                found[pid] = l[1:]
    return found


def cmd_plan(a):
    have, notes = packages(a.parent, a.with_secrets)
    for name, base, items, note in have:
        mb = tree_size(base, items) / 1e6
        print(f"{name}: {mb:.1f} MB, {note}")
        print("  " + " ".join(["COPYFILE_DISABLE=1"] + [shlex.quote(x) for x in tar_cmd(f"OUTDIR/{name}.tar", base, items)]))
    for n in notes:
        print("note:", n)


def record_block(text, forced):
    """The comparable part of a readiness report: tips, refs digest, object count. No paths,
    user names or host names, so the file can be pasted into a handoff."""
    out, on = [f"readiness: {'forced past a failing check' if forced else 'READY'}"], False
    for l in text.splitlines():
        if l.startswith("== RECORD"):
            on = True
        elif l.startswith("== ") or l.startswith(("READY", "NOT READY")):
            on = False
        elif on:
            out.append(l)
    return "\n".join(out) + "\n"


def cmd_pack(a):
    os.umask(0o077)                 # the tarballs may hold secrets: owner only
    have, _ = packages(a.parent, a.with_secrets)
    if a.only:
        keep = set(a.only.split(","))
        have = [p for p in have if p[0] in keep]
    out = os.path.realpath(a.outdir)
    for name, base, items, _ in have:
        for i in items:
            t = os.path.realpath(os.path.join(base, i))
            if out == t or out.startswith(t + os.sep):
                sys.exit(f"pack: {out} is inside what is being packed ({t})")
    problems = []
    repo = primary()
    ready = subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), "readiness")],
                           capture_output=True, text=True, cwd=repo)
    if ready.returncode != 0:
        problems.append("tools/readiness: NOT READY")
    trees = [os.path.join(b, i) for n, b, items, _ in have
             if n in ("repo", "scratch", "claude-project") for i in items]
    try:
        holders = open_holders(trees)
    except OSError as e:
        holders = {}
        problems.append(f"cannot check for open files ({e})")
    for pid, c in sorted(holders.items()):
        problems.append(f"pid {pid} ({c}) has files open in a packed tree")
    if problems and not a.force:
        print("\n".join(problems), file=sys.stderr)
        sys.exit("pack: not quiesced (fix the above, or --force)")
    os.makedirs(os.path.join(out, "manifests"), exist_ok=True)
    meta, sums = [], []
    for name, base, items, note in have:
        tarball = os.path.join(out, f"{name}.tar")
        lines = manifest(base, items)
        cmd = tar_cmd(tarball, base, items)
        print(" ".join(["COPYFILE_DISABLE=1"] + cmd), flush=True)
        subprocess.run(cmd, check=True, env=TAR_ENV)
        with open(os.path.join(out, "manifests", name + ".txt"), "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write("\n".join(lines) + "\n")
        sums.append(f"{sha256_file(tarball)}  {name}.tar")
        meta.append(dict(name=name, items=items, note=note, files=len(lines)))
        print(f"  {len(lines)} entries, {os.path.getsize(tarball) / 1e6:.1f} MB")
    with open(os.path.join(out, "SHA256SUMS"), "w") as f:
        f.write("\n".join(sums) + "\n")
    with open(os.path.join(out, "packages.json"), "w") as f:
        json.dump(meta, f, indent=1)
    with open(os.path.join(out, "RECORD.txt"), "w") as f:
        f.write(record_block(ready.stdout, ready.returncode != 0))
    print("packed:", ", ".join(m["name"] for m in meta), "->", out)


def read_manifest(path):
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        lines = f.read().split("\n")
    return lines[:-1] if lines and lines[-1] == "" else lines


def cmd_verify(a):
    meta = json.load(open(os.path.join(a.outdir, "packages.json")))
    sums = {n: h for h, n in (l.split("  ", 1) for l in open(os.path.join(a.outdir, "SHA256SUMS")).read().splitlines())}
    mfile = lambda name: os.path.join(a.outdir, "manifests", name + ".txt")
    # nothing is unpacked until every package checks out, so a failure leaves DEST untouched
    problems = []
    for m in meta:
        name, tarball = m["name"], os.path.join(a.outdir, m["name"] + ".tar")
        dest = os.path.join(a.dest, name)
        if not os.path.exists(tarball):
            problems.append(f"{name}: tarball missing")
        elif name + ".tar" not in sums:
            problems.append(f"{name}: not in SHA256SUMS")
        elif sha256_file(tarball) != sums[name + ".tar"]:
            problems.append(f"{name}: tarball hash differs from SHA256SUMS")
        if os.path.exists(dest) and os.listdir(dest):
            problems.append(f"{name}: {dest} is not empty (unpack into a fresh path)")
    for p in problems:
        print("FAIL", p)
    if problems:
        sys.exit(1)
    nomf = [m["name"] for m in meta if not os.path.exists(mfile(m["name"]))]
    if nomf:
        print("WARN: no manifest for " + ", ".join(nomf) + " (carry the whole output directory): comparing entry counts only, a weaker check")
    bad = 0
    for m in meta:
        name = m["name"]
        dest = os.path.join(a.dest, name)
        os.makedirs(dest, exist_ok=True)
        subprocess.run(tar_cmd(os.path.join(a.outdir, name + ".tar"), dest, [], extract=True), check=True, env=TAR_ENV)
        got = manifest(dest, m["items"])
        if name in nomf:
            if len(got) == m["files"]:
                print(f"PASS {name}: {len(got)} entries (counts only)")
            else:
                bad += 1
                print(f"FAIL {name}: {len(got)} entries, {m['files']} recorded")
            continue
        want = read_manifest(mfile(name))
        if got == want:
            print(f"PASS {name}: {len(got)} entries match")
        else:
            bad += 1
            g, w = set(got), set(want)
            print(f"FAIL {name}: {len(w - g)} missing or different, {len(g - w)} extra")
            for l in sorted(w - g)[:10]:
                print("  want", l)
            for l in sorted(g - w)[:10]:
                print("  got ", l)
    sys.exit(1 if bad else 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("plan", "pack"):
        p = sub.add_parser(n)
        p.add_argument("--parent", action="store_true", help="pack the clone's parent directory as the repo package")
        p.add_argument("--with-secrets", action="store_true")
        if n == "pack":
            p.add_argument("outdir")
            p.add_argument("--only", help="comma-separated package names")
            p.add_argument("--force", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("outdir")
    p.add_argument("dest")
    a = ap.parse_args(argv)
    {"plan": cmd_plan, "pack": cmd_pack, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    main()
