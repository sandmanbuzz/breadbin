#!/usr/bin/env python3
"""Survey printable ASCII: how often the repo uses each character, how a C64 keyboard types it
(src/kernel/keytab.inc through kbd.s's PETSCII and con.s's to_ascii), and what the console shows
for it (to_screen for the 40-column console; the 80-column font in src/mod/con80.font via sc80).

    python3 tools/glyph_survey.py [--top 60] [--json]

Frequency is counted over the repo's own text (src/, tools/, docs/, tests/): a proxy for what a
user meets in files, not a claim about any corpus. Read-only."""
import argparse, glob, json, os, re, sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def keytab_tables():
    """The 64-key tables from keytab.inc: unshifted, shift, commodore (lists of 64 PETSCII bytes)."""
    txt = open(os.path.join(ROOT, "src", "kernel", "keytab.inc")).read()
    tabs = []
    for block in re.split(r"; ---- ", txt)[1:]:
        vals = []
        for m in re.finditer(r"\.byte\s+(.*?)\s*;", block):
            vals += [int(x.strip().lstrip("$"), 16) for x in m.group(1).split(",")]
        tabs.append(vals)
    return tabs[0], tabs[1], tabs[2]          # unshifted, shift, commodore (the control table is ignored)

def to_ascii(p):
    """Port of con.s to_ascii (PETSCII -> ASCII); None where it maps to nothing."""
    if p < 0x20: return None
    if p < 0x41: return p
    if p < 0x5B: return p | 0x20           # not reached for keys: keys come as $41-$5A (see below)
    if p < 0x5F: return p
    if p == 0x5F: return 0x5F
    if p < 0x61: return p
    if p < 0x7B: return p & 0xDF
    if p == 0xDD: return 0x7C
    if 0xC1 <= p < 0xDB: return p & 0x7F
    return None

KEYNAME = {}
def label(line, bit, mods):
    return f"{mods}{'line%d.bit%d' % (line, bit)}"

def reach():
    """ASCII -> list of (modifier, matrix position) that type it."""
    un, sh, cbm = keytab_tables()
    out = {}
    for mods, tab in (("", un), ("SHIFT+", sh), ("C= ", cbm)):
        for i, p in enumerate(tab):
            if p == 0xFF: continue
            a = to_ascii(p)
            if a is None: continue
            out.setdefault(chr(a), []).append(f"{mods}{'line%d.bit%d' % (i // 8, i % 8)}")
    return out

def font_status():
    """Per 80-column screen code: 'blank' if the glyph has no ink, else 'ink'."""
    f = open(os.path.join(ROOT, "src", "mod", "con80.font"), "rb").read()
    return ["blank" if not any(f[c*4:c*4+4]) else "ink" for c in range(len(f)//4)]

def screen_code(a):
    """The 40-column to_screen (con.s) and the 80-column sc80 (con80.inc), as code, for ASCII a."""
    o = a
    if o < 0x20: return None, None
    if o < 0x40 or 0x41 <= o <= 0x5A: s = o
    elif o == 0x40: s = 0
    elif o < 0x5F: s = o - 0x40
    elif o == 0x5F: s = 0x64
    elif o == 0x60: return None, None
    elif o <= 0x7A: s = o - 0x60
    elif o == 0x7C: s = 0x5D
    else: s = 0x3F
    if 0x7B <= o <= 0x7E: s80 = o - 0x16    # sc80
    else: s80 = s
    return s, s80

def corpus():
    c = Counter()
    for pat in ("src/**/*", "tools/**/*", "docs/**/*", "tests/**/*", "include/**/*"):
        for f in glob.glob(os.path.join(ROOT, pat), recursive=True):
            if not os.path.isfile(f): continue
            try: t = open(f, encoding="ascii", errors="ignore").read()
            except OSError: continue
            c.update(ch for ch in t if 0x20 <= ord(ch) < 0x7F)
    return c

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--top", type=int, default=0); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    freq = corpus(); keys = reach(); ink = font_status()
    rows = []
    for ch in (chr(i) for i in range(0x20, 0x7F)):
        s40, s80 = screen_code(ord(ch))
        if s40 is None: shown40 = shown80 = "nothing"
        else:
            shown40 = "?" if s40 == 0x3F and ch != "?" else f"code {s40:02X}"
            shown80 = f"code {s80:02X} ({ink[s80]})" if s80 < len(ink) else "?"
        rows.append({"char": ch, "uses": freq.get(ch, 0), "keys": keys.get(ch, []) or ["none"],
                     "console40": shown40, "console80": shown80})
    rows.sort(key=lambda r: -r["uses"])
    if a.top: rows = rows[:a.top]
    if a.json:
        print(json.dumps(rows, indent=1)); return
    print(f"{'char':4} {'uses':>7}  {'keyboard':28} {'40-col':12} 80-col")
    for r in rows:
        k = ",".join(r["keys"][:2]) + ("…" if len(r["keys"]) > 2 else "")
        print(f"{r['char']!r:4} {r['uses']:>7}  {k:28} {r['console40']:12} {r['console80']}")

if __name__ == "__main__":
    sys.exit(main())
