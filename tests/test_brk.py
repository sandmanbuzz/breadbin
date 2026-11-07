"""BRK kills the user process that executes it (SIGKILL) and the machine carries on: the shell
survives, the program is gone from `ps`, and the kernel's BRK panic is not reached. The program
is assembled on the C64 with `as` from a source put on a copy of the test disk, as in
tests/test_compiled.py. Needs the VICE ROMs (tools/setup-vice-roms.sh) and `make all`."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402


def make_disk(name, asm):
    """A copy of the breadbin image with /home/<name>.s added (the image is the root filesystem)."""
    tmp = tempfile.mkdtemp(prefix="brk-")
    root = os.path.join(tmp, "root")
    shutil.copytree(os.path.join(ROOT, "build", "root"), root)
    with open(os.path.join(root, "home", name + ".s"), "w", encoding="ascii") as f:
        f.write(asm)
    img = os.path.join(ROOT, "build", "t_brk_" + name + ".d64")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "build", img,
                    "--boot", os.path.join(ROOT, "build", "breadbin.prg"), "--root", root,
                    "--dev", "console:1", "--dev", "null:0"], check=True, capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return img

BRK_SRC = """\
start:  lda #0
        brk                 ; no operand byte follows: the kernel kills us here
        lda #1
        jmp sys_exit
"""


class Brk(unittest.TestCase):
    def test_brk_kills_only_the_program(self):
        img = make_disk("brkprog", BRK_SRC)
        with Vice(img) as v:
            v.wait_shell()
            assembled = v.run("as /home/brkprog.s /home/brkprog", timeout=600)
            self.assertIn("bytes", assembled, assembled)
            v.run("/home/brkprog", timeout=120)          # returns at the prompt: the shell survived
            self.assertEqual(v.run("echo alive"), "alive")
            self.assertNotIn("brkprog", v.run("ps").split()[5:])
            self.assertNotIn("kernel panic", v.screen().lower())


if __name__ == "__main__":
    unittest.main()
