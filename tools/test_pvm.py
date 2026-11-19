"""The p-code VM (src/pvm/pvm.s, docs/design/pvm.md) run under py65 (tools/asim.py): the VM is
built as the shared library /lib/pvm (CX format 3) and bytecode programs written with
src/pvm/pvm.inc are linked against it (format 2) by tools/pvmlink.py, then run. Needs ca65, ld65 and py65 (the container
image has them; the host test run skips without them)."""
import os
import shutil
import subprocess
import tempfile
import unittest

import pvmlink
from asim import MPU, run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAVE_TOOLS = bool(shutil.which("ca65") and shutil.which("ld65") and MPU)

# native entry: init the VM with a 1 KB frame stack, call main (bytecode), exit 0. Two canary
# bytes sit below the frame stack; $3C/$3D point at them
PRELUDE = """
.include "breadbin.inc"
.include "pvm.inc"
.macpack generic
SYSN_WRITE = (SYS_WRITE - SYS_BASE) / 3
SYSN_EXIT  = (SYS_EXIT - SYS_BASE) / 3
.segment "BSS"
fguard: .res 2
fstk:   .res 1024
fstk_end:
buf:    .res 64
.segment "CODE"
pvm_main:
        lda #$A5
        sta fguard
        sta fguard+1
        lda #<fguard
        sta $3c
        lda #>fguard
        sta $3d
        lda #<fstk
        sta r0
        lda #>fstk
        sta r0+1
        lda #<fstk_end
        ldy #>fstk_end
        jsr pvm_init
        jsr f_main
        stx $3a             ; the eval stack index after main returned
        tsx
        stx $3b             ; the 6502 stack pointer
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


# pdec(n): write n (0-32767) in decimal and a newline to fd 1, in bytecode; returns write's result
PDEC = """
f_pdec: P_FUNC
        P_ENTER 4, 1            ; 0: n, 2: i, the next digit's index in buf
        P_B PO_CB, 10
        P_W PO_SAB, buf+8
        P_CN 8
        P_B PO_SLW, 2
@lp:    P_B PO_LLW, 0
        P_CN 10
        P_OP PO_MOD
        P_B PO_ADDI, '0'
        P_B PO_LLW, 2
        P_OP PO_DECR
        P_B PO_DLW, 2
        P_W PO_LA, buf
        P_OP PO_ADD
        P_OP PO_SB
        P_B PO_LLW, 0
        P_CN 10
        P_OP PO_DIV
        P_B PO_DLW, 0
        P_BR PO_BRTRU, @lp
        P_CN 9
        P_B PO_LLW, 2
        P_OP PO_SUB
        P_W PO_SAW, r1
        P_W PO_LA, buf
        P_B PO_LLW, 2
        P_OP PO_ADD
        P_W PO_SAW, r0
        P_CN 1
        P_SYS SYSN_WRITE
        P_B PO_LEAVE, 4
