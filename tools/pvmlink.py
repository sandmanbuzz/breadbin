"""pvmlink: build the p-code VM library and link p-code programs against it (CX formats 3 and 2,
tools/cx.py). Prints one JSON object.

    python3 tools/pvmlink.py lib OUTDIR                       -> OUTDIR/pvm (format 3), OUTDIR/pvmstub.s
    python3 tools/pvmlink.py prog OUT LIBDIR OBJ...           -> OUT (format 2, importing /lib/pvm)

The library's exports are pvm_init, pvm_interp (code) and pvm_errno (zero page). A program is
linked three times: at $0000 and $0100 with the library stub at $0000, and at $0000 with the stub
at $0100; the differences are the program's and the library's relocations.
"""
import json
import os
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import cx  # noqa: E402

PVM = os.path.join(ROOT, "src", "pvm")
EXPORTS = ["pvm_init", "pvm_interp", "zp:pvm_errno"]
LIBPATH = "/lib/pvm"


def sh(*a):
    p = subprocess.run(a, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"{a[0]} failed:\n{p.stdout}{p.stderr}")


def build_lib(d):
    """OUTDIR/pvm and OUTDIR/pvmstub.s; returns (path, id)."""
    os.makedirs(d, exist_ok=True)
    j = lambda n: os.path.join(d, n)  # noqa: E731
    sh("ca65", "-I", os.path.join(ROOT, "include"), "-o", j("pvm.o"), os.path.join(PVM, "pvm.s"))
    cfg = os.path.join(PVM, "pvm.cfg")
    sh("ld65", "-C", cfg, "-S", "0", "-Ln", j("pvm.lbl"), "-o", j("pvm.0"), j("pvm.o"))
    sh("ld65", "-C", cfg, "-S", "256", "-o", j("pvm.1"), j("pvm.o"))
    with open(j("pvm.lbl")) as f:
        ex = cx.lib_exports(f.read(), EXPORTS)
    with open(j("pvm.0"), "rb") as f:
        a = f.read()
    with open(j("pvm.1"), "rb") as f:
        b = f.read()
    data, lid = cx.make_lib(a, b, 0, ex)
    with open(j("pvm"), "wb") as f:
        f.write(data)
    with open(j("pvmstub.s"), "w") as f:
        f.write(cx.lib_stub(ex))
    return j("pvm"), lid


def link_prog(out, libdir, objs):
    """OUT, format 2, from ca65 objects linked against the library built in libdir. The
    intermediate files go beside the first object, not beside OUT (which may be a disk's root)."""
    d = os.path.dirname(os.path.abspath(objs[0]))
    stem = os.path.join(d, os.path.basename(out))
    stub = os.path.join(libdir, "pvmstub.s")
    for base, tag in ((cx.LIBBASE, "a"), (cx.LIBBASE + 0x100, "b")):
        sh("ca65", "-D", "LIBBASE=$%04X" % base, "-o", "%s.stub%s.o" % (stem, tag), stub)
    cfg = os.path.join(PVM, "prog.cfg")
    sh("ld65", "-C", cfg, "-S", "0", "-Ln", stem + ".lbl", "-o", stem + ".0", *objs, stem + ".stuba.o")
    sh("ld65", "-C", cfg, "-S", "256", "-o", stem + ".1", *objs, stem + ".stuba.o")
    sh("ld65", "-C", cfg, "-S", "0", "-o", stem + ".2", *objs, stem + ".stubb.o")
    with open(os.path.join(libdir, "pvm"), "rb") as f:
        lib = f.read()
    with open(stem + ".lbl") as f:
        bss = cx.bss_size(f.read())
    bins = []
    for n in "012":
        with open(stem + "." + n, "rb") as f:
            bins.append(f.read())
    data = cx.make_import(*bins, bss, LIBPATH, lib[9] | lib[10] << 8)
    with open(out, "wb") as f:
        f.write(data)
    return out


def main():
    try:
        if sys.argv[1] == "lib":
            path, lid = build_lib(sys.argv[2])
            print(json.dumps({"lib": path, "id": "%04X" % lid, "bytes": os.path.getsize(path)}))
        elif sys.argv[1] == "prog":
            out = link_prog(sys.argv[2], sys.argv[3], sys.argv[4:])
            print(json.dumps({"prog": out, "bytes": os.path.getsize(out)}))
        else:
            raise ValueError("lib or prog")
    except (RuntimeError, ValueError, IndexError) as e:
        print(json.dumps({"error": str(e)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
