"""The p-code VM (src/pvm/pvm.s, docs/design/pvm.md) on the machine: bytecode programs are linked
against the VM's shared library (CX format 2 importing /lib/pvm, tools/pvmlink.py) on the host,
put in /home on a copy of the root, and run under the real kernel, whose syscalls clobber $08-$1F
where the VM keeps its eval stack. Build: `make all` first (it puts /lib/pvm on the root). Needs
ca65 and ld65 (the container image has them)."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402
import test_pvm  # noqa: E402

# PLASMA's compiler output for the benchmark (docs/design/pvm.md section 3): 469
BENCH = open(os.path.join(ROOT, "src", "pvm", "test", "bench.s")).read() + """
f_main: P_FUNC
        P_W PO_CALL, _C003
        P_W PO_CALL, f_pdec
        P_OP PO_RET
"""

# n + f(n - 1), 120 deep, under a pending 1000: ENTER spills at every level
REC = """
f_rec:  P_FUNC
        P_ENTER 2, 1
        P_B PO_LLW, 0
        P_BR PO_BRTRU, @r
        P_CN 0
        P_B PO_LEAVE, 2
@r:     P_B PO_LLW, 0
        P_OP PO_DUP
        P_OP PO_DECR
        P_W PO_CALL, f_rec
        P_OP PO_ADD
        P_B PO_LEAVE, 2
f_main: P_FUNC
        P_W PO_CW, 1000
        P_B PO_CB, %d
        P_W PO_CALL, f_rec
        P_W PO_CALL, f_pdec
        P_OP PO_DROP
        P_W PO_CALL, f_pdec
        P_OP PO_RET
"""

# sleeps 30,000 ticks (over 8 minutes), then prints 1: something to share the library with
SLP = """
SYSN_SLEEP = (SYS_SLEEP - SYS_BASE) / 3
f_main: P_FUNC
        P_W PO_CW, 30000
        P_SYS SYSN_SLEEP
        P_OP PO_DROP
        P_CN 1
        P_W PO_CALL, f_pdec
        P_OP PO_RET
"""

# exec(path) with no argv; prints 1 only if exec came back
EXEC = """
SYSN_SPAWN = (SYS_SPAWN - SYS_BASE) / 3
f_main: P_FUNC
        P_W PO_LA, path
        P_W PO_SAW, r0
        P_CN 0
        P_W PO_SAW, r1
        P_B PO_CB, SP_EXEC
        P_CN 0
        P_SYSY SYSN_SPAWN
        P_OP PO_DROP
        P_CN 1
        P_W PO_CALL, f_pdec
        P_OP PO_RET
