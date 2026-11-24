"""pvm_bench: 6502 cycles for the docs/design/pvm.md benchmark three ways, printed as one JSON object.

    python3 tools/pvm_bench.py

- pvm:  src/pvm/test/bench.s (upstream PLASMA compiler output) on the ported VM, under tools/asim.py
- ccpy: src/pvm/test/bench.c through tools/cc.py, native, under py65 (tools/test_cc_run.py's harness)
- cc65: the same C through cl65 -t sim6502 -Oirs, under sim65 -c
- ccpcode: the same C through tools/cc.py --pcode (L2) on the same VM, under tools/asim.py

Each figure is the program's cycles less an empty program's under the same harness, so start-up
and exit are not counted. The two simulators count documented 6502 cycles; neither models the
C64's badlines, so these are CPU-bound ratios, not C64 wall time. Needs ca65, ld65, cl65, sim65, py65.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import cc  # noqa: E402
import test_cc_run  # noqa: E402
import test_pvm  # noqa: E402
import test_cc_pcode  # noqa: E402

BENCH = os.path.join(ROOT, "src", "pvm", "test")
EXPECT = 469


def pvm(body_main):
    """Cycles and result of a bytecode main under asim."""
    with open(os.path.join(BENCH, "bench.s")) as f:
        bench = f.read()
    body = bench + "f_main:\n" + body_main + """
        P_W PO_SAW, buf
        P_CN 2
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
"""
    with tempfile.TemporaryDirectory(prefix="pvmb-") as d:
        r = test_pvm.build_run(body, d)
    return r.cycles, int.from_bytes(r.out[:2], "little")


def ccpy(src):
    """Cycles and main's result of cc.py output under py65 (test_cc_run's stubs and layout)."""
    asm = cc.compile_c(src)
    asm = "".join(line + "\n" for line in asm.split("\n") if not line.startswith("cc_ptr = "))
    with tempfile.TemporaryDirectory(prefix="ccb-") as d:
        p = lambda n: os.path.join(d, n)  # noqa: E731
        with open(p("prog.s"), "w") as f:
            f.write(test_cc_run.HEADER + asm + test_cc_run.STUBS)
        with open(p("prog.cfg"), "w") as f:
            f.write(test_cc_run.CFG)
        subprocess.run(["ca65", "-g", "-o", p("prog.o"), p("prog.s")], check=True, capture_output=True)
        subprocess.run(["ld65", "-C", p("prog.cfg"), "-Ln", p("prog.lbl"), "-o", p("prog.bin"),
                        p("prog.o")], check=True, capture_output=True)
        image = open(p("prog.bin"), "rb").read()
        acc = int(re.search(r"al ([0-9A-F]+) \.acc$", open(p("prog.lbl")).read(), re.M).group(1), 16)
    mpu = test_cc_run.MPU()
    mem = mpu.memory
    mem[test_cc_run.ORG:test_cc_run.ORG + len(image)] = image
    mpu.pc = test_cc_run.ORG
    mem[0xFC], mem[0xFD] = test_cc_run.OUT & 0xFF, test_cc_run.OUT >> 8
    for _ in range(20_000_000):
        if mem[mpu.pc] == 0:
            break
        mpu.step()
    else:
        raise RuntimeError("cc.py program did not exit")
    return mpu.processorCycles, mem[acc] | mem[acc + 1] << 8


def ccpcode(src):
    """Cycles and exit status (main's result & 255) of cc.py --pcode output under asim."""
    r = test_cc_pcode.run_full(src)
    return r.cycles, r.exit


def cc65(src):
    """Cycles and exit status (main's result & 255) under sim65."""
    with tempfile.TemporaryDirectory(prefix="c65b-") as d:
        c, exe = os.path.join(d, "b.c"), os.path.join(d, "b")
        with open(c, "w") as f:
            f.write(src)
        subprocess.run(["cl65", "-t", "sim6502", "-Oirs", "-o", exe, c], check=True, capture_output=True)
        p = subprocess.run(["sim65", "-c", exe], capture_output=True, text=True)
    cycles = int(re.search(r"(\d+) cycles", p.stdout + p.stderr).group(1))
    return cycles, p.returncode


def main():
    for tool in ("ca65", "ld65", "cl65", "sim65"):
        if not shutil.which(tool):
            print(json.dumps({"error": "needs " + tool}))
            return 1
    with open(os.path.join(BENCH, "bench.c")) as f:
        src = f.read()
    empty = "int main() {\n  return 0;\n}\n"
    out = {}
    for name, fn, full, base in (("pvm", pvm, "        P_W PO_CALL, _C003\n", "        P_CN 0\n"),
                                 ("ccpy", ccpy, src, empty), ("cc65", cc65, src, empty),
                                 ("ccpcode", ccpcode, src, empty)):
        cyc, res = fn(full)
        cyc0, _ = fn(base)
        ok = res == (EXPECT & 0xFF if name in ("cc65", "ccpcode") else EXPECT)
        if not ok:
            print(json.dumps({"error": "%s gave %d" % (name, res)}))
            return 1
        out[name] = cyc - cyc0
    out["pvm_vs_ccpy"] = round(out["pvm"] / out["ccpy"], 2)
    out["pvm_vs_cc65"] = round(out["pvm"] / out["cc65"], 2)
    out["ccpcode_vs_ccpy"] = round(out["ccpcode"] / out["ccpy"], 2)
    out["ccpcode_vs_pvm"] = round(out["ccpcode"] / out["pvm"], 2)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