"""


_LIB = []


def lib_dir():
    """A directory holding /lib/pvm and its stub, built once per test run."""
    if not _LIB:
        _LIB.append(tempfile.mkdtemp(prefix="pvmlib-"))
        pvmlink.build_lib(_LIB[0])
    return _LIB[0]


def build_cx(body, d):
    """The format 2 CX file for PRELUDE + body, built in directory d (the library: lib_dir())."""
    src = os.path.join(d, "t.s")
    with open(src, "w") as f:
        f.write(PRELUDE + body)
    pvmlink.sh("ca65", "-I", os.path.join(ROOT, "include"), "-I", os.path.join(ROOT, "src", "pvm"),
               "-o", os.path.join(d, "t.o"), src)
    return pvmlink.link_prog(os.path.join(d, "t.cx"), lib_dir(), [os.path.join(d, "t.o")])


def build_run(body, d):
    return run("t", [], path=build_cx(body, d), libs={pvmlink.LIBPATH: os.path.join(lib_dir(), "pvm")})


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
        self.assertEqual(r.mem[0x3A], 10, "eval stack index after main")
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
        self.assertEqual(r.mem[0x3B], 0xFF, "6502 stack balanced")

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

    def test_div_and_mod_by_zero_are_zero(self):
        # x / 0 and x % 0 are 0 whatever the sign of x (the divide-by-zero rule cc.py and cc_pcode.py follow)
        ops = [("5", "0", "PO_DIV", 0), ("-5", "0", "PO_DIV", 0), ("0", "0", "PO_DIV", 0),
               ("5", "0", "PO_MOD", 0), ("-5", "0", "PO_MOD", 0)]
        body = "f_main: P_FUNC\n"
        for i, (a, b, op, _) in enumerate(ops):
            body += f"        P_W PO_CW, {a}\n        P_W PO_CW, {b}\n        P_OP {op}\n        P_W PO_SAW, buf+{2 * i}\n"
        body += f"        P_B PO_CB, {2 * len(ops)}\n"
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
        self.assertEqual(r.mem[0x3B], 0xFF, "6502 stack balanced")

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

    def test_frame_stack_overflow_traps(self):
        # recursion past the 1 KB frame stack exits with ENOMEM and writes nothing below it: once
        # through the spill path (a pending value per level) and once through the plain ENTER
        for depth, pending in ((250, False), (200, True)):
            with self.subTest(depth=depth, pending=pending), tempfile.TemporaryDirectory(prefix="pvm-") as d:
                r = build_run("""
f_rec:  P_FUNC
        P_ENTER 2, 1
        P_B PO_LLW, 0
        P_BR PO_BRTRU, @r
        P_CN 0
        P_B PO_LEAVE, 2
@r:     P_B PO_LLW, 0
""" + ("        P_OP PO_DUP\n" if pending else "") + """        P_OP PO_DECR
        P_W PO_CALL, f_rec
