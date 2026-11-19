"""The p-code VM (src/pvm/pvm.s, docs/design/pvm.md) run under py65 (tools/asim.py): bytecode
programs written with src/pvm/pvm.inc are linked with the VM through src/pvm/pvm.cfg, made into
CX files with tools/cx.py like any program, and run. Needs ca65, ld65 and py65 (the container
image has them; the host test run skips without them)."""
import os
import shutil
import subprocess
import tempfile
import unittest

from asim import MPU, run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAVE_TOOLS = bool(shutil.which("ca65") and shutil.which("ld65") and MPU)

# native entry: init the VM with a 1 KB frame stack, call main (bytecode), exit 0
PRELUDE = """
.include "breadbin.inc"
.include "pvm.inc"
.export pvm_main
.macpack generic
SYSN_WRITE = (SYS_WRITE - SYS_BASE) / 3
SYSN_EXIT  = (SYS_EXIT - SYS_BASE) / 3
.segment "BSS"
fstk:   .res 1024
fstk_end:
buf:    .res 64
.segment "CODE"
pvm_main:
        lda #<fstk_end
        ldy #>fstk_end
        jsr pvm_init
        jsr f_main
        stx $39             ; the eval stack index after main returned
        tsx
        stx $3a             ; the 6502 stack pointer
        lda #0
        jmp SYS_EXIT
; write(1, buf, n): n on the eval stack
.macro WRITE_BUF
        P_W PO_SAW, r1
        P_W PO_LA, buf
        P_W PO_SAW, r0
        P_CN 1
        P_SYS SYSN_WRITE
        P_OP PO_DROP
.endmacro
"""


