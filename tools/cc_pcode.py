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

Signed semantics are the native back end's: `int` is signed, so `<` `>` `<=` `>=` compare signed
and `/` truncates toward zero. They are the VM's own ops (ISLT, ISGT, ISLE, ISGE, DIV), which give
-1 for true: a NEG makes it C's 1. x / 0 is 0 (the VM's DIV, changed to give 0 for this; the
native back end does the same). The only native helper left is `cc_copy`, and only a program
that initialises a local char array from a string emits it.
"""
import cc
from cc import CompileError, Var

ESLIMIT = 8                          # eval stack entries a framed function may use (pvm.md, section 4)
FRAME_MAX = 255                      # ENTER/LEAVE take the frame size in a byte
FSTACK = 1024                        # bytes of frame stack (return IPs, spills, frames)
STRAIGHT = 240                       # most bytecode bytes past the IP base before a renormalising branch

SIZE = {"P_CN": 1, "P_OP": 1, "P_B": 2, "P_W": 3, "P_BR": 3, "P_ENTER": 3, "P_SYS": 2}

PRELUDE = """\
; compiled by tools/cc.py --pcode: p-code for /lib/pvm (CX format 2)
.include "breadbin.inc"
.include "pvm.inc"
SYSN_WRITE = (SYS_WRITE - SYS_BASE) / 3
.segment "BSS"
cc_fstk: .res {fstack}
cc_fend:
.segment "CODE"
; native entry: the VM with its frame stack, then main; main's value is the exit status
start:  lda #<cc_fstk
        sta r0
        lda #>cc_fstk
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
}
VMCMP = {"<": "PO_ISLT", ">": "PO_ISGT", "<=": "PO_ISLE", ">=": "PO_ISGE"}   # signed; true is -1


class Local(Var):
    """A parameter or local: its offset in the frame."""

    def __init__(self, off, base, ptr, arr):
        super().__init__(None, base, ptr, arr)
        self.off = off


class PGen(cc.Gen):
    def __init__(self, funcs, fstack=FSTACK):
        super().__init__(funcs)
        self.fstack = fstack
        self.helpers = set()
        self._need = {}

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
            self.function(name, params, body, line)
        for name, line in self.calls:
            if name not in self.funcs:
                raise CompileError(f"line {line}: undefined function {name}")
        total = sum(v.nbytes() for v in self.globals.values())
        if total > cc.STATIC_MAX:
            raise CompileError(f"the program's static variables take {total} bytes; the limit is {cc.STATIC_MAX}")
        helpers = "".join(HELPERS[h] for h in HELPERS if h in self.helpers)
        return (PRELUDE.format(fstack=self.fstack) + "\n".join(self.out) + "\n" + helpers
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
            if kind == "bin":
                n = max(self.need(e[2]), self.need(e[3]), 2)
            elif kind == "index":
                n = max(self.need(e[1]), self.need(e[2]), 2)
            elif kind in ("neg", "deref"):
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
        elif kind == "while":
            # the test at the bottom: one branch an iteration, not two
            _, cond, body, _line = s
            top_l, test_l = self.new_label(), self.new_label()
            if cond[0] == "num" and cond[1] != 0:
                self.lab(top_l)
                self.stmt(body)
                self.op("P_BR", "PO_BRNCH", top_l)
                return
            self.op("P_BR", "PO_BRNCH", test_l)
            self.lab(top_l)
            self.stmt(body)
            self.lab(test_l)
            self.cond(cond, top_l, when=True)
        elif kind == "block":
            for x in s[1]:
                self.stmt(x)

    def cond(self, e, lbl, when=False):
        """Branch to lbl when e's truth is `when`."""
        if e[0] == "bin" and e[1] in ("==", "!="):
            self.operands(e)
            self.op("P_BR", "PO_BREQ" if (e[1] == "==") == when else "PO_BRNE", lbl)
            self.pop(2)
            return
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
            else:
                self.call(name, args, line)
            return ("int", False)
        if kind == "neg":
            if self.expr(e[1])[1]:
                raise CompileError(f"line {e[2]}: - of a pointer is not in this slice")
            self.op("P_OP", "PO_NEG")
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
        if tb[1]:
            raise CompileError(f"line {line}: a pointer cannot be the right side of {op} in this slice")
        if ta[1] and op not in ("+", "-"):
            raise CompileError(f"line {line}: a pointer can only be added to or subtracted from")
        return ta, tb

    def binary(self, e):
        _, op, a, b, line = e
        x = self.simple(b) if op == "+" or (op == "-" and b[0] == "num") else None
        if x:
            ta = self.expr(a)
            if ta[1] and op not in ("+", "-"):
                raise CompileError(f"line {line}: a pointer can only be added to or subtracted from")
            self.add_simple(x, ta[1] and ta[0] == "int", neg=op == "-")
            return (ta[0], True) if ta[1] else ("int", False)
        ta, _ = self.operands(e)
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
        if self.depth + len(args) > ESLIMIT:
            raise CompileError(f"line {line}: {name} takes {len(args)} arguments; at most {ESLIMIT} fit")
        fits = all(self.depth + i + self.need(a) <= ESLIMIT for i, a in enumerate(args))
        slots = []
        for a, (base, ptr, pname, _lbl) in zip(args, params):
            self.check((base, ptr), self.expr(a), a, line, f"argument {pname} of {name}")
            if not fits:
                slots.append(self.temp())
                self.op("P_B", "PO_SLW", slots[-1])
                self.pop()
        for s in slots:
            self.op("P_B", "PO_LLW", s)
            self.push()
        self.temps += reversed(slots)
        self.calls.append((name, line))
        self.op("P_W", "PO_CALL", "fn_" + name)
        self.pop(len(args))
        self.push()

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


def compile_pcode(src, fstack=FSTACK):
    """ca65 source for the program (assemble with -I include -I src/pvm; link with pvmlink)."""
    import sys
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 6000))
    try:
        funcs, globs = cc.Parser(cc.lex(src)).program()
        seen = set()
        for name, _, _, line in funcs:
            if name in seen:
                raise CompileError(f"line {line}: function {name} is defined twice")
            seen.add(name)
        return PGen(funcs, fstack).program(funcs, globs)
    except RecursionError:
        raise CompileError("expression nested too deeply for the compiler") from None
    finally:
        sys.setrecursionlimit(limit)
