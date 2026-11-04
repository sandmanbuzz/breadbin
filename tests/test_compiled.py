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


# 82 characters: as drops input past 127 characters a line, so the string is emitted over several lines
LONG_LINE = "a line of text that is longer than what an old as line held, so it has to be split"

SLICE2 = """\
int sub(int a, int b) { return a - b; }
int sum3(int *p) { return p[0] + p[1] + p[2]; }
int main() {
  int a[3];
  int i;
  char c = 321;
  for (i = 0; i < 3; i = i + 1) a[i] = i + 1;
  if (sum3(a) == 6) puts("sum\\n"); else puts("nosum\\n");
  if (sub(10, 3) == 7) puts("sub\\n"); else puts("nosub\\n");
  if (c == 65) puts("char\\n"); else puts("nochar\\n");
  return 0;
}
"""

OPS = """\
int f() { return 3 - 1; }
int main() {
  int a = 5;
  if (a == 5) puts("eq\\n"); else puts("ne\\n");
  if (f() - 1 == 1) puts("sub\\n"); else puts("nosub\\n");
  if (a < 3) puts("lt\\n"); else puts("ge\\n");
  puts("%s\\n");
  return 0;
}
""" % LONG_LINE


def make_disk(programs):
    """A copy of the breadbin image with each program's .s in /home (the image is the root
    filesystem). One disk and one VICE session serve every program, so the boot is paid once."""
    tmp = tempfile.mkdtemp(prefix="cc-")
    root = os.path.join(tmp, "root")
    shutil.copytree(os.path.join(ROOT, "build", "root"), root)
    for name, asm in programs.items():
        with open(os.path.join(root, "home", name + ".s"), "w", encoding="ascii") as f:
            f.write(asm)
    img = os.path.join(ROOT, "build", "t_cc_all.d64")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "build", img,
                    "--boot", os.path.join(ROOT, "build", "breadbin.prg"), "--root", root,
                    "--dev", "console:1", "--dev", "null:0"], check=True, capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return img


# the programs run on the machine, in one VICE session: name -> C source
PROGRAMS = {
    "cchello": HELLO,
    "ccloop": LOOP,
    "ccops": OPS,
    "ccslice2": SLICE2,
}


class Compiled(unittest.TestCase):
    """cc.py -> the disk -> `as` on the C64 -> run -> the output. One VICE session for all four."""

    @classmethod
    def setUpClass(cls):
        cls.results = {}
        img = make_disk({name: cc.compile_c(src) for name, src in PROGRAMS.items()})
        with Vice(img) as v:
            v.wait_shell()
            for name in PROGRAMS:
                assembled = v.run(f"as /home/{name}.s /home/{name}", timeout=600)
                if "bytes" not in assembled:
                    cls.results[name] = ("as", assembled)
                    continue
                out = v.run(f"/home/{name}", timeout=120)
                cls.results[name] = ("ok", out) if out else ("empty", (assembled, v.screen()))

    def out(self, name):
        kind, value = self.results[name]
        self.assertEqual(kind, "ok", f"{name}: {kind}: {value}")
        return value

    def test_hello(self):
        self.assertEqual(self.out("cchello").splitlines(), ["hello, world!"])

    def test_loop_counts_to_five(self):
        self.assertEqual(self.out("ccloop").splitlines(), ["tick"] * 5)

    def test_operators_branches_and_a_long_string(self):
        # the screen is 40 columns: a long line wraps at a space, and the space is lost at the
        # break, so compare with all whitespace removed on both sides (no character may be lost)
        self.assertEqual("".join(self.out("ccops").split()), "eqsubge" + "".join(LONG_LINE.split()))

    def test_parameters_arrays_pointers_char_and_for(self):
        self.assertEqual(self.out("ccslice2").split(), ["sum", "sub", "char"])


if __name__ == "__main__":
    unittest.main()
