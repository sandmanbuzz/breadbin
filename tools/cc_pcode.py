"""L2: cc.py's C subset compiled to p-code for the Breadbin VM (src/pvm/pvm.s, docs/design/pvm.md).

    python3 tools/cc.py --pcode prog.c > prog.s
    ca65 -I include -I src/pvm -o prog.o prog.s
    python3 tools/pvmlink.py prog prog.cx LIBDIR prog.o      (CX format 2, importing /lib/pvm)

The parser and the type rules are cc.py's (one language, two back ends). What differs from the
native back end:

- **Real recursion.** Parameters and locals live in the function's frame (`ENTER`/`LEAVE`), so a
  function may call itself; the frame stack (1 KB, in the program's BSS) bounds the depth, and
  running out exits with status 12 (ENOMEM) instead of corrupting memory.
- **The eval stack** (11 entries; 8 guaranteed free at a framed function's entry) replaces
  `acc` and `cc_stk`. Every function is framed, so the VM spills a caller's pending values at
  each call. Within one function the compiler keeps an expression to 8 entries: when the right
  side of a binary operator (or the arguments of a call) would not fit above what is pending,
  the pending value goes to a frame temporary instead (`need()` below). Any expression compiles;
  a call takes at most 8 arguments (refused at compile time).
- **`main`'s return value is the exit status** (its low byte); the native back end exits 0.
- **Evaluation order of a store through a pointer:** the value is computed before the address
  (`SB`/`SW` take the value under the address; the VM has no swap). C leaves the order of the
  two unspecified; the native back end computes the address first.
- No `as` limits: symbols are not capped at 14 characters, and a `puts` string may be longer
  than 254 bytes. A function's frame (parameters, locals, temporaries) is at most 255 bytes.
- **Locals are not static:** an uninitialised local holds whatever the frame stack held, not
  its value from the previous call (the native back end's locals are statics).

L3a (docs/design/basic.md section 4) adds, to this back end only:

- `%` (the VM's MOD: the dividend's sign, as C's; x % 0 is 0), `&&` `||` `!` (short-circuit; as
  values, 0 or 1), `break` and `continue` (`continue` in a `for` runs the step).
- **Syscall builtins:** `read(fd, buf, n)` and `write(fd, buf, n)` give the count, `open(path,
  flags)` the fd, `close(fd)` 0, each -1 on error; `exit(status)`. One `SYS` each; `r0`/`r1` are
  stored after every argument is evaluated, since a call inside an argument may make syscalls
  of its own. `open` evaluates `flags` before `path` (C leaves the order unspecified). `buf` may
  point to int or char. These names, and `puts`, cannot name a function.
- **`extern int name(params);`** declares a native routine linked in beside the program (another
  ca65 object; `.export name` there). `CALL` reaches it with the arguments on the eval stack, the
  first deepest and the last at TOS (X is TOS's index, `P_ESTKL`/`P_ESTKH` in pvm.inc); it pops
  them, pushes one result, and returns with RTS. It may not make syscalls (they clobber the eval
  stack's zero page; only `SYS` saves it) and may not use more entries than its arguments took
  (one, with none). Its name is the ca65 symbol, so the compiler's own prefixes are refused.
  A program with an extern exports its globals as `g_NAME` (an int is 2 bytes, low first; an
  array is its elements), so such a routine can use them directly rather than through
  arguments.

A source comment `/* fstack N */` at the start of a line sets the program's frame stack to N bytes (default 1024, 128 to 8192); a
program that knows its depth gives back the rest (bas takes 768).

A source line `/* xops */` makes the program keep the VM's XOP vector table (pvm.s) under its
frame stack, copied at start from `xtab`, which the program's natives export.

A compare that decides a branch is the VM's compare and a `BRTRU`/`BRFLS`, with no `NEG`.

Signed semantics are the native back end's: `int` is signed, so `<` `>` `<=` `>=` compare signed
and `/` truncates toward zero. They are the VM's own ops (ISLT, ISGT, ISLE, ISGE, DIV), which give
-1 for true: a NEG makes it C's 1. x / 0 is 0 (the VM's DIV, changed to give 0 for this; the
native back end does the same). The only native helper left is `cc_copy`, and only a program
that initialises a local char array from a string emits it.
"""
import re

import cc
from cc import CompileError, Var