def build_run(body, d):
    src = os.path.join(d, "t.s")
    with open(src, "w") as f:
        f.write(PRELUDE + body)
    inc = ["-I", os.path.join(ROOT, "include"), "-I", os.path.join(ROOT, "src", "pvm")]

    def sh(*a):
        p = subprocess.run(a, capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError(f"{a[0]} failed:\n{p.stdout}{p.stderr}")
    sh("ca65", *inc, "-o", os.path.join(d, "t.o"), src)
    sh("ca65", "-o", os.path.join(d, "pvm.o"), os.path.join(ROOT, "src", "pvm", "pvm.s"))
    cfg = os.path.join(ROOT, "src", "pvm", "pvm.cfg")
    objs = [os.path.join(d, "pvm.o"), os.path.join(d, "t.o")]
    sh("ld65", "-C", cfg, "-S", "0", "-Ln", os.path.join(d, "t.lbl"), "-o", os.path.join(d, "t.0"), *objs)
    sh("ld65", "-C", cfg, "-S", "256", "-o", os.path.join(d, "t.1"), *objs)
    sh("python3", os.path.join(ROOT, "tools", "cx.py"), os.path.join(d, "t.0"), os.path.join(d, "t.1"),
       os.path.join(d, "t.lbl"), os.path.join(d, "t.cx"))
    return run("t", [], path=os.path.join(d, "t.cx"))


def words(b):
    return [int.from_bytes(b[i:i + 2], "little", signed=True) for i in range(0, len(b), 2)]


@unittest.skipUnless(HAVE_TOOLS, "needs ca65, ld65 and py65")
class PVM(unittest.TestCase):
    def go(self, body):
        with tempfile.TemporaryDirectory(prefix="pvm-") as d:
            r = build_run(body, d)
        self.assertEqual(r.exit, 0)
        # main returned to native code with the eval stack holding its one result and the
        # 6502 stack as the program got it, less the one JSR level the prelude is in
        self.assertEqual(r.mem[0x39], 10, "eval stack index after main")
        return r

    def test_loop(self):
        # sum = 0; for i = 1 to 100: sum += i
        r = self.go("""
f_main: P_FUNC
        P_ENTER 4, 0
        P_CN 0
        P_B PO_SLW, 0
        P_B PO_CB, 100
        P_CN 1
@top:   P_B PO_DLW, 2
        P_B PO_LLW, 0
        P_B PO_ADDLW, 2
        P_B PO_SLW, 0
        P_BR PO_INCBRLE, @top
        P_OP PO_DROP2
        P_B PO_LLW, 0
        P_W PO_SAW, buf
        P_CN 2
        WRITE_BUF
        P_CN 0
        P_B PO_LEAVE, 4
""")
        self.assertEqual(words(r.out), [5050])

    def test_recursion_200_deep(self):
        # rec(n) = n ? rec(n - 1) + n : 0; 200 levels need 800 bytes of 6502 stack upstream. The
        # call comes first, so no caller value waits on the eval stack (11 deep) across it
        r = self.go("""
f_rec:  P_FUNC
        P_ENTER 2, 1
        P_B PO_LLW, 0
        P_BR PO_BRTRU, @r
        P_CN 0
        P_B PO_LEAVE, 2
@r:     P_B PO_LLW, 0
        P_OP PO_DECR
        P_W PO_CALL, f_rec
        P_B PO_ADDLW, 0
        P_B PO_LEAVE, 2
f_main: P_FUNC
        P_B PO_CB, 200
        P_W PO_CALL, f_rec
        P_W PO_SAW, buf
        P_CN 2
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
""")
        self.assertEqual(words(r.out), [20100])
        self.assertEqual(r.mem[0x3a], 0xFF, "6502 stack balanced")

    def test_arith(self):
        ops = [("-7", "3", "PO_MUL", -21), ("-7", "2", "PO_DIV", -3), ("-7", "2", "PO_MOD", -1),
               ("1000", "7", "PO_DIV", 142), ("1", "12", "PO_SHL", 4096), ("-32768", "4", "PO_SHR", -2048),
               ("-1", "1", "PO_ISLT", -1), ("-1", "1", "PO_ISGT", 0), ("30000", "-30000", "PO_ISGT", -1),
               ("-30000", "30000", "PO_ISGE", 0), ("5", "3", "PO_SUB", 2), ("$F0F0", "$0FF0", "PO_XOR", -256)]
        body = "f_main: P_FUNC\n"
        for i, (a, b, op, _) in enumerate(ops):
            body += f"        P_W PO_CW, {a}\n        P_W PO_CW, {b}\n        P_OP {op}\n        P_W PO_SAW, buf+{2 * i}\n"
        body += f"        P_CN {2 * len(ops)}\n" if 2 * len(ops) < 16 else f"        P_B PO_CB, {2 * len(ops)}\n"
        body += "        WRITE_BUF\n        P_CN 0\n        P_OP PO_RET\n"
        r = self.go(body)
        self.assertEqual(words(r.out), [w for *_, w in ops])

    def test_syscall_keeps_the_eval_stack(self):
        # a value under the call survives (asim trashes $08-$1F on every syscall); a bad fd gives
        # -1 and the errno; a string constant is written
        r = self.go("""
f_main: P_FUNC
        P_W PO_CW, 1234
        P_CS "hi"
        P_OP PO_DUP
        P_OP PO_LB
        P_W PO_SAW, r1
        P_B PO_ADDI, 1
        P_W PO_SAW, r0
        P_CN 1
        P_SYS SYSN_WRITE
        P_OP PO_DROP
        P_CN 7
        P_SYS SYSN_WRITE
        P_W PO_SAW, buf
        P_W PO_LAB, pvm_errno
        P_W PO_SAW, buf+2
        P_W PO_SAW, buf+4
        P_CN 6
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
""")
        self.assertEqual(r.out[:2], b"hi")
        self.assertEqual(words(r.out[2:]), [-1, 9, 1234])

    def test_native_call_and_select(self):
        # CALL to a native routine (doubles TOS); SEL picks a case
        r = self.go("""
f_main: P_FUNC
        P_CN 3
        P_W PO_CALL, n_double
        P_W PO_SAW, buf
        P_CN 2
        P_BR PO_SEL, @tbl
@c1:    P_CN 11
        P_BR PO_BRNCH, @end
@c2:    P_CN 12
        P_BR PO_BRNCH, @end
@c3:    P_CN 13
        P_BR PO_BRNCH, @end
@tbl:   .byte 2
        .word 1
        .word .loword(@c1 - *)
        .word 2
        .word .loword(@c2 - *)
@dflt:  P_BR PO_BRNCH, @c3
@end:   P_W PO_SAW, buf+2
        P_CN 4
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
n_double:
        asl $15,x           ; ESTKL
        rol $0a,x           ; ESTKH
        rts
""")
        self.assertEqual(words(r.out), [6, 12])

    def test_recursion_with_pending_values(self):
        # return n + f(n - 1) as PLASMA's compiler emits it (LLW; DUP; DECR; CALL; ADD): n waits on
        # the eval stack across every level, so 120 levels need ENTER's spill to the frame stack (about 7 bytes a level)
        r = self.go("""
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
        P_B PO_CB, 120
        P_W PO_CALL, f_rec
        P_W PO_SAW, buf
        P_W PO_SAW, buf+2
        P_CN 4
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
""")
        self.assertEqual(words(r.out), [7260, 1000])
        self.assertEqual(r.mem[0x3a], 0xFF, "6502 stack balanced")

    def test_spill_with_zero_and_two_results(self):
        # PLASMA's #0 and #2 functions: four pending values force a spill at ENTER; LEAVE must put
        # them back under however many results there are (go() checks the depth afterwards)
        r = self.go("""
f_none: P_FUNC
        P_ENTER 2, 1
        P_B PO_LLW, 0
        P_W PO_SAW, buf+2
        P_B PO_LEAVE, 2
f_two:  P_FUNC
        P_ENTER 2, 1
        P_B PO_LLW, 0
        P_B PO_LLW, 0
        P_OP PO_INCR
        P_B PO_LEAVE, 2
f_main: P_FUNC
        P_CN 1
        P_CN 2
        P_CN 3
        P_CN 4
        P_CN 5
        P_W PO_CALL, f_none
        P_OP PO_ADD
        P_OP PO_ADD
        P_OP PO_ADD
        P_W PO_SAW, buf
        P_CN 1
        P_CN 2
        P_CN 3
        P_CN 4
        P_CN 7
        P_W PO_CALL, f_two
        P_W PO_SAW, buf+6
        P_W PO_SAW, buf+4
        P_OP PO_ADD
        P_OP PO_ADD
        P_OP PO_ADD
        P_W PO_SAW, buf+8
        P_B PO_CB, 10
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
""")
        self.assertEqual(words(r.out), [10, 5, 7, 8, 10])

    def test_overflow_traps(self):
        # pending values across frameless calls (no ENTER, so no spill) wrap the eval stack: the
        # next call traps with ENOMEM instead of running on
        with tempfile.TemporaryDirectory(prefix="pvm-") as d:
            r = build_run("""
f_main: P_FUNC
@lp:    P_CN 1
        P_W PO_CALL, @lp - 3
        P_OP PO_RET
""", d)
        self.assertEqual(r.exit, 12)

    def test_natv_returns_from_the_function(self):
        # NATV in a function reached by CALL: the native tail's RTS returns to the caller, as
        # upstream (where the call itself was a JSR)
        r = self.go("""
f_nat:  P_FUNC
        P_OP PO_NATV
        dex
        lda #42
        sta $15,x
        lda #0
        sta $0a,x
        rts
f_main: P_FUNC
        P_W PO_CALL, f_nat
        P_B PO_ADDI, 1
        P_W PO_SAW, buf
        P_CN 2
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
""")
        self.assertEqual(words(r.out), [43])

    def test_plasma_compiler_output(self):
        # the docs/design/pvm.md benchmark as upstream's compiler emits it (src/pvm/test/bench.s):
        # the port runs real PLASMA bytecode, not just what these tests hand-write
        with open(os.path.join(ROOT, "src", "pvm", "test", "bench.s")) as f:
            bench = f.read()
        r = self.go(bench + """
f_main: P_FUNC
        P_W PO_CALL, _C003
        P_W PO_SAW, buf
        P_CN 2
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
""")
        self.assertEqual(words(r.out), [469])   # 46 primes below 200 + 288 (the gcds) + 135 (the sum)


if __name__ == "__main__":
    unittest.main()
