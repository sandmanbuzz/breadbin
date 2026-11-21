"""vprof: where the emulated time of a command goes, from VICE tracepoints.

A tracepoint prints one line (with the registers and the emulated cycle count) and lets the
machine run on, so the measurement does not change the timing it reports (it must stay at real
speed: warp changes the emulated cycle count). The points are labels in build/kernel.lbl, or
in a module's build/mod/NAME.lbl (the module's load address comes from `mod ls`); NAME+N is N
bytes past a label. The events, in order, cut the run into phases (from one event to the next);
one point is the anchor (the block, the call, whatever repeats) and the report is per anchor hit.

    python3 tools/vprof.py build/breadbin.d64 "wc /bin/as" --setup "mod load /lib/km/fast" \
        --anchor fast:ft_read --points iec_read fast:ft_start fast:ft_good

Do not put a point on a hot label (a byte loop): every hit is a line on the monitor socket.
JiffyDOS or other ROMs: BREADBIN_VICE_ARGS as for the tests (docs/testing.md).
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

PAL_HZ = 985248

# "#1 (Trace  exec ed07)  105/$069,  28/$1c" then ".C:ed07  EE 64 E6  INC $E664 - A:08 X:00 Y:00 SP:eb ..-....C  114031099"
EVENT = re.compile(r"\(Trace\s+exec ([0-9a-f]{4})\)[^\n]*\n\.C:[0-9a-f]{4}[^\n]*?\s(\d+)\s*(?:\n|$)")


def parse_trace(text):
    """[(cycle, address)] for every tracepoint hit in the monitor's output, in order."""
    return [(int(m.group(2)), int(m.group(1), 16)) for m in EVENT.finditer(text)]


def load_labels(path):
    with open(path, encoding="utf-8") as fh:
        return {m.group(2): int(m.group(1), 16)
                for m in (re.match(r"al ([0-9A-Fa-f]+) \.(\S+)", ln) for ln in fh) if m}


def resolve(spec, base_of, root=ROOT):
    """(address, label) for `LABEL`, `MODULE:LABEL`, either with +N. base_of(module) is its load address."""
    off = 0
    if "+" in spec:
        spec, n = spec.rsplit("+", 1)
        off = int(n, 0)
    if ":" in spec:
        mod, name = spec.split(":", 1)
        lbl = load_labels(os.path.join(root, "build", "mod", mod + ".lbl"))
        base = base_of(mod)
    else:
        mod, name = None, spec
        lbl = load_labels(os.path.join(root, "build", "kernel.lbl"))
        base = 0
    if name not in lbl:
        raise KeyError(f"no label {spec}")
    return base + lbl[name] + off, spec + (f"+{off}" if off else "")


def phases(events, names, anchor):
    """The report for [(cycle, address)] events: every consecutive pair is a phase (from -> to).
    names maps an address to its label; anchor is a label (hits counted), or None for one run."""
    if not events:
        return {"anchors": 0, "window_ms": 0, "phases": []}
    labs = [names[a] for _, a in events]
    n = sum(1 for lb in labs if lb == anchor) if anchor else 1
    acc = {}
    for (c0, _), (c1, _), a, b in zip(events, events[1:], labs, labs[1:]):
        t = acc.setdefault((a, b), [0, 0])
        t[0] += 1
        t[1] += c1 - c0
    window = events[-1][0] - events[0][0]
    rows = [{"from": a, "to": b, "n": k, "ms_per_anchor": round(c / PAL_HZ * 1000 / n, 1)}
            for (a, b), (k, c) in acc.items()]
    rows.sort(key=lambda r: -r["ms_per_anchor"])
    return {"anchors": n, "window_ms": round(window / PAL_HZ * 1000, 1),
            "window_ms_per_anchor": round(window / PAL_HZ * 1000 / n, 1), "phases": rows}


def profile(image, command, points, anchor=None, setup=(), timeout=900, root=ROOT, peek=None):
    """Boot the image under VICE at real speed, run the setup commands untraced, set a tracepoint on
    each point, run `command`, and report. Needs a display (xvfb-run) and the ROMs. peek(v, base_of),
    if given, is called just before and just after the traced command; the report has its two results
    as "peek" (to check the trace against counters the machine keeps itself)."""
    import re as _re
    from vicetest import Vice
    v = Vice(image, warp=False)
    try:
        v.wait_shell()
        for s in setup:
            v.run(s)
        mods = v.run("mod ls")

        def base_of(mod):
            m = _re.search(rf"{_re.escape(mod)}\S*[^\n]*?page (\d+)", mods)
            if not m:
                raise KeyError(f"module {mod} is not loaded (mod ls: {mods!r})")
            return int(m.group(1)) << 8
        names, seen = {}, []
        for spec in points:
            addr, label = resolve(spec, base_of, root)
            names[addr] = label
            seen.append(addr)
        if anchor and anchor not in points:
            addr, label = resolve(anchor, base_of, root)
            names[addr] = label
            seen.append(addr)
        raw = []
        orig = v._cmd

        def tee(c, wait=0.15):       # the trace lines arrive on the socket whenever the monitor is read
            out = orig(c, wait)
            raw.append(out)
            return out
        v._cmd = tee
        for addr in dict.fromkeys(seen):
            v._cmd(f"tr {addr:04x}")
        v._cmd("x")
        p0 = peek(v, base_of) if peek else None
        c0 = _cycles(v)
        v.run(command, timeout=timeout, clear=True)
        wall = (_cycles(v) - c0) / PAL_HZ
        v._cmd("", wait=1.0)
        p1 = peek(v, base_of) if peek else None
        events = [e for e in parse_trace("".join(raw)) if e[1] in names]
        out = phases(events, names, anchor)
        out.update({"image": os.path.basename(image), "command": command, "wall_s": round(wall, 2),
                    "events": len(events)})
        if peek:
            out["peek"] = [p0, p1]
        return out
    finally:
        v.close()


def _cycles(v):
    out = v._cmd("sw")
    v._cmd("x")
    return int(re.search(r"Stopwatch:\s*(\d+)", out).group(1))


def from_trace(text, points, anchor, bases=None, root=ROOT):
    """The report for a saved monitor log (no emulator). bases maps a module name to its load address."""
    bases = bases or {}
    names = {}
    for spec in list(points) + ([anchor] if anchor else []):
        addr, label = resolve(spec, lambda m: bases[m], root)
        names[addr] = label
    events = [e for e in parse_trace(text) if e[1] in names]
    out = phases(events, names, anchor)
    out["events"] = len(events)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image")
    ap.add_argument("command")
    ap.add_argument("--points", nargs="+", default=["bread", "iec_read"])
    ap.add_argument("--anchor", default="iec_read")
    ap.add_argument("--setup", action="append", default=[], help="a command run first, untraced (repeatable)")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--trace", help="analyse a saved monitor log instead of running (image and command ignored)")
    ap.add_argument("--base", action="append", default=[], help="MODULE=ADDR load address, with --trace")
    a = ap.parse_args()
    try:
        if a.trace:
            with open(a.trace, encoding="utf-8") as fh:
                out = from_trace(fh.read(), a.points, a.anchor, {k: int(v, 0) for k, v in (b.split("=") for b in a.base)})
        else:
            out = profile(a.image, a.command, a.points, a.anchor, a.setup)
        out["phases"] = out["phases"][:a.top]
        print(json.dumps(out))
    except Exception as e:      # noqa: BLE001
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
