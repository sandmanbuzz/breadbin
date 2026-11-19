#!/usr/bin/env python3
# /// block
# name = "chess-diff"
# summary = "Differential-test a chess CX binary against a baseline in py65: random games or positions."
# effects = "exec"
# example = ["--base", "build/root/bin/chess", "--new", "build/root/bin/chess", "--n", "2"]
# matches = ["asim[.]run\\(.chess"]
#
# [returns]
# keys = ["mode", "n", "diffs", "kingless", "checks", "mates", "stalemates", "first"]
# doc = "diffs counts runs whose output, exit code or /tmp/chess.sav differ; positions mode skips (and counts as kingless) runs where a king was captured from an illegal save, a known difference; first is up to 3 {run, hex} reproducers (hex = the save file for positions, else the script lines)"
#
# [params]
# base = { type = "path", required = true, help = "Baseline chess binary (e.g. built from cf4666e)" }
# new = { type = "path", required = true, help = "Binary under test" }
# n = { type = "int", default = 100, help = "Runs" }
# seed = { type = "int", default = 1, help = "Random seed" }
# mode = { type = "str", default = "games", help = "games or positions" }
#
# [provenance]
# created = "2026-11-18"
# source = "local"
#
# [stamp]
# verified = "9526d1bf1939"
# ///
"""Run the same random input through two chess binaries and compare everything observable."""
import argparse, json, os, random, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import asim  # noqa: E402

JUNK = ["s", "l", "l", "zz", "", "e2", "e2e4x", "E2E4", "a1a1", "i9i9", "qq"]
KN = [(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)]
DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]
PAWN = [(0, 1), (0, 2), (1, 1), (-1, 1), (0, -1), (0, -2), (1, -1), (-1, -1)]


def sq(r, f):
    return "abcdefgh"[f] + str(r + 1)


def script(rnd):
    out = []
    for _ in range(rnd.randint(10, 160)):
        k = rnd.random()
        if k < 0.12:
            out.append("a")
        elif k < 0.14:
            out.append(rnd.choice(JUNK))
        else:
            f, r, m = rnd.randrange(8), rnd.randrange(8), rnd.random()
            if m < 0.4:
                df, dr = rnd.choice(KN)
            elif m < 0.7:
                d = rnd.randint(1, 7)
                df, dr = (x * d for x in rnd.choice(DIRS))
            else:
                df, dr = rnd.choice(PAWN)
            ok = 0 <= f + df < 8 and 0 <= r + dr < 8
            out.append(sq(r, f) + (sq(r + dr, f + df) if ok else sq(r, f)))
    return out + ["q"]


def position(rnd):
    b = bytearray(129)

    def put(t, black):
        for _ in range(100):
            r, f = rnd.randrange(8), rnd.randrange(8)
            if t == 1 and r in (0, 7) and rnd.random() < .9:
                continue
            if b[r * 16 + f] == 0:
                b[r * 16 + f] = t | (0x80 if black else 0)
                return

    put(6, 0), put(6, 1)
    for _ in range(rnd.randint(1, 7)):
        put(rnd.choice([1, 1, 1, 2, 3, 4, 5]), rnd.random() < .5)
    for _ in range(rnd.randint(0, 2)):          # pawns near promotion
        f, w = rnd.randrange(8), rnd.random() < .5
        i = (6 if w else 1) * 16 + f
        if b[i] == 0:
            b[i] = 1 if w else 0x81
    b[128] = rnd.choice([0, 0x80])
    return bytes(b)


def run(path, lines, files):
    r = asim.run("chess", [], path=path, files=files, cooked=True, limit=200_000_000,
                 stdin="".join(l + "\n" for l in lines).encode())
    return r.out, r.exit, r.files.get("/tmp/chess.sav")


def kingless(out):
    rows = re.findall(rb"(?:^|\n)[1-8] ([^\n]*)", out)
    for x in range(0, len(rows) - 7, 8):
        s = b"".join(rows[x:x + 8])
        if b"K" not in s or b"k" not in s:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--mode", default="games", choices=["games", "positions"])
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    res = dict(mode=a.mode, n=a.n, diffs=0, kingless=0, checks=0, mates=0, stalemates=0, first=[])
    for k in range(a.n):
        if a.mode == "games":
            lines, files, tag = script(rnd), {}, None
        else:
            pos = position(rnd)
            lines, files, tag = ["l"] + ["a"] * rnd.randint(1, 12) + ["q"], {"/tmp/chess.sav": pos}, pos.hex()
        x, y = run(a.base, lines, dict(files)), run(a.new, lines, dict(files))
        res["checks"] += x[0].count(b"check!")
        res["mates"] += x[0].count(b"checkmate")
        res["stalemates"] += x[0].count(b"stalemate")
        if a.mode == "positions" and kingless(x[0]):
            res["kingless"] += 1
            continue
        if x != y:
            res["diffs"] += 1
            if len(res["first"]) < 3:
                res["first"].append({"run": k, "hex": tag or lines[:40]})
    print(json.dumps(res))
    return 1 if res["diffs"] else 0


if __name__ == "__main__":
    sys.exit(main())
