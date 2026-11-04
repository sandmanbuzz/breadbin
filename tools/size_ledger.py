#!/usr/bin/env python3
"""Append one line to the size ledger: the `make size` figures for a commit, so creep is visible over time (M0-7).

    make size | python3 tools/size_ledger.py --commit "$(git rev-parse --short HEAD)"    (appends to docs/size-ledger.tsv)
    python3 tools/size_ledger.py --commit HASH --size-file FILE --ledger FILE --kernel-inc src/kernel/k.inc

The ledger is tab-separated with a header. Columns: commit, KSTART (the first kernel page, from k.inc), code and data
end, room below $CF00, BSS and CODEHI end, room below $FFFA, the module totals (code, rodata, data, codehi, init, bss,
total) and the INIT bytes. Nothing is computed twice: every figure is what `tools/size.py` printed.

Programs have their own ledger, one row per program per commit (docs/program-size-ledger.tsv): the size of each CX file
in build/root/bin, so a review can see which program grew:

    python3 tools/size_ledger.py --commit HASH --programs build/root/bin          (appends to docs/program-size-ledger.tsv)
"""
import argparse
import os
import re
import sys

HEADER = ["commit", "kstart", "code_end", "room_below_cf00", "bss_codehi_end", "room_below_fffa",
          "code", "rodata", "data", "codehi", "init", "bss", "modules_total"]


def parse_kstart(text):
    """KSTART = $A200 in k.inc -> 0xA200."""
    m = re.search(r"^KSTART\s*=\s*\$([0-9A-Fa-f]+)", text, re.M)
    if not m:
        raise ValueError("no KSTART = $xxxx in k.inc")
    return int(m.group(1), 16)


def parse_size(text):
    """The text of `make size` (tools/size.py) -> a dict of the figures the ledger keeps."""
    fig = {}
    total = None
    for line in text.splitlines():
        cols = line.split()
        if cols and cols[0] == "total" and len(cols) == 8:
            total = [int(c) for c in cols[1:]]
        m = re.search(r"code and data end at \$([0-9A-Fa-f]+); room below \$[0-9A-Fa-f]+: (\d+) bytes", line)
        if m:
            fig["code_end"], fig["room_below_cf00"] = int(m.group(1), 16), int(m.group(2))
        m = re.search(r"BSS and CODEHI end at \$([0-9A-Fa-f]+); room below \$[0-9A-Fa-f]+: (\d+) bytes", line)
        if m:
            fig["bss_codehi_end"], fig["room_below_fffa"] = int(m.group(1), 16), int(m.group(2))
    if total is None:
        raise ValueError("no 'total' row in the size output")
    if "code_end" not in fig:
        raise ValueError("no 'code and data end' line in the size output")
    names = ["code", "rodata", "data", "codehi", "init", "bss", "modules_total"]
    fig.update(zip(names, total))
    return fig


def line_for(commit, kstart, fig):
    vals = [commit, f"${kstart:04X}", f"${fig['code_end']:04X}", str(fig["room_below_cf00"]),
            f"${fig['bss_codehi_end']:04X}" if "bss_codehi_end" in fig else "",
            str(fig.get("room_below_fffa", "")),
            str(fig["code"]), str(fig["rodata"]), str(fig["data"]), str(fig["codehi"]), str(fig["init"]),
            str(fig["bss"]), str(fig["modules_total"])]
    return "\t".join(vals) + "\n"


def append(ledger, commit, kstart, fig):
    new = not os.path.exists(ledger) or os.path.getsize(ledger) == 0
    with open(ledger, "a") as f:
        if new:
            f.write("\t".join(HEADER) + "\n")
        f.write(line_for(commit, kstart, fig))


PROGRAM_HEADER = ["commit", "program", "cx_bytes"]


def program_rows(commit, bindir):
    """One (commit, program, bytes) row per CX file in the directory, sorted by name (dot files are not programs)."""
    return [(commit, name, os.path.getsize(os.path.join(bindir, name)))
            for name in sorted(os.listdir(bindir))
            if not name.startswith(".") and os.path.isfile(os.path.join(bindir, name))]


def append_programs(ledger, commit, bindir):
    rows = program_rows(commit, bindir)
    new = not os.path.exists(ledger) or os.path.getsize(ledger) == 0
    with open(ledger, "a") as f:
        if new:
            f.write("\t".join(PROGRAM_HEADER) + "\n")
        for c, name, n in rows:
            f.write("\t".join([c, name, str(n)]) + "\n")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--commit", required=True, help="the commit the size output is for")
    ap.add_argument("--size-file", help="the make size output (default: stdin)")
    ap.add_argument("--ledger", default=os.path.join(os.path.dirname(__file__), "..", "docs", "size-ledger.tsv"))
    ap.add_argument("--kernel-inc", default=os.path.join(os.path.dirname(__file__), "..", "src", "kernel", "k.inc"))
    ap.add_argument("--programs", help="a directory of CX programs (build/root/bin): append their sizes instead")
    ap.add_argument("--program-ledger", default=os.path.join(os.path.dirname(__file__), "..", "docs",
                                                              "program-size-ledger.tsv"))
    a = ap.parse_args(argv)
    if a.programs:
        rows = append_programs(a.program_ledger, a.commit, a.programs)
        return "".join("\t".join([c, n, str(b)]) + "\n" for c, n, b in rows)
    text = open(a.size_file).read() if a.size_file else sys.stdin.read()
    kstart = parse_kstart(open(a.kernel_inc).read())
    fig = parse_size(text)
    append(a.ledger, a.commit, kstart, fig)
    return line_for(a.commit, kstart, fig)


if __name__ == "__main__":
    print(main(), end="")