ESLIMIT = 8                          # eval stack entries a framed function may use (pvm.md, section 4)
FRAME_MAX = 255                      # ENTER/LEAVE take the frame size in a byte
FSTACK_MIN, FSTACK_MAX = 128, 8192
FSTACK = 1024                        # bytes of frame stack (return IPs, spills, frames)
POOL = 39680                         # the user pool ($0800-$A2FF): static bytes past it can never load
STRAIGHT = 240                       # most bytecode bytes past the IP base before a renormalising branch

SIZE = {"P_CN": 1, "P_OP": 1, "P_B": 2, "P_W": 3, "P_BR": 3, "P_ENTER": 3, "P_SYS": 2}

# A program with `/* xops */` keeps the vector table of the VM's XOP opcodes (pvm.s) in the 56
# bytes under the bottom of its frame stack, copied at start from `xtab` (28 words, which the
# program's natives define and export).
XOPS = {False: {"xres": "", "xinit": "  ", "xoff": ""},
        True: {"xres": " + 56", "xoff": " + 56", "xinit": """
        .import xtab
        ldy #55
@x:     lda xtab,y
        sta cc_fstk,y
        dey
        bpl @x
        """}}
PRELUDE = """\
; compiled by tools/cc.py --pcode: p-code for /lib/pvm (CX format 2)
.include "breadbin.inc"
.include "pvm.inc"
SYSN_WRITE = (SYS_WRITE - SYS_BASE) / 3
SYSN_READ = (SYS_READ - SYS_BASE) / 3
SYSN_OPEN = (SYS_OPEN - SYS_BASE) / 3
SYSN_CLOSE = (SYS_CLOSE - SYS_BASE) / 3
SYSN_EXIT = (SYS_EXIT - SYS_BASE) / 3
SYSN_ISATTY = (SYS_ISATTY - SYS_BASE) / 3
.segment "BSS"
cc_fstk: .res {fstack}{xres}
cc_fend:
.segment "CODE"
; native entry: the VM with its frame stack, then main; main's value is the exit status
start:{xinit}  lda #<(cc_fstk{xoff})
        sta r0
        lda #>(cc_fstk{xoff})
        sta r0+1
        lda #<cc_fend
        ldy #>cc_fend
        jsr pvm_init
        jsr fn_main
        lda P_ESTKL,x
        jmp SYS_EXIT
"""

# native helpers, called with CALL: X is the eval stack index (TOS at X, the one under it at X+1)
HELPERS = {
    # copy TOS bytes (1-255) from NOS to the address under it; pops all three
    "cc_copy": """\
cc_copy:
        lda P_ESTKL+2,x
        sta $3A
        lda P_ESTKH+2,x
        sta $3B
        lda P_ESTKL+1,x
        sta $3C
        lda P_ESTKH+1,x
        sta $3D
        ldy P_ESTKL,x
@lp:    dey
        lda ($3C),y
        sta ($3A),y
        tya
        bne @lp
        inx
        inx
        inx
        rts
""",
    # after SYS: the result of read and write is the count the kernel left in r1 (-1 on error)
    "cc_r1": """\
cc_r1:  lda pvm_errno
        bne @e
        lda r1
        sta P_ESTKL,x
        lda r1+1
        sta P_ESTKH,x
@e:     rts
""",
    # after SYS: open's fd is A alone; X is whatever the kernel left (-1 on error)
    "cc_lo": """\
cc_lo:  lda pvm_errno
        bne @e
        sta P_ESTKH,x
@e:     rts
""",
    # after SYS: close gives 0 (-1 on error)
    "cc_ok": """\
cc_ok:  lda pvm_errno
        bne @e
        sta P_ESTKL,x
        sta P_ESTKH,x
@e:     rts
""",
    # after SYS: isatty is 1 when the kernel said yes (carry clear), else 0, as C's
    "cc_tty": """\
cc_tty: lda #0
        sta P_ESTKH,x
        ldy pvm_errno
        bne :+
        lda #1
:       sta P_ESTKL,x
        rts
""",
}
# the syscall builtins: SYS number, the fixing helper, and the parameters (base, pointer)
SYSCALLS = {
    "read": ("SYSN_READ", "cc_r1", [("int", False), None, ("int", False)]),       # None: any pointer
    "write": ("SYSN_WRITE", "cc_r1", [("int", False), None, ("int", False)]),
    "open": ("SYSN_OPEN", "cc_lo", [("char", True), ("int", False)]),
    "close": ("SYSN_CLOSE", "cc_ok", [("int", False)]),
    "exit": ("SYSN_EXIT", None, [("int", False)]),
    "isatty": ("SYSN_ISATTY", "cc_tty", [("int", False)]),
}
assert set(SYSCALLS) == set(cc.SYSCALLS)
BITOPS = {"&": "PO_BAND", "|": "PO_IOR", "^": "PO_XOR", "<<": "PO_SHL", ">>": "PO_SHR"}
VMCMP = {"<": "PO_ISLT", ">": "PO_ISGT", "<=": "PO_ISLE", ">=": "PO_ISGE"}   # signed; true is -1