.segment "RODATA"
path:   .byte "%s", 0
.segment "CODE"
"""

# name -> bytecode source (with the decimal printer)
PROGRAMS = {
    "pvmbench": BENCH,
    "pvmrec": REC % 120,
    "pvmdeep": REC % 200,       # about 1,400 bytes of frame stack: past the prelude's 1 KB
    "pvmslp": SLP,
    "pvmxp": EXEC % "/home/pvmrec",    # p-code execs p-code: the library stays, one reference
    "pvmxn": EXEC % "/bin/uname",      # p-code execs native: the library goes
}

# CX format 2 header: "CX" 2, image, bss, relocs, library relocs (2 each), library id (2), path (16)
CX2_ID, CX2_PATH = 11, 13


def broken(cx, lib_id=None, path=None):
    """A copy of a format 2 file importing another library id or path."""
    b = bytearray(cx)
    assert b[:3] == b"CX\x02"
    if lib_id is not None:
        b[CX2_ID:CX2_ID + 2] = lib_id.to_bytes(2, "little")
    if path is not None:
        b[CX2_PATH:CX2_PATH + 16] = path.encode().ljust(16, b"\0")
    return bytes(b)


def label(name):
    with open(os.path.join(ROOT, "build", "kernel.lbl")) as f:
        for line in f:
            m = re.match(r"al ([0-9A-F]+) \.%s$" % name, line.strip())
            if m:
                return int(m.group(1), 16)
    raise KeyError(name)


def make_disk():
    tmp = tempfile.mkdtemp(prefix="pvm-")
    try:
        root = os.path.join(tmp, "root")
        shutil.copytree(os.path.join(ROOT, "build", "root"), root)
        for name, body in PROGRAMS.items():
            d = os.path.join(tmp, name)
            os.mkdir(d)
            shutil.copy(test_pvm.build_cx(test_pvm.PDEC + body, d), os.path.join(root, "home", name))
        with open(os.path.join(root, "home", "pvmrec"), "rb") as f:
            rec = f.read()
        lid = int.from_bytes(rec[CX2_ID:CX2_ID + 2], "little")
        for name, data in (("pvmbadid", broken(rec, lib_id=lid ^ 1)),
                           ("pvmnolib", broken(rec, path="/lib/nope"))):
            with open(os.path.join(root, "home", name), "wb") as f:
                f.write(data)
        img = os.path.join(ROOT, "build", "t_pvm.d64")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "build", img,
                        "--boot", os.path.join(ROOT, "build", "breadbin.prg"), "--root", root,
                        "--dev", "console:1", "--dev", "null:0"], check=True, capture_output=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return img


class PCode(unittest.TestCase):
    """Bytecode programs on the VM under the real kernel. One VICE session for all three."""

    @classmethod
    def setUpClass(cls):
        cls.results = {}
        with Vice(make_disk()) as v:
            v.wait_shell()
            for name in PROGRAMS:
                cls.results[name] = v.run(f"/home/{name}", timeout=120)
                # clear=False: run() types "clear" first otherwise, which sets $? to its own 0
                cls.results[name + "?"] = v.run("echo $?", clear=False, timeout=30)

    def test_plasma_compiler_output(self):
        self.assertEqual(self.results["pvmbench"].split(), ["469"])
        self.assertEqual(self.results["pvmbench?"].split(), ["0"])

    def test_recursion_spills_across_syscalls(self):
        self.assertEqual(self.results["pvmrec"].split(), ["7260", "1000"])
        self.assertEqual(self.results["pvmrec?"].split(), ["0"])

    def test_frame_stack_overflow_exits_with_enomem(self):
        self.assertEqual(self.results["pvmdeep"].split(), [])
        self.assertEqual(self.results["pvmdeep?"].split(), ["12"])


class SharedVM(unittest.TestCase):
    """/lib/pvm is loaded once for every p-code process, and freed after the last one."""

    def test_one_copy_shared_and_refused_when_wrong(self):
        pg_used, npool = label("pg_used"), (int(re.search(
            r"^KSTART\s*=\s*\$([0-9A-Fa-f]+)", open(os.path.join(ROOT, "src", "kernel", "k.inc")).read(),
            re.M).group(1), 16) >> 8) - 8
        lib_base, lib_ref = label("lib_base"), label("lib_ref")
        lib_np = label("lib_np")

        with Vice(make_disk()) as v:
            v.wait_shell()

            def used():
                return sum(1 for b in v.mem(pg_used, pg_used + npool - 1) if b)

            def libs():
                return list(v.mem(lib_base, lib_base + 1)), list(v.mem(lib_ref, lib_ref + 1))

            base = used()
            self.assertEqual(libs()[0], [0, 0])
            pids = [v.run("/home/pvmslp &", clear=False).strip("[]")]
            one = used()
            pids.append(v.run("/home/pvmslp &", clear=False).strip("[]"))
            two = used()
            bases, refs = libs()
            self.assertEqual(sorted(bases)[0], 0, bases)                # one library resident
            self.assertEqual(sorted(refs), [0, 2], refs)                # used by both
            prog = two - one
            lib_pages = max(v.mem(lib_np, lib_np + 1))
            self.assertEqual(lib_pages, 10)                             # 2,544 bytes
            self.assertEqual(one - base, prog + lib_pages)              # the second paid no library
            self.assertIn("exec format", v.run("/home/pvmbadid", clear=False))
            self.assertIn("exec format", v.run("/home/pvmnolib", clear=False))
            self.assertIn("exec format", v.run("/lib/pvm", clear=False))    # a library, not a program
            self.assertIn("exec format", v.run("mod load /lib/pvm", clear=False))
            self.assertEqual(used(), two)
            self.assertEqual(libs(), (bases, refs))
            v.run("kill " + pids[0], clear=False)
            self.assertEqual(sorted(libs()[1]), [0, 1])
            self.assertEqual(used(), one)
            v.run("kill " + pids[1], clear=False)
            self.assertEqual(libs(), ([0, 0], [0, 0]))                  # freed with the last user
            self.assertEqual(used(), base)
            # loaded afresh, and a mismatched id with nobody holding it leaves nothing behind
            self.assertIn("exec format", v.run("/home/pvmbadid", clear=False))
            self.assertEqual(used(), base)
            self.assertEqual(v.run("/home/pvmrec", clear=False).split(), ["7260", "1000"])
            self.assertEqual(used(), base)
            self.assertEqual(libs()[0], [0, 0])
            # exec with a library, both ways and in: no reference left behind
            for cmd, out in (("/home/pvmxp", ["7260", "1000"]), ("/home/pvmxn", ["breadbin"]),
                             ("exec /home/pvmrec", ["7260", "1000"])):
                self.assertEqual(v.run(cmd, clear=False).split()[:len(out)], out, cmd)
                self.assertEqual(libs(), ([0, 0], [0, 0]), cmd)
                self.assertEqual(used(), base, cmd)
            # and in a pipeline, as the story's acceptance puts it (a pipe takes a page of its own)
            before = v.run("free", clear=False)
            v.run("/home/pvmslp | /home/pvmslp &", clear=False)
            self.assertEqual(sorted(libs()[1]), [0, 2])
            self.assertEqual(used(), base + 2 * prog + lib_pages + 1)
            during = v.run("free", clear=False)
            self.assertNotEqual(before, during)
            for line in v.run("ps", clear=False).splitlines():
                if "pvmslp" in line:
                    v.run("kill " + line.split()[0], clear=False)
            self.assertEqual(libs(), ([0, 0], [0, 0]))
            self.assertEqual(used(), base)
            self.assertEqual(v.run("free", clear=False), before)
            print("pages: base %d, one p-code process %d (library %d), two %d"
                  % (base, one - base, lib_pages, two - base), file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
