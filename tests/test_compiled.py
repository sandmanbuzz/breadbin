"""S14 on the machine: cc.py compiles a C program on the host, the .s goes on a test disk, `as`
assembles it on the C64, the result runs, and the output is checked. Build: `make all` first."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402
import cc  # noqa: E402

HELLO = 'int main() {\n  puts("hello, world!\\n");\n  return 0;\n}\n'

LOOP = """\
int main() {
  int i = 0;
  while (i < 5) {
    puts("tick\\n");
    i = i + 1;
  }
  return 0;
}
"""


def make_disk(name, asm):
    """A copy of the breadbin image with /home/<name>.s added (the image is the root filesystem)."""
    tmp = tempfile.mkdtemp(prefix="cc-")
    root = os.path.join(tmp, "root")
    shutil.copytree(os.path.join(ROOT, "build", "root"), root)
    with open(os.path.join(root, "home", name + ".s"), "w", encoding="ascii") as f:
        f.write(asm)
    img = os.path.join(ROOT, "build", "t_cc_" + name + ".d64")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "build", img,
                    "--boot", os.path.join(ROOT, "build", "breadbin.prg"), "--root", root,
                    "--dev", "console:1", "--dev", "null:0"], check=True, capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return img


class Compiled(unittest.TestCase):
    def run_compiled(self, name, src):
        img = make_disk(name, cc.compile_c(src))
        with Vice(img) as v:
            v.wait_shell()
            assembled = v.run(f"as /home/{name}.s /home/{name}", timeout=600)
            self.assertIn("bytes", assembled, assembled)       # as's success line
            out = v.run(f"/home/{name}", timeout=120)
            if not out:       # say what the machine showed, not just that it was empty
                self.fail(f"no output; as said {assembled!r}; screen:\n{v.screen()}")
            return out

    def test_hello(self):
        self.assertEqual(self.run_compiled("cchello", HELLO).splitlines(), ["hello, world!"])

    def test_loop_counts_to_five(self):
        self.assertEqual(self.run_compiled("ccloop", LOOP).splitlines(), ["tick"] * 5)


if __name__ == "__main__":
    unittest.main()
