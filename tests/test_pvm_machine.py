"""The p-code VM (src/pvm/pvm.s, docs/design/pvm.md) on the machine: bytecode programs are linked
with the VM into CX files on the host (tools/test_pvm.py's build), put in /home on a copy of the
root, and run under the real kernel, whose syscalls clobber $08-$1F where the VM keeps its eval
stack. Build: `make all` first. Needs ca65 and ld65 (the container image has them)."""
import os
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

# name -> bytecode source (with the decimal printer)
PROGRAMS = {
    "pvmbench": BENCH,
    "pvmrec": REC % 120,
    "pvmdeep": REC % 200,       # about 1,400 bytes of frame stack: past the prelude's 1 KB
}


def make_disk():
    tmp = tempfile.mkdtemp(prefix="pvm-")
    try:
        root = os.path.join(tmp, "root")
        shutil.copytree(os.path.join(ROOT, "build", "root"), root)
        for name, body in PROGRAMS.items():
            d = os.path.join(tmp, name)
            os.mkdir(d)
            shutil.copy(test_pvm.build_cx(test_pvm.PDEC + body, d), os.path.join(root, "home", name))
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


if __name__ == "__main__":
    unittest.main()
