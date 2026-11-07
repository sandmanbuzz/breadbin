"""Stack high-water measurement (needs a kernel built with `make STKWATCH=1`).

Not a regression test: it runs heavy workloads and prints the largest stack a
context switch had to save (stk_hwm in proc.s), per workload.  Results go to
$STKWATCH_OUT (default build/stkwatch.txt).
"""
import os
import re
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402

OUT = os.environ.get("STKWATCH_OUT", os.path.join(ROOT, "build", "stkwatch.txt"))


def labels():
    d = {}
    for ln in open(os.path.join(ROOT, "build", "kernel.lbl")):
        f = ln.split()
        if len(f) == 3 and f[2].startswith(".stk_hwm"):
            d[f[2][1:]] = int(f[1], 16)
    return d


def prep():
    home = os.path.join(ROOT, "build", "root", "home")
    # a long assembler source: many labels, expressions, data
    src = ["; big test source", "start:  ldx #0"]
    for i in range(120):
        src += [f"l{i}:    lda #<l{i}+{i}", f"        sta $0200+{i}",
                f"        ldy #>l{i}", f"        bne l{(i + 1) % 120}"]
    src += ["done:   lda #0", "        jmp sys_exit", 'msg:    .byte "stack test", 10, 0']
    open(os.path.join(home, "big.s"), "w").write("\n".join(src) + "\n")
    # a big text file (about 3 KB), numbers shuffled for sort/grep
    lines = [f"line {(i * 37) % 211:03d} some text to sort and grep {i}" for i in range(70)]
    open(os.path.join(home, "big.txt"), "w").write("\n".join(lines) + "\n")
    p10 = "(" * 10 + "1" + ")" * 10
    deep = ["10 rem nesting", f"20 for i = 1 to 400 : a = {p10} + {p10} * {p10} : next i", "30 print a",
            "40 for i = 1 to 40 : gosub 100 : next i", "50 print d : end",
            "100 d = 0 : for j = 1 to 3 : d = d + 1 : gosub 200 : next j : return",
            "200 for k = 1 to 3 : for l = 1 to 3 : x = " + p10 + " : next l : next k : return"]
    for n in (2, 4, 6, 8, 10):
        e = "(" * n + "1" + ")" * n
        open(os.path.join(home, f"p{n}.bas"), "w").write(f"10 for i = 1 to 600 : a = {e} : next i : print a\n")
    e = "(" * 10 + "1" + "=1)" * 10
    open(os.path.join(home, "pr.bas"), "w").write(f"10 for i = 1 to 600 : a = {e} : next i : print a\n")
    open(os.path.join(home, "pu.bas"), "w").write("10 for i = 1 to 600 : a = " + "-" * 40 + "5 : next i : print a\n")
    open(os.path.join(home, "deep.bas"), "w").write("\n".join(deep) + "\n")
    subprocess.run(["python3", "tools/mkimage.py", "build", "build/stk.d64", "--boot", "build/breadbin.prg",
                    "--root", "build/root", "--dev", "console:1", "--dev", "null:0"], cwd=ROOT, check=True,
                   capture_output=True)


class Stk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.l = labels()
        prep()
        cbm = os.path.join(ROOT, "build", "t_stk9.d64")
        if os.path.exists(cbm):
            os.unlink(cbm)
        subprocess.run(["c1541", "-format", "cbmdisk,cb", "d64", cbm,
                        "-write", os.path.join(ROOT, "rootfs", "etc", "motd"), "motd,s",
                        "-write", os.path.join(ROOT, "rootfs", "home", "readme"), "readme,s"],
                       capture_output=True, check=True)
        cls.v = Vice(os.path.join(ROOT, "build", "stk.d64"), extra=["-drive9type", "1541", "-9", cbm])
        cls.v.wait_shell()
        cls.res = []

    @classmethod
    def tearDownClass(cls):
        cls.v.close()
        with open(OUT, "a") as f:
            for r in cls.res:
                f.write(r + "\n")

    def reset(self):
        self.v._cmd(f"> {self.l['stk_hwm']:04x} 00")
        d = self.v.mem(self.l["stk_hwm"], self.l["stk_hwm"] + 12)
        self.assertEqual(d[0], 0)

    def mark(self, name, out=""):
        a = self.l["stk_hwm"]
        d = self.v.mem(a, a + 13)
        nm = bytes(d[2:13]).split(b"\0")[0].decode(errors="replace")
        line = f"{name}\tkills={d[13]}\thwm={d[0]}\tby={nm}\tout={out.strip()[-60:]!r}"
        print(line)
        self.res.append(line)

    def w(self, name, cmd, timeout=240, fresh=True):
        self.reset()
        out = self.v.run(cmd, timeout=timeout)
        self.mark(name, out)
        return out

    def test_a_as(self):
        self.w("a as hello.s", "as /home/hello.s /home/h1")
        self.w("a as bigbuf.s", "as /home/bigbuf.s /home/h2")
        self.w("a as big.s (480 lines, expressions)", "as /home/big.s /home/h3")

    def test_b_basic(self):
        self.w("b basic hello.bas", "basic /home/hello.bas")
        self.w("b basic deep.bas", "basic /home/deep.bas", timeout=400)

    def test_g_basic_depth(self):
        for n in (2, 4, 6, 8, 10):
            self.w(f"g basic {n} parens ({n + 1} levels), 600 loops", f"basic /home/p{n}.bas", timeout=400)
        self.w("g basic 10 nested relational", "basic /home/pr.bas", timeout=400)
        self.w("g basic 40 unary minus", "basic /home/pu.bas", timeout=400)

    def test_c_edit(self):
        self.reset()
        v = self.v
        v.type("clear\n")
        v.wait_for("$")
        v.type("edit /home/big.txt\n")
        v.wait_for("edit:", timeout=90)
        for _ in range(3):
            v.keybuf(b"\x11" * 20)      # down x20
            time.sleep(1)
        v.keybuf(b"zzz")
        time.sleep(2)
        v.keybuf(b"\x0f")
        v.wait_for(" saved", timeout=60)
        v.keybuf(b"\x18")
        time.sleep(3)
        self.mark("c edit big.txt")

    def test_d_pipe_bg(self):
        self.reset()
        self.v.run("count > /dev/null &")
        out = self.v.run("cat /home/big.txt | sort | grep 1 | wc", timeout=240)
        out2 = self.v.run("cat /home/big.txt | sort | grep line | tail | wc", timeout=240)
        self.mark("d 3-stage pipe + bg count", out + " / " + out2)
        for p in re.findall(r"^\s*(\d+)\s+count", self.v.run("ps"), re.M):
            self.v.run("kill " + p)

    def test_e_cbm(self):
        self.reset()
        self.v.run("mount 9 /mnt")
        self.v.run("cp /home/big.txt /mnt/big")
        self.v.run("cp /mnt/readme /home/r2")
        out = self.v.run("ls -l /mnt")
        self.v.run("ls -l /home")
        self.mark("e cbm mount, cp, ls -l", out)
        self.reset()
        self.v.run("umount /mnt")

    def test_f_mod(self):
        self.reset()
        out = self.v.run("mod load /lib/km/hello")
        self.v.run("mod ls")
        self.v.run("mod unload 0")
        self.mark("f mod load/unload", out)


if __name__ == "__main__":
    unittest.main()
