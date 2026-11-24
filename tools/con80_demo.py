#!/usr/bin/env python3
"""Build the con80 tech demo: a standalone PRG that plays a script through the 6502 driver.

    python3 tools/con80_demo.py FONT [SCRIPT] [-o demo.prg] [--frames DIR] [--run]

SCRIPT (default experiments/con80/demo.txt), one item per line:
    $ command      typed slowly after a "$ " prompt (the 'shell')
    # narration    typed quickly, a shell comment
    @wait N        pause N frames (50 per second PAL)
    @clear         form feed
    @each ... @end the output lines in between are written one per call (no look-ahead)
    @snap NAME     host only: with --frames, write NAME.png of the screen here
    anything else  output; consecutive output lines go out as one write
The PRG is run by tools/ultimate.py's run_prg (it resets the machine) under the ultimate lock; this
tool only does so with --run. FONT: a doubled-nibble 2048-byte font (see soft80_render.py); it is
embedded in the PRG, so keep the PRG out of the repo.
"""
import argparse
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soft80_render as m  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "experiments", "con80")
OP_WAIT, OP_CLEAR, OP_WRITE, OP_TYPE = 1, 2, 3, 4
TYPE_CMD, TYPE_NARR, SETTLE, NARR_HOLD = 4, 1, 25, 45
BORDER, COLOUR = 14, (14 << 4) | 6      # light blue on blue

CFG = """MEMORY {
  FNT: start = $4000, size = $1000, file = %O, fill = yes;
  GL:  start = $5000, size = $4800, file = %O;
  B:   start = $0340, size = $0040, file = "";     # the glue's own variables, not the driver's (they are in the bitmap tail)
}
SEGMENTS { FONTSEG: load = FNT, type = ro; CODE: load = FNT, type = ro; RODATA: load = FNT, type = ro;
           BSS: load = B, type = bss; GLUE: load = GL, type = ro; }
"""
ZP = {"p1": 0x50, "p2": 0x52, "p3": 0x54, "p4": 0x56, "tmp0": 0x58, "tmp1": 0x59, "tmp2": 0x5A, "tmp3": 0x5B}


def chunks(text):
    """Split ASCII text into pieces of at most 250 bytes, at line ends where it can."""
    while text:
        if len(text) <= 250:
            yield text
            return
        cut = text.rfind("\n", 0, 250) + 1 or 250
        yield text[:cut]
        text = text[cut:]


def parse(script):
    """Script text -> [(op, ...)] with ops ('wait', n) ('clear',) ('write', str) ('type', delay, str)
    ('snap', name)."""
    ops, out, each = [], [], False

    def flush():
        if out:
            if each:
                ops.extend(("write", line + "\n") for line in out)
            else:
                ops.extend(("write", c) for c in chunks("".join(line + "\n" for line in out)))
            ops.append(("wait", 30))
            out.clear()

    for raw in script.splitlines():
        line = raw.rstrip()
        if line.startswith("@wait "):
            flush()
            ops.append(("wait", int(line.split()[1])))
        elif line == "@clear":
            flush()
            ops.append(("clear",))
        elif line == "@each":
            flush()
            each = True
        elif line == "@end":
            flush()
            each = False
        elif line.startswith("@snap"):
            flush()
            ops.append(("snap", line.split()[1]))
        elif line.startswith("$ "):
            flush()
            ops += [("write", "$ "), ("type", TYPE_CMD, line[2:] + "\n"), ("wait", SETTLE)]
        elif line.startswith("#"):
            flush()
            ops += [("type", TYPE_NARR, line + "\n"), ("wait", NARR_HOLD)]
        else:
            out.append(line)
    flush()
    return ops


def encode(ops):
    b = bytearray()
    for op in ops:
        if op[0] == "wait":
            n = op[1]
            while n:
                k = min(n, 255)
                b += bytes([OP_WAIT, k])
                n -= k
        elif op[0] == "clear":
            b += bytes([OP_CLEAR])
        elif op[0] == "write":
            for c in chunks(op[1]):
                b += bytes([OP_WRITE, len(c)]) + c.encode("ascii")
        elif op[0] == "type":
            for c in chunks(op[2]):
                b += bytes([OP_TYPE, op[1], len(c)]) + c.encode("ascii")
    return bytes(b + b"\x00")


def replay(ops, font, frames_dir=None):
    """Run the script on the host model; returns the model. Snaps go to frames_dir."""
    s = m.Soft80(font, COLOUR >> 4, COLOUR & 15)
    for op in ops:
        if op[0] == "write":
            s.write(op[1])
        elif op[0] == "type":
            s.write(op[2])
        elif op[0] == "clear":
            s.write("\f")
        elif op[0] == "snap" and frames_dir:
            s.to_png(os.path.join(frames_dir, op[1] + ".png"), 2)
    return s


def build(font, ops, tmp):
    """font: kernel-order doubled-nibble bytes -> the PRG as bytes."""
    with open(os.path.join(tmp, "kernel_syms.inc"), "w") as f:
        f.write("r0 = $02\nr1 = $04\n")
        f.write("".join("%s = $%02X\n" % kv for kv in ZP.items()))
        f.write("DEMO_BORDER = %d\nDEMO_COLOUR = $%02X\n" % (BORDER, COLOUR))
    with open(os.path.join(tmp, "font_glyph.bin"), "wb") as f:
        f.write(m.glyphs(font))
    with open(os.path.join(tmp, "script.bin"), "wb") as f:
        f.write(encode(ops))
    with open(os.path.join(tmp, "d.cfg"), "w") as f:
        f.write(CFG)
    subprocess.run(["ca65", "--bin-include-dir", tmp, "-I", tmp, "-I", os.path.join(ROOT, "src", "mod"), "-I", SRC, "-o", os.path.join(tmp, "d.o"),
                    os.path.join(SRC, "demo.s")], check=True)
    subprocess.run(["ld65", "-C", os.path.join(tmp, "d.cfg"), "-Ln", os.path.join(tmp, "d.lbl"),
                    "-o", os.path.join(tmp, "d.bin"), os.path.join(tmp, "d.o")], check=True)
    with open(os.path.join(tmp, "d.bin"), "rb") as f:
        payload = f.read()
    # $0801: 10 SYS 20480 ($5000), then zeros up to the payload at $4000
    stub = bytes([0x0B, 0x08, 0x0A, 0x00, 0x9E]) + b"20480" + bytes([0, 0, 0])
    return b"\x01\x08" + stub + bytes(0x4000 - 0x0801 - len(stub)) + payload


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("font")
    ap.add_argument("script", nargs="?", default=os.path.join(SRC, "demo.txt"))
    ap.add_argument("-o", "--out", default="con80demo.prg")
    ap.add_argument("--frames", help="directory for host-model PNGs at @snap lines")
    ap.add_argument("--run", action="store_true", help="send it to the Ultimate (BREADBIN_ULTIMATE, ultimate lock)")
    a = ap.parse_args()
    with open(a.script) as f:
        ops = parse(f.read())
    font = m.load_font(a.font)
    if a.frames:
        os.makedirs(a.frames, exist_ok=True)
        replay(ops, font, a.frames)
    with tempfile.TemporaryDirectory() as tmp:
        prg = build(font, ops, tmp)
    with open(a.out, "wb") as f:
        f.write(prg)
    print("%s: %d bytes, script %d bytes" % (a.out, len(prg), len(encode(ops))))
    if a.run:
        from ultimate import Ultimate
        Ultimate.from_env().run_prg(prg)
        print("sent")


if __name__ == "__main__":
    main()