""" + ("        P_OP PO_ADD\n" if pending else "        P_B PO_ADDLW, 0\n") + """        P_B PO_LEAVE, 2
f_main: P_FUNC
        P_CN 1
        P_CN 2
        P_CN 3
        P_CN 4
        P_W PO_CW, %d
        P_W PO_CALL, f_rec
        P_W PO_SAW, buf
        P_CN 2
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
""" % depth, d)
                self.assertEqual(r.exit, 12)
                g = r.mem[0x3C] | r.mem[0x3D] << 8
                self.assertEqual(r.mem[g:g + 2], [0xA5, 0xA5], "canary below the frame stack")

    def test_eval_stack_push_guard(self):
        # one expression 11 entries deep (the whole eval stack) runs; a 12th push exits with ENOMEM
        # at the push. Unguarded, the 12th wrapped and the adds came back in range with wrong values
        for depth, status in ((11, 0), (12, 12)):
            body = "f_main: P_FUNC\n" + "".join("        P_CN %d\n" % (i % 16) for i in range(1, depth + 1))
            body += "        P_OP PO_ADD\n" * (depth - 1) + """
        P_W PO_SAW, buf
        P_CN 2
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
"""
            with self.subTest(depth=depth), tempfile.TemporaryDirectory(prefix="pvm-") as d:
                r = build_run(body, d)
                self.assertEqual(r.exit, status)
                if status == 0:
                    self.assertEqual(words(r.out), [66])
        # the 12th push through every guarded op, in a framed function so the local loads work.
        twelfth = ["P_OP PO_DUP", "P_OP PO_MINUS1", "P_CN 3", "P_B PO_CB, 3", "P_B PO_CFFB, 3", "P_W PO_CW, 3",
                   'P_CS "x"', "P_W PO_LA, buf", "P_B PO_LLA, 0", "P_B PO_LLB, 0", "P_B PO_LLW, 0",
                   "P_W PO_LAB, buf", "P_W PO_LAW, buf"]
        for op in twelfth:
            body = "f_main: P_FUNC\n        P_ENTER 2, 0\n" + "        P_CN 1\n" * 11
            # the DROP brings a wrapped index back in range, so LEAVE's check cannot stand in
            body += "        %s\n        P_OP PO_DROP\n        P_B PO_LEAVE, 2\n" % op
            with self.subTest(op=op), tempfile.TemporaryDirectory(prefix="pvm-") as d:
                self.assertEqual(build_run(body, d).exit, 12)
        # LEAVE after ENTER spilled 8 pending entries: 3 results fit above them, a 4th would be a
        # 12th entry, and the shift used to write it into page 1 ($0109/$0114) before any trap
        for nres, status in ((3, 0), (4, 12)):
            body = "f_res: P_FUNC\n        P_ENTER 2, 0\n" + "".join(
                "        P_W PO_CW, $%02X%02X\n" % (0x70 + i, 0x70 + i) for i in range(nres))
            body += "        P_B PO_LEAVE, 2\nf_main: P_FUNC\n" + "        P_CN 1\n" * 8
            body += "        P_W PO_CALL, f_res\n" + "        P_OP PO_DROP\n" * (8 + nres)
            body += "        P_CN 0\n        P_OP PO_RET\n"
            with self.subTest(results=nres), tempfile.TemporaryDirectory(prefix="pvm-") as d:
                r = build_run(body, d)
                self.assertEqual(r.exit, status)
                self.assertEqual([a for a in range(0x100, 0x200) if 0x70 <= r.mem[a] < 0x74], [])
        # a callee that pops past empty traps at LEAVE whether or not ENTER spilled: with k
        # entries spilled, X - k used to land back in range and the caller lost one silently
        for k in (0, 4, 8, 11):
            body = "f_res: P_FUNC\n        P_ENTER 2, 0\n        P_OP PO_DROP\n        P_B PO_LEAVE, 2\n"
            body += "f_main: P_FUNC\n" + "        P_CN 1\n" * k + "        P_W PO_CALL, f_res\n"
            body += "        P_OP PO_DROP\n" * k + "        P_CN 0\n        P_OP PO_RET\n"
            with self.subTest(popped_under=k), tempfile.TemporaryDirectory(prefix="pvm-") as d:
                self.assertEqual(build_run(body, d).exit, 12)

    def test_frame_stack_boundary(self):
        # plain recursion, no pending values, so only the frame-stack check can trap: 2 bytes for
        # the native-entry marker and 5 a level (return IP, spill count, 2-byte frame). 204 levels
        # (rec(203) down to rec(0)) take 1,022 of the 1,024 bytes and run; one more level traps
        body = """
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
        P_W PO_CW, %d
        P_W PO_CALL, f_rec
        P_W PO_SAW, buf
        P_CN 2
        WRITE_BUF
        P_CN 0
        P_OP PO_RET
"""
        for depth, status in ((203, 0), (204, 12)):
            with self.subTest(depth=depth), tempfile.TemporaryDirectory(prefix="pvm-") as d:
                r = build_run(body % depth, d)
                self.assertEqual(r.exit, status)
                if status == 0:
                    self.assertEqual(words(r.out), [depth * (depth + 1) // 2])
                g = r.mem[0x3C] | r.mem[0x3D] << 8
                self.assertEqual(r.mem[g:g + 2], [0xA5, 0xA5], "canary below the frame stack")

    def test_pdec(self):
        # the decimal printer tests/test_pvm_machine.py uses on the C64
        r = self.go(PDEC + """
f_main: P_FUNC
        P_CN 0
        P_W PO_CALL, f_pdec
        P_OP PO_DROP
        P_W PO_CW, 469
        P_W PO_CALL, f_pdec
        P_OP PO_DROP
        P_W PO_CW, 32767
        P_W PO_CALL, f_pdec
        P_OP PO_RET
""")
        self.assertEqual(r.out, b"0\n469\n32767\n")

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