class Local(Var):
    """A parameter or local: its offset in the frame."""

    def __init__(self, off, base, ptr, arr):
        super().__init__(None, base, ptr, arr)
        self.off = off


class PGen(cc.Gen):
    def __init__(self, funcs, fstack=FSTACK, xops=False):
        super().__init__(funcs)
        self.fstack = fstack
        self.xops = xops
        self.helpers = set()
        self._need = {}
        self.loops = []                  # (break label, continue label), innermost last
        self.externs = [name for name, _, body, _ in funcs if body is None]

    # --- emission ---

    def claim(self, lbl, line):
        """ca65 is case-sensitive and has no length limit: only a clash is an error."""
        if lbl in self.names:
            raise CompileError(f"line {line}: {lbl} clashes with {self.names[lbl]}")
        self.names[lbl] = lbl

    def op(self, macro, *args):
        """One bytecode instruction. The VM addresses code as a base plus Y: straight-line code
        must not run Y past 255, so a branch to the next instruction (which sets Y to 0) goes in
        when it would. A call or a taken branch also sets it to 0; a conditional branch that is
        not taken leaves it below 128 (pvm.s NOBRNCH)."""
        size = SIZE[macro]
        if self.straight + size > STRAIGHT:
            lbl = self.new_label()
            self.ins(f"P_BR PO_BRNCH, {lbl}")
            self.lab(lbl)
            self.straight = 0
        self.ins(macro + (" " + ", ".join(str(a) for a in args) if args else ""))
        self.straight += size
        if macro == "P_BR":
            self.straight = 0 if args[0] == "PO_BRNCH" else min(self.straight, 130)
        elif macro == "P_W" and args[0] == "PO_CALL":
            self.straight = 0

    def const(self, v):
        v &= 0xFFFF
        if v < 16:
            self.op("P_CN", v)
        elif v < 256:
            self.op("P_B", "PO_CB", v)
        elif v == 0xFFFF:
            self.op("P_OP", "PO_MINUS1")
        else:
            self.op("P_W", "PO_CW", v)

    def helper(self, name):
        self.use(name)
        self.op("P_W", "PO_CALL", name)

    def use(self, name):
        self.helpers.add(name)

    def push(self, n=1):
        self.depth += n
        if self.depth > ESLIMIT:
            raise CompileError(f"internal: eval stack depth {self.depth} in {self.fn}")

    def pop(self, n=1):
        self.depth -= n
        assert self.depth >= 0

    # --- program ---

    def program(self, funcs, globs):
        if "main" not in self.funcs:
            raise CompileError("no function main")
        if self.params["main"]:
            raise CompileError(f"line {self.funcs['main']}: main takes no parameters (start passes none)")
        for d in globs:
            self.global_var(d)
        for name, params, body, line in funcs:
            if name in cc.BUILTINS or name == "puts":
                raise CompileError(f"line {line}: {name} is a builtin; a function cannot have its name")
            if body is None:
                if name == "main":
                    raise CompileError(f"line {line}: main cannot be extern (start calls the compiled main)")
                if (name in ("start", "r0", "r1", "r2") or name.lower() in ("a", "x", "y", "z", "s")
                        or re.fullmatch(r"L\d+", name)
                        or name.startswith(("cc_", "fn_", "pvm_", "FS_", "SYSN_", "P_", "PO_", "SYS_"))):
                    raise CompileError(f"line {line}: extern {name}: the name is reserved for the compiler")
                self.claim(name, line)
                self.out.append(f".import {name}")
            else:
                self.function(name, params, body, line)
        for name, line in self.calls:
            if name not in self.funcs:
                raise CompileError(f"line {line}: undefined function {name}")
        total = sum(v.nbytes() for v in self.globals.values())
        if total > POOL:   # cc.STATIC_MAX is the native back end's (the on-system `as`); ca65 has none
            raise CompileError(f"the program's static variables take {total} bytes; the limit is {POOL}")
        helpers = "".join(HELPERS[h] for h in HELPERS if h in self.helpers)
        if self.externs:    # the natives may share the globals, by their labels
            helpers += "".join(f".export {v.label}\n" for v in self.globals.values())
        return (PRELUDE.format(fstack=self.fstack, **XOPS[self.xops]) + "\n".join(self.out) + "\n" + helpers
                + '.segment "DATA"\n' + self.strings_text() + "\n".join(self.gdata) + "\n"
                + '.segment "BSS"\n' + "\n".join(self.gres) + "\n" + '.segment "CODE"\n')

    def function(self, name, params, body, line):
        self.fn, self.vars = name, {}
        self.frame, self.temps, self.depth, self.straight = 0, [], 0, 0
        lbl = "fn_" + name
        self.claim(lbl, line)
        self.lab(lbl)
        self.ins("P_FUNC")
        self.op("P_ENTER", f"FS_{name}", len(params))
        for base, ptr, pname, pline in params:
            v = self.declare(pname, base, ptr, None, pline)
            if v.nbytes() == 1:
                self.frame += 1             # ENTER stores two bytes per parameter: a char reads the low one
        for s in body:
            self.stmt(s)
        self.const(0)
        self.op("P_B", "PO_LEAVE", f"FS_{name}")
        if self.frame > FRAME_MAX:
            raise CompileError(f"line {line}: {name}'s frame (parameters, locals and temporaries) takes "
                               f"{self.frame} bytes; the limit is {FRAME_MAX}")
        self.out.append(f"FS_{name} = {self.frame}")

    def declare(self, name, base, ptr, arr, line):
        if name in self.vars:
            raise CompileError(f"line {line}: {name} is already declared in {self.fn}")
        v = Local(self.frame, base, ptr, arr)
        self.frame += v.nbytes()
        self.vars[name] = v
        return v

    def temp(self):
        if self.temps:
            return self.temps.pop()
        self.frame += 2
        return self.frame - 2

    # --- depth ---

    def need(self, e):
        """Eval stack entries e needs above what is pending, when the compiler may spill to
        frame temporaries: what is left over the operands' own needs is the two operands of the
        operator, or the arguments of a call (evaluated into temporaries when they do not fit)."""
        key = id(e)
        if key not in self._need:
            kind = e[0]
            if kind == "bin" and e[1] in ("&&", "||"):
                n = max(self.need(e[2]), self.need(e[3]))     # the left value is gone before the right
            elif kind == "bin":
                n = max(self.need(e[2]), self.need(e[3]), 2)
            elif kind == "index":
                n = max(self.need(e[1]), self.need(e[2]), 2)
            elif kind in ("neg", "deref", "not", "comp"):
                n = self.need(e[1])
            elif kind == "addr":
                n = 1 if e[1][0] == "var" else self.need(e[1][1] if e[1][0] == "deref" else e[1])
            elif kind == "call" and e[1] != "puts":
                n = max([len(e[2]), 1] + [self.need(a) for a in e[2]])
            else:
                n = 1
            self._need[key] = n
        return self._need[key]

    def pair(self, first, second, need2):
        """Evaluate first then second, leaving both on the stack (second on top). When second
        would not fit above first, first waits in a frame temporary."""
        t1 = first()
        if self.depth + need2 <= ESLIMIT:
            return t1, second()
        a = self.temp()
        self.op("P_B", "PO_SLW", a)
        self.pop()
        t2 = second()
        b = self.temp()
        self.op("P_B", "PO_SLW", b)
        self.op("P_B", "PO_LLW", a)
        self.op("P_B", "PO_LLW", b)
        self.push()
        self.temps += [b, a]
        return t1, t2

    # --- statements ---

    def stmt(self, s):
        kind = s[0]
        if kind == "decl":
            _, base, ptr, name, arr, init, line = s
            if arr == "infer":
                arr = len(init[1]) + 1
            if arr is not None and init is not None:
                if base != "char" or ptr:
                    raise CompileError(f"line {line}: a string initialises a char array")
                if len(init[1]) + 1 > arr:
                    raise CompileError(f"line {line}: the string does not fit in {name}")
                if arr > 255:
                    raise CompileError(f"line {line}: a local char array takes a string of at most 254 bytes")
                v = self.declare(name, base, ptr, arr, line)
                # copied in each time the declaration runs, from a copy padded to the array's size
                src = self.add_string(init[1] + bytes(arr - 1 - len(init[1])))
                self.op("P_B", "PO_LLA", v.off)
                self.op("P_W", "PO_LA", src)
                self.const(arr)
                self.push(3)
                self.helper("cc_copy")
                self.pop(3)
                return
            v = self.declare(name, base, ptr, arr, line)
            if init is not None:
                self.check((v.base, v.ptr), self.expr(init), init, line, "initialise")
                self.store_var(v)
        elif kind == "assign":
            self.assign(s[1], s[2], s[3])
        elif kind == "expr":
            e = s[1]
            if e[0] == "call" and e[1] == "puts":
                self.puts(e[2], e[3], value=False)
            else:
                self.expr(e)
                self.op("P_OP", "PO_DROP")
                self.pop()
        elif kind == "return":
            if s[1] is None:
                self.const(0)
            else:
                self.check(("int", False), self.expr(s[1]), s[1], s[2], "return")
                self.pop()
            self.op("P_B", "PO_LEAVE", f"FS_{self.fn}")
        elif kind == "if":
            _, cond, then, other, _line = s
            else_l, end_l = self.new_label(), self.new_label()
            self.cond(cond, else_l)
            self.stmt(then)
            if other is not None:
                self.op("P_BR", "PO_BRNCH", end_l)
            self.lab(else_l)
            if other is not None:
                self.stmt(other)
            self.lab(end_l)
        elif kind in ("while", "for"):
            # the test at the bottom: one branch an iteration, not two; `continue` goes to the
            # step (a for's) or the test
            cond, body = s[1], s[2]
            step = s[3] if kind == "for" else None
            top_l, test_l, end_l = self.new_label(), self.new_label(), self.new_label()
            forever = cond[0] == "num" and cond[1] != 0
            cont_l = self.new_label() if step else (top_l if forever else test_l)
            if not forever:
                self.op("P_BR", "PO_BRNCH", test_l)
            self.lab(top_l)
            self.loops.append((end_l, cont_l))
            self.stmt(body)
            self.loops.pop()
            if step:
                self.lab(cont_l)
                self.stmt(step)
            if forever:
                self.op("P_BR", "PO_BRNCH", top_l)
            else:
                self.lab(test_l)
                self.cond(cond, top_l, when=True)
            self.lab(end_l)
        elif kind in ("break", "continue"):
            if not self.loops:
                raise CompileError(f"line {s[1]}: {kind} outside a loop")
            self.op("P_BR", "PO_BRNCH", self.loops[-1][kind == "continue"])
        elif kind == "block":
            for x in s[1]:
                self.stmt(x)

    def cond(self, e, lbl, when=False):
        """Branch to lbl when e's truth is `when`. `!`, `&&` and `||` become branches; a
        comparison's -1 needs no NEG here."""
        if e[0] == "not":
            self.cond(e[1], lbl, not when)
            return
        if e[0] == "bin" and e[1] in ("&&", "||"):
            if (e[1] == "||") == when:          # either side decides alone
                self.cond(e[2], lbl, when)
                self.cond(e[3], lbl, when)
            else:                               # the left side can only rule the branch out
                skip = self.new_label()
                self.cond(e[2], skip, not when)
                self.cond(e[3], lbl, when)
                self.lab(skip)
            return
        if e[0] == "bin" and e[1] in ("==", "!="):
            self.operands(e)
            self.op("P_BR", "PO_BREQ" if (e[1] == "==") == when else "PO_BRNE", lbl)
            self.pop(2)
            return
        if e[0] == "bin" and e[1] in VMCMP:
            self.operands(e)
            self.op("P_OP", VMCMP[e[1]])
            self.pop()
        else:
            self.expr(e)
        self.op("P_BR", "PO_BRTRU" if when else "PO_BRFLS", lbl)
        self.pop()

    def store_var(self, v):
        char = v.base == "char" and not v.ptr
        if isinstance(v, Local):
            self.op("P_B", "PO_SLB" if char else "PO_SLW", v.off)
        else:
            self.op("P_W", "PO_SAB" if char else "PO_SAW", v.label)
        self.pop()

    def assign(self, lhs, rhs, line):
        if lhs[0] == "var":
            v = self.var(lhs[1], lhs[2])
            if v.arr is not None:
                raise CompileError(f"line {line}: cannot assign to the array {lhs[1]}")
            self.check((v.base, v.ptr), self.expr(rhs), rhs, line, "assign")
            self.store_var(v)
            return
        if lhs[0] == "deref":
            def address():
                t = self.expr(lhs[1])
                if not t[1]:
                    raise CompileError(f"line {line}: * needs a pointer")
                return t
            need = self.need(lhs[1])
        elif lhs[0] == "index":
            address, need = (lambda: self.index_addr(lhs)), self.need(lhs)
        else:
            raise CompileError(f"line {line}: cannot assign to this")
        tv, (base, _) = self.pair(lambda: self.expr(rhs), address, need)
        self.check((base, False), tv, rhs, line, "store")
        self.op("P_OP", "PO_SB" if base == "char" else "PO_SW")
        self.pop(2)

    # --- expressions: each pushes one entry and returns its type ---

    def index_addr(self, node):
        _, base_e, idx_e, line = node
        simple = self.simple(idx_e)
        if simple:
            t = self.expr(base_e)
        else:
            t, ti = self.pair(lambda: self.expr(base_e), lambda: self.expr(idx_e), self.need(idx_e))
        if not t[1]:
            raise CompileError(f"line {line}: a[i] needs a pointer or an array")
        if simple:
            self.add_simple(simple, t[0] == "int")
            return (t[0], True)
        if ti[1]:
            raise CompileError(f"line {line}: an index must be a number")
        self.op("P_OP", "PO_IDXW" if t[0] == "int" else "PO_ADD")
        self.pop()
        return (t[0], True)

    def simple(self, e):
        """A number operand an op can carry (ADDLW and friends): a scalar int or char variable,
        or a constant. None otherwise."""
        if e[0] == "num" and e[1] < 128:
            return ("I", e[1])
        if e[0] == "var":
            v = self.var(e[1], e[2])
            if v.arr is None and not v.ptr:
                char = v.base == "char"
                return ("L", v.off, char) if isinstance(v, Local) else ("A", v.label, char)
        return None

    def add_simple(self, x, scaled, neg=False):
        """TOS += x (twice x when scaled; TOS -= x when neg, constants only)."""
        if x[0] == "I":
            n = x[1] * (2 if scaled else 1)
            if n:
                self.op("P_B", "PO_SUBI" if neg else "PO_ADDI", n)
            return
        size = "B" if x[2] else "W"
        if x[0] == "L":
            self.op("P_B", f"PO_{'IDX' if scaled else 'ADD'}L{size}", x[1])
        else:
            self.op("P_W", f"PO_{'IDX' if scaled else 'ADD'}A{size}", x[1])

    def load_var(self, v):
        if v.arr is not None:
            if isinstance(v, Local):
                self.op("P_B", "PO_LLA", v.off)
            else:
                self.op("P_W", "PO_LA", v.label)
        else:
            char = v.base == "char" and not v.ptr
            if isinstance(v, Local):
                self.op("P_B", "PO_LLB" if char else "PO_LLW", v.off)
            else:
                self.op("P_W", "PO_LAB" if char else "PO_LAW", v.label)
        self.push()

    def expr(self, e):
        kind = e[0]
        if kind == "num":
            self.const(e[1])
            self.push()
            return ("int", False)
        if kind == "var":
            v = self.var(e[1], e[2])
            self.load_var(v)
            if v.arr is not None or v.ptr:
                return (v.base, True)
            return (v.base, False)
        if kind == "str":
            if 0 in e[1]:
                raise CompileError(f"line {e[2]}: a \\0 in a string would end it early; not in this slice")
            self.op("P_W", "PO_LA", self.add_string(e[1]))
            self.push()
            return ("char", True)
        if kind == "call":
            _, name, args, line = e
            if name == "puts":
                self.puts(args, line, value=True)
            elif name in SYSCALLS:
                self.syscall(name, args, line)
            elif name == "icall":
                self.icall(args, line)
            else:
                self.call(name, args, line)
            return ("int", False)
        if kind == "not":
            self.expr(e[1])
            self.op("P_OP", "PO_LNOT")
            self.op("P_OP", "PO_NEG")       # LNOT's true is -1
            return ("int", False)
        if kind in ("neg", "comp"):
            if self.expr(e[1])[1]:
                raise CompileError(f"line {e[2]}: {'-' if kind == 'neg' else '~'} of a pointer is not in this slice")
            self.op("P_OP", "PO_NEG" if kind == "neg" else "PO_COMP")
            return ("int", False)
        if kind == "deref":
            t = self.expr(e[1])
            if not t[1]:
                raise CompileError(f"line {e[2]}: * needs a pointer")
            self.op("P_OP", "PO_LB" if t[0] == "char" else "PO_LW")
            return (t[0], False)
        if kind == "addr":
            return self.addr_of(e)
        if kind == "index":
            t = self.index_addr(e)
            self.op("P_OP", "PO_LB" if t[0] == "char" else "PO_LW")
            return (t[0], False)
        if kind == "bin":
            return self.binary(e)
        raise CompileError(f"internal: unknown expression {kind}")

    def addr_of(self, e):
        x, line = e[1], e[2]
        if x[0] == "var":
            if x[1] not in self.vars and x[1] not in self.globals and x[1] in self.funcs:
                name = x[1]             # a function's address, typed char *: for icall
                self.op("P_W", "PO_LA", name if name in self.externs else "fn_" + name)
                self.push()
                return ("char", True)
            v = self.var(x[1], x[2])
            if v.ptr and v.arr is None:
                raise CompileError(f"line {line}: pointers to pointers are not in this slice")
            if isinstance(v, Local):
                self.op("P_B", "PO_LLA", v.off)
            else:
                self.op("P_W", "PO_LA", v.label)
            self.push()
            return (v.base, True)
        if x[0] == "deref":
            t = self.expr(x[1])
            if not t[1]:
                raise CompileError(f"line {line}: * needs a pointer")
            return (t[0], True)
        if x[0] == "index":
            return self.index_addr(x)
        raise CompileError(f"line {line}: cannot take the address of this")

    def operands(self, e):
        _, op, a, b, line = e
        ta, tb = self.pair(lambda: self.expr(a), lambda: self.expr(b), self.need(b))
        if tb[1] and not (op == "-" and ta[1]):
            raise CompileError(f"line {line}: a pointer cannot be the right side of {op} in this slice")
        if tb[1] and ta[0] != tb[0]:
            raise CompileError(f"line {line}: - of a pointer to {tb[0]} from a pointer to {ta[0]}")
        if ta[1] and op not in ("+", "-"):
            raise CompileError(f"line {line}: a pointer can only be added to or subtracted from")
        return ta, tb

    def logical(self, e):
        """a && b, a || b as a value: BRAND/BROR keep the left value when it decides, then LNOT
        and ADDI 1 make 0 or 1 of either side's value."""
        _, op, a, b, line = e
        end = self.new_label()
        self.expr(a)
        self.op("P_BR", "PO_BRAND" if op == "&&" else "PO_BROR", end)
        self.pop()
        self.expr(b)
        self.lab(end)
        self.op("P_OP", "PO_LNOT")
        self.op("P_B", "PO_ADDI", 1)
        return ("int", False)

    def binary(self, e):
        _, op, a, b, line = e
        if op in ("&&", "||"):
            return self.logical(e)
        x = self.simple(b) if op == "+" or (op == "-" and b[0] == "num") else None
        if x:
            ta = self.expr(a)
            if ta[1] and op not in ("+", "-"):
                raise CompileError(f"line {line}: a pointer can only be added to or subtracted from")
            self.add_simple(x, ta[1] and ta[0] == "int", neg=op == "-")
            return (ta[0], True) if ta[1] else ("int", False)
        ta, tb = self.operands(e)
        if tb[1]:                           # pointer difference: elements, an int
            self.op("P_OP", "PO_SUB")
            if ta[0] == "int":
                self.const(1)
                self.op("P_OP", "PO_SHR")   # the byte difference is even
            self.pop()
            return ("int", False)
        scaled = ta[1] and ta[0] == "int"
        if op == "+":
            self.op("P_OP", "PO_IDXW" if scaled else "PO_ADD")
        elif op == "-":
            if scaled:
                self.op("P_OP", "PO_NEG")
                self.op("P_OP", "PO_IDXW")
            else:
                self.op("P_OP", "PO_SUB")
        elif op == "*":
            self.op("P_OP", "PO_MUL")
        elif op == "/":
            self.op("P_OP", "PO_DIV")       # signed, truncating toward zero; by 0 gives 0 (pvm.s _DIV)
        elif op == "%":
            self.op("P_OP", "PO_MOD")       # the dividend's sign, as C's; x % 0 is 0
        elif op in BITOPS:
            self.op("P_OP", BITOPS[op])     # >> is arithmetic (int is signed); counts 0 to 15
        elif op in ("==", "!="):
            self.op("P_OP", "PO_ISEQ" if op == "==" else "PO_ISNE")
            self.op("P_OP", "PO_NEG")       # the VM's true is -1; C's is 1
        else:
            self.op("P_OP", VMCMP[op])
            self.op("P_OP", "PO_NEG")       # as above
        self.pop()
        return (ta[0], True) if ta[1] else ("int", False)

    def call(self, name, args, line):
        if name not in self.funcs:
            raise CompileError(f"line {line}: undefined function {name}")
        params = self.params[name]
        if len(args) != len(params):
            raise CompileError(f"line {line}: {name} takes {len(params)} argument(s), not {len(args)}")
        self.arguments(name, args, [(base, ptr, pname) for base, ptr, pname, _ in params], line)
        self.calls.append((name, line))
        self.op("P_W", "PO_CALL", name if name in self.externs else "fn_" + name)
        self.pop(len(args))
        self.push()

    def arguments(self, name, args, params, line):
        """Push the arguments, the first deepest; through frame temporaries when they would not
        fit. params: (base, pointer, name), base None for any pointer."""
        if self.depth + len(args) > ESLIMIT:
            raise CompileError(f"line {line}: {name} takes {len(args)} arguments; at most {ESLIMIT} fit")
        fits = all(self.depth + i + self.need(a) <= ESLIMIT for i, a in enumerate(args))
        slots = []
        for a, (base, ptr, pname) in zip(args, params):
            t = self.expr(a)
            what = f"argument {pname} of {name}"
            if base is not None:
                self.check((base, ptr), t, a, line, what)
            elif not t[1]:
                raise CompileError(f"line {line}: {what}: a number where a pointer is needed")
            if not fits:
                slots.append(self.temp())
                self.op("P_B", "PO_SLW", slots[-1])
                self.pop()
        for s in slots:
            self.op("P_B", "PO_LLW", s)
            self.push()
        self.temps += reversed(slots)

    def icall(self, args, line):
        """icall(p): call the code at p, a bytecode function (one that starts with JSR
        pvm_interp, as &f gives) or native code; no arguments, its result is the value."""
        if len(args) != 1:
            raise CompileError(f"line {line}: icall takes 1 argument, not {len(args)}")
        if not self.expr(args[0])[1]:
            raise CompileError(f"line {line}: argument 1 of icall: a number where a pointer is needed")
        self.op("P_OP", "PO_ICAL")          # pops the address, pushes the result
        self.straight = 0

    def syscall(self, name, args, line):
        """read(fd, buf, n), write(fd, buf, n), open(path, flags), close(fd), exit(status): one
        SYS each, the kernel's r0 and r1 stored from the eval stack after every argument is
        evaluated (a call inside an argument may make syscalls of its own). open evaluates flags
        before path (C leaves the order open), so that path is the one under TOS."""
        sysn, fix, types = SYSCALLS[name]
        if len(args) != len(types):
            raise CompileError(f"line {line}: {name} takes {len(types)} argument(s), not {len(args)}")
        params = [(t[0], t[1], str(i + 1)) if t else (None, True, str(i + 1)) for i, t in enumerate(types)]
        if name == "open":
            args, params = args[::-1], params[::-1]
        self.arguments(name, args, params, line)
        for reg in ("r1", "r0")[3 - len(args):]:
            self.op("P_W", "PO_SAW", reg)
            self.pop()
        self.op("P_SYS", sysn)              # pops the last argument, pushes the result
        if fix:
            self.helper(fix)

    def puts(self, args, line, value):
        if len(args) != 1 or args[0][0] != "str":
            raise CompileError(f"line {line}: puts takes one string literal")
        data = args[0][1]
        if 0 in data:
            raise CompileError(f"line {line}: a \\0 in a string would end it early; not in this slice")
        if data:
            self.op("P_W", "PO_LA", self.add_string(data, share=True))
            self.op("P_W", "PO_SAW", "r0")
            self.const(len(data))
            self.op("P_W", "PO_SAW", "r1")
            self.const(1)                   # fd 1 = stdout
            self.push()
            self.op("P_SYS", "SYSN_WRITE")
            self.op("P_OP", "PO_DROP")
            self.pop()
        if value:
            self.const(0)
            self.push()


def compile_pcode(src, fstack=None):
    """ca65 source for the program (assemble with -I include -I src/pvm; link with pvmlink)."""
    import sys
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 6000))
    try:
        if fstack is None:              # an explicit argument wins; else the program's own, else the default
            m = re.search(r"^/\*\s*fstack\s+(\d+)\s*\*/", src, re.M)
            fstack = int(m.group(1)) if m else FSTACK
        if not FSTACK_MIN <= fstack <= FSTACK_MAX:
            raise CompileError(f"fstack {fstack}: the frame stack is {FSTACK_MIN} to {FSTACK_MAX} bytes")
        funcs, globs = cc.Parser(cc.lex(src)).program()
        seen = set()
        for name, _, _, line in funcs:
            if name in seen:
                raise CompileError(f"line {line}: function {name} is defined twice")
            seen.add(name)
        return PGen(funcs, fstack, bool(re.search(r"^/\*\s*xops\s*\*/", src, re.M))).program(funcs, globs)
    except RecursionError:
        raise CompileError("expression nested too deeply for the compiler") from None
    finally:
        sys.setrecursionlimit(limit)
