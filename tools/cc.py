#!/usr/bin/env python3
"""S14 host-side reference: a C subset compiled to `as` source (no kernel bytes, no device).

  python3 tools/cc.py prog.c > prog.s        then on the C64:  as prog.s prog

Subset: `int` (16 bit) and `char` (8 bit, zero-extended when read), pointers to int or char,
arrays of int or char (local, static storage), functions with parameters (passed on the
software stack and stored in each function's static parameter slots), local variables, unary
`- * &`, `+ - == != < > <= >=`, indexing `a[i]`, calls, `if`/`else`, `while`, `for`, `return`,
blocks, decimal and 0x numbers, and `puts("...")` (the one builtin: prints a string literal).

Not in this slice: `* /` as binary operators (`*` is only the dereference), globals, pointers to
pointers, `char` return types, `#include`, recursion (static locals), `&&` `||` `!`.

Emitted code: `as` syntax (labels, .byte, .res, `#<`, `(zp),y`); symbols at most 14 characters.
Calling convention: the value of an expression is in `acc` (16 bit, lo then hi); a binary
operator pushes the left value on a memory stack (`cc_stk`, 32 levels) and pops it into `tmp`.
A call evaluates its arguments onto the same stack, pops them into the callee's parameter
slots, then calls. Pointers are dereferenced through `cc_ptr`, which is in zero page ($2b).
"""
import re
import sys

KEYWORDS = {"int", "char", "if", "else", "while", "for", "return"}
MAX_DEPTH = 32                       # values pushed at once: cc_stk holds 32 two-byte values
SYMMAX = 14                          # `as` keeps 14 characters of a symbol (getname: cpx #14)
LINE_BYTES = 16                      # .byte values per emitted line (as keeps at most 254 characters a line)
SYMTABLE = 220                       # as NSYM 255 less its 35 builtins
STATIC_MAX = 8192                    # bytes of static variables a program may have (a project limit: the owner may change it)

TOKEN = re.compile(r"""
    (?P<ws>\s+) | (?P<lc>//[^\n]*) | (?P<bc>/\*.*?\*/) |
    (?P<num>0[xX][0-9a-fA-F]+|[0-9]+) |
    (?P<str>"(?:\\.|[^"\\\n])*") |
    (?P<id>[A-Za-z_][A-Za-z_0-9]*) |
    (?P<op>==|!=|<=|>=|[-+*/<>=(){};,&\[\]])
""", re.X | re.S)

ESCAPES = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, '"': 34}


class CompileError(Exception):
    pass


def lex(src):
    toks, pos, line = [], 0, 1
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m:
            raise CompileError(f"line {line}: bad character {src[pos]!r}")
        kind, text = m.lastgroup, m.group()
        if kind == "num":
            v = int(text, 16) if text[:2].lower() == "0x" else int(text)
            if v > 0xFFFF:
                raise CompileError(f"line {line}: number {text} does not fit in 16 bits")
            toks.append(("num", v, line))
        elif kind == "str":
            toks.append(("str", unescape(text[1:-1], line), line))
        elif kind == "id":
            toks.append(("kw" if text in KEYWORDS else "id", text, line))
        elif kind == "op":
            toks.append(("op", text, line))
        line += text.count("\n")
        pos = m.end()
    toks.append(("eof", None, line))
    return toks


def unescape(body, line):
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            i += 1
            if i >= len(body) or body[i] not in ESCAPES:
                raise CompileError(f"line {line}: bad escape in string literal")
            out.append(ESCAPES[body[i]])
        else:
            if ord(c) > 255:
                raise CompileError(f"line {line}: string literal characters must be Latin-1 (as stores 8 bits)")
            out.append(ord(c))
        i += 1
    if 0 in out:
        raise CompileError(f"line {line}: a \\0 in a string would end it early; not in this slice")
    return bytes(out)


LEVELS = [("==", "!="), ("<", ">", "<=", ">="), ("+", "-"), ("*", "/")]
TYPES = ("int", "char")


class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k]

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def at(self, kind, value=None):
        tok = self.peek()
        return tok[0] == kind and (value is None or tok[1] == value)

    def expect(self, kind, value=None):
        tok = self.take()
        if tok[0] != kind or (value is not None and tok[1] != value):
            want = repr(value) if value is not None else kind
            got = tok[1] if tok[1] is not None else "end of file"
            raise CompileError(f"line {tok[2]}: expected {want}, got {got!r}")
        return tok

    def at_type(self):
        return self.at("kw") and self.peek()[1] in TYPES

    def program(self):
        funcs, globs = [], []
        while not self.at("eof"):
            if self.is_function():
                funcs.append(self.function())
            else:
                d = self.decl()
                self.expect("op", ";")
                globs.append(d)
        return funcs, globs

    def is_function(self):
        j = self.i + 1
        if self.t[j][:2] == ("op", "*"):
            j += 1
        if j + 1 >= len(self.t):
            return False            # the file ends here: decl() reports what is missing
        return self.t[j + 1][:2] == ("op", "(")

    def function(self):
        self.expect("kw", "int")
        name, line = self.expect("id")[1], self.peek()[2]
        self.expect("op", "(")
        params = []
        if not self.at("op", ")"):
            while True:
                pline = self.peek()[2]
                base = self.expect("kw")[1]
                if base not in TYPES:
                    raise CompileError(f"line {pline}: expected a parameter type")
                ptr = self.at("op", "*") and bool(self.take())
                pname = self.expect("id")[1]
                if self.at("op", "["):
                    raise CompileError(f"line {pline}: array parameters are not in this slice")
                params.append((base, ptr, pname, pline))
                if not self.at("op", ","):
                    break
                self.take()
        self.expect("op", ")")
        return name, params, self.block(), line

    def block(self):
        self.expect("op", "{")
        stmts = []
        while not self.at("op", "}"):
            if self.at("eof"):
                raise CompileError(f"line {self.peek()[2]}: missing '}}'")
            stmts.append(self.stmt())
        self.take()
        return stmts

    def decl(self):
        """`int|char [*] name [ [n] ] [= expr]` (without the ';'). An array's size may be left
        out when a string initialises it; a string initialiser is a ("str", data, line) node."""
        line = self.peek()[2]
        base = self.take()[1]
        ptr = self.at("op", "*") and bool(self.take())
        name = self.expect("id")[1]
        arr, init = None, None
        if self.at("op", "["):
            self.take()
            if self.at("op", "]"):
                arr = "infer"
            else:
                n = self.expect("num")[1]
                if n < 1:
                    raise CompileError(f"line {line}: an array needs at least one element")
                arr = n
            self.expect("op", "]")
            if ptr:
                raise CompileError(f"line {line}: an array of pointers is not in this slice")
        if self.at("op", "="):
            self.take()
            if self.at("str"):
                tok = self.take()
                init = ("str", tok[1], tok[2])
            else:
                init = self.expr()
        if arr is not None and (init is None and arr == "infer"):
            raise CompileError(f"line {line}: an array with no size needs a size or a string")
        if arr is not None and init is not None and init[0] != "str":
            raise CompileError(f"line {line}: an array can only be initialised from a string literal")
        if init is not None and init[0] == "str" and arr is None and not ptr:
            raise CompileError(f"line {line}: a string initialises a char array or a char pointer")
        return ("decl", base, ptr, name, arr, init, line)

    def simple(self):
        """An assignment or an expression statement, without the ';'."""
        line = self.peek()[2]
        e = self.expr()
        if self.at("op", "="):
            self.take()
            return ("assign", e, self.expr(), line)
        return ("expr", e, line)

    def stmt(self):
        line = self.peek()[2]
        if self.at_type():
            s = self.decl()
            self.expect("op", ";")
            return s
        if self.at("kw", "if"):
            self.take()
            cond = self.paren_expr()
            then = self.stmt()
            other = None
            if self.at("kw", "else"):
                self.take()
                other = self.stmt()
            return ("if", cond, then, other, line)
        if self.at("kw", "while"):
            self.take()
            cond = self.paren_expr()
            return ("while", cond, self.stmt(), line)
        if self.at("kw", "for"):
            return self.for_stmt(line)
        if self.at("kw", "return"):
            self.take()
            value = None if self.at("op", ";") else self.expr()
            self.expect("op", ";")
            return ("return", value, line)
        if self.at("op", "{"):
            return ("block", self.block(), line)
        s = self.simple()
        self.expect("op", ";")
        return s

    def for_stmt(self, line):
        """for (init; cond; step) body  ==  { init; while (cond) { body; step; } }"""
        self.take()
        self.expect("op", "(")
        init = None
        if self.at_type():
            init = self.decl()
            self.expect("op", ";")
        elif not self.at("op", ";"):
            init = self.simple()
            self.expect("op", ";")
        else:
            self.take()
        cond = ("num", 1, line)
        if not self.at("op", ";"):
            cond = self.expr()
        self.expect("op", ";")
        step = None
        if not self.at("op", ")"):
            step = self.simple()
        self.expect("op", ")")
        body = self.stmt()
        inner = [body] + ([step] if step else [])
        loop = ("while", cond, ("block", inner, line), line)
        return ("block", ([init] if init else []) + [loop], line)

    def paren_expr(self):
        self.expect("op", "(")
        e = self.expr()
        self.expect("op", ")")
        return e

    def expr(self):
        return self.binary(0)

    def binary(self, level):
        if level == len(LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek()[0] == "op" and self.peek()[1] in LEVELS[level]:
            op, line = self.take()[1], self.peek()[2]
            left = ("bin", op, left, self.binary(level + 1), line)
        return left

    def unary(self):
        if self.at("op", "-"):
            line = self.take()[2]
            return ("neg", self.unary(), line)
        if self.at("op", "*"):
            line = self.take()[2]
            return ("deref", self.unary(), line)
        if self.at("op", "&"):
            line = self.take()[2]
            return ("addr", self.unary(), line)
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while self.at("op", "["):
            line = self.take()[2]
            i = self.expr()
            self.expect("op", "]")
            e = ("index", e, i, line)
        return e

    def primary(self):
        kind, value, line = self.take()
        if kind == "num":
            return ("num", value, line)
        if kind == "str":
            return ("str", value, line)
        if kind == "id":
            if self.at("op", "("):
                self.take()
                args = []
                if not self.at("op", ")"):
                    args.append(self.expr())
                    while self.at("op", ","):
                        self.take()
                        args.append(self.expr())
                self.expect("op", ")")
                return ("call", value, args, line)
            return ("var", value, line)
        if kind == "op" and value == "(":
            e = self.expr()
            self.expect("op", ")")
            return e
        got = value if value is not None else "end of file"
        raise CompileError(f"line {line}: expected an expression, got {got!r}")


RUNTIME = """\
; --- runtime (fixed text; the same for every program) ---
cc_push:
        ldx cc_sp
        lda acc
        sta cc_stk,x
        inx
        lda acc+1
        sta cc_stk,x
        inx
        stx cc_sp
        rts
cc_pop:
        ldx cc_sp
        dex
        dex
        stx cc_sp
        lda cc_stk,x
        sta tmp
        inx
        lda cc_stk,x
        sta tmp+1
        rts
cc_add:                         ; acc = tmp + acc
        clc
        lda tmp
        adc acc
        sta acc
        lda tmp+1
        adc acc+1
        sta acc+1
        rts
cc_sub:                         ; acc = tmp - acc
        sec
        lda tmp
        sbc acc
        sta acc
        lda tmp+1
        sbc acc+1
        sta acc+1
        rts
cc_swap:                        ; tmp <-> acc
        lda tmp
        ldx acc
        sta acc
        stx tmp
        lda tmp+1
        ldx acc+1
        sta acc+1
        stx tmp+1
        rts
cc_lt:                          ; acc = 1 if tmp < acc (unsigned), else 0
        sec
        lda tmp
        sbc acc
        lda tmp+1
        sbc acc+1
        bcc *+11                ; borrow: the 1 below (relative: no label to spend)
        lda #0
        sta acc
        sta acc+1
        rts
        lda #1
        sta acc
        lda #0
        sta acc+1
        rts
cc_eq:                          ; acc = 1 if tmp == acc, else 0
        lda tmp
        cmp acc
        bne *+21
        lda tmp+1
        cmp acc+1
        bne *+13
        lda #1
        sta acc
        lda #0
        sta acc+1
        rts
        lda #0
        sta acc
        sta acc+1
        rts
cc_not:                         ; acc = 1 if acc == 0, else 0
        lda acc
        ora acc+1
        beq *+11
        lda #0
        sta acc
        sta acc+1
        rts
        lda #1
        sta acc
        lda #0
        sta acc+1
        rts
rt_puts:                        ; print the zero-terminated string at cc_ptr
        ldy #0
rt_puts_1:
        lda (cc_ptr),y
        beq rt_puts_done
        sty cc_y
        sta cc_ch
        lda #<cc_ch
        sta r0
        lda #>cc_ch
        sta r0+1
        lda #1
        sta r1
        lda #0
        sta r1+1
        lda #1                  ; fd 1 = stdout
        jsr sys_write
        ldy cc_y
        iny
        jmp rt_puts_1
rt_puts_done:
        rts
cc_mul:                         ; acc = tmp * acc (the low 16 bits)
        lda #0
        sta cc_mr
        sta cc_mr+1
        ldx #16
cc_mul_1:
        lda acc
        and #1
        beq cc_mul_2
        clc
        lda cc_mr
        adc tmp
        sta cc_mr
        lda cc_mr+1
        adc tmp+1
        sta cc_mr+1
cc_mul_2:
        lsr acc+1
        ror acc
        asl tmp
        rol tmp+1
        dex
        bne cc_mul_1
        lda cc_mr
        sta acc
        lda cc_mr+1
        sta acc+1
        rts
cc_div:                         ; acc = tmp / acc (unsigned; dividing by 0 gives 65535)
        lda acc
        sta cc_dv
        lda acc+1
        sta cc_dv+1
        lda tmp
        sta cc_q
        lda tmp+1
        sta cc_q+1
        lda #0
        sta cc_rm
        sta cc_rm+1
        sta cc_ov
        ldx #16
cc_div_1:
        asl cc_q
        rol cc_q+1
        rol cc_rm
        rol cc_rm+1
        rol cc_ov               ; the remainder's 17th bit, when it has one
        sec
        lda cc_rm
        sbc cc_dv
        tay
        lda cc_rm+1
        sbc cc_dv+1
        sta cc_t
        lda cc_ov
        bne cc_div_3            ; 17 bits: the remainder is at least the divisor
        bcc cc_div_2            ; below the divisor: keep the remainder
cc_div_3:
        sty cc_rm
        lda cc_t
        sta cc_rm+1
        lda #0
        sta cc_ov
        inc cc_q                ; the quotient's bit 0 (it was shifted in as 0)
cc_div_2:
        dex
        bne cc_div_1
        lda cc_q
        sta acc
        lda cc_q+1
        sta acc+1
        rts
"""
DATA = """\
; --- data ---
cc_ptr = $2b           ; zero page: (zp),y in rt_puts needs a zero-page pointer (program ZP is $23-$2f)
acc:    .res 2
tmp:    .res 2
cc_mr:  .res 2
cc_dv:  .res 2
cc_rm:  .res 2
cc_q:   .res 2
cc_ov:  .res 1
cc_t:   .res 1
cc_y:   .res 1
cc_ch:  .res 1
cc_sp:  .res 1
cc_stk: .res 64
"""

class Var:
    """A variable: its label, element base ('int' or 'char'), pointer flag and array length."""

    def __init__(self, label, base, ptr, arr):
        self.label, self.base, self.ptr, self.arr = label, base, ptr, arr

    def elem(self):
        return 2 if self.base == "int" else 1

    def nbytes(self):
        if self.arr is not None:
            return self.elem() * self.arr
        if self.ptr:
            return 2
        return self.elem()


class Gen:
    def __init__(self, funcs):
        self.funcs = {name: line for name, _, _, line in funcs}
        self.params = {name: [(base, ptr, pname, f"v_{name}_{pname}") for base, ptr, pname, _ in params]
                       for name, params, _, _ in funcs}
        self.out, self.n, self.depth = [], 0, 0
        self.strings, self.locals, self.calls = [], [], []
        self.shared = {}                   # puts() strings, by text
        self.names, self.fn_max, self.call_sites, self._worst = {}, {}, {}, {}
        self.fn, self.vars = None, {}
        self.globals, self.gdata, self.gres = {}, [], []

    def ins(self, text):
        self.out.append("        " + text)

    def lab(self, name):
        self.out.append(name + ":")

    def new_label(self, prefix="L"):
        self.n += 1
        return f"{prefix}{self.n}"

    def claim(self, lbl, line):
        if len(lbl) > SYMMAX:
            raise CompileError(f"line {line}: {lbl} is longer than {SYMMAX} characters (as limit)")
        key = lbl.lower()
        if key in self.names:
            raise CompileError(f"line {line}: {lbl} clashes with {self.names[key]} (as ignores case)")
        self.names[key] = lbl

    def check(self, want, got, node, line, what):
        """Types must agree: a number is not a pointer, and a pointer must point at the same base.
        The literal 0 is the null pointer."""
        if want[1] == got[1]:
            if want[1] and want[0] != got[0]:
                raise CompileError(f"line {line}: {what}: a pointer to {got[0]} where a pointer to {want[0]} is needed")
            return
        if want[1] and node[0] == "num" and node[1] == 0:
            return
        raise CompileError(f"line {line}: {what}: a {'pointer' if got[1] else 'number'} where a "
                           f"{'pointer' if want[1] else 'number'} is needed")

    def global_var(self, d):
        _, base, ptr, name, arr, init, line = d
        if name in self.globals:
            raise CompileError(f"line {line}: global {name} is already declared")
        if arr == "infer":
            arr = len(init[1]) + 1
        if name in self.funcs:
            raise CompileError(f"line {line}: {name} is a function; a global cannot have its name")
        v = Var(f"g_{name}", base, ptr, arr)
        self.claim(v.label, line)
        self.globals[name] = v
        n = v.nbytes()
        if init is not None and init[0] == "num" and not ptr and base == "char" and init[1] > 255:
            raise CompileError(f"line {line}: a char global takes 0 to 255")
        if arr is not None and init is not None:
            if base != "char" or ptr:
                raise CompileError(f"line {line}: a string initialises a char array")
            if len(init[1]) + 1 > arr:
                raise CompileError(f"line {line}: the string does not fit in {name}")
            data = list(init[1]) + [0] * (arr - len(init[1]))
        elif init is None:
            self.gres.append(f"{v.label}: .res {n}")
            return
        elif ptr:
            if init[0] == "str":
                if base != "char":
                    raise CompileError(f"line {line}: a string is a pointer to char, not to {base}")
                self.gdata.append(f"{v.label}: .word {self.add_string(init[1])}")
                return
            if init[0] == "num" and init[1] == 0:
                self.gdata.append(f"{v.label}: .word 0")
                return
            raise CompileError(f"line {line}: a global pointer takes a string or 0")
        elif init[0] == "num" or (init[0] == "neg" and init[1][0] == "num" and base == "int"):
            n = init[1] if init[0] == "num" else -init[1][1]     # an int may start negative (two's complement)
            value = n & 0xFFFF
            data = [value & 255] if base == "char" else [value & 255, value >> 8]
        else:
            raise CompileError(f"line {line}: a global needs a literal initialiser")
        vals = [str(b) for b in data]
        self.gdata.append(f"{v.label}:")
        for i in range(0, len(vals), LINE_BYTES):
            self.gdata.append("        .byte " + ", ".join(vals[i:i + LINE_BYTES]))

    def program(self, funcs, globs):
        if "main" not in self.funcs:
            raise CompileError("no function main")
        if self.params["main"]:
            raise CompileError(f"line {self.funcs['main']}: main takes no parameters (start passes none)")
        for d in globs:
            self.global_var(d)
        self.lab("start")
        self.ins("lda #0")
        self.ins("sta cc_sp")
        self.ins("jsr fn_main")
        self.ins("lda #0")
        self.ins("jmp sys_exit")
        for name, params, body, line in funcs:
            self.function(name, params, body, line)
        for name, line in self.calls:
            if name not in self.funcs:
                raise CompileError(f"line {line}: undefined function {name}")
        total = sum(n for _, n in self.locals) + sum(v.nbytes() for v in self.globals.values())
        if total > STATIC_MAX:
            raise CompileError(f"the program's static variables take {total} bytes; the limit is {STATIC_MAX}")
        for name in self.funcs:
            w = self.worst(name, [])
            if w > MAX_DEPTH:
                raise CompileError(f"{name}: stack use along one call chain is {w} values; cc_stk holds 32")
        # every initialised byte comes before any .res: as counts the program's size on the way
        return ("\n".join(self.out) + "\n" + RUNTIME + self.strings_text() + DATA
                + "\n".join(self.gdata) + "\n" + self.locals_text() + "\n".join(self.gres) + "\n")

    def worst(self, f, path):
        """Most values pushed at once on any call chain that starts in f (no recursion allowed)."""
        if f in path:
            raise CompileError(f"recursion: {' -> '.join(path + [f])} (locals are static: no recursion yet)")
        if f not in self._worst:
            w = self.fn_max.get(f, 0)
            for callee, _line, d in self.call_sites.get(f, []):
                w = max(w, d + self.worst(callee, path + [f]))
            self._worst[f] = w
        return self._worst[f]

    def function(self, name, params, body, line):
        self.fn, self.vars = name, {}
        self.claim("fn_" + name, line)
        self.lab("fn_" + name)
        for base, ptr, pname, pline in params:
            self.declare(pname, base, ptr, None, pline)
        for s in body:
            self.stmt(s)
        self.ins("lda #0")
        self.ins("sta acc")
        self.ins("sta acc+1")
        self.ins("rts")

    def declare(self, name, base, ptr, arr, line):
        if name in self.vars:
            raise CompileError(f"line {line}: {name} is already declared in {self.fn}")
        lbl = f"v_{self.fn}_{name}"
        self.claim(lbl, line)
        v = Var(lbl, base, ptr, arr)
        self.vars[name] = v
        self.locals.append((lbl, v.nbytes()))
        return v

    def add_string(self, data, share=False):
        """share: reuse the label of an identical puts() string. Only puts() shares: a pointer to a
        literal may be written through, so each pointer gets its own bytes."""
        if share and data in self.shared:
            return self.shared[data]
        lbl = f"s_{len(self.strings) + 1}"
        self.strings.append((lbl, data))
        if share:
            self.shared[data] = lbl
        return lbl

    def strings_text(self):
        out = []
        for lbl, data in self.strings:
            vals = [str(b) for b in data + b"\0"]
            out.append(f"{lbl}:")
            for i in range(0, len(vals), LINE_BYTES):
                out.append("        .byte " + ", ".join(vals[i:i + LINE_BYTES]))
        return "\n".join(out) + "\n"

    def locals_text(self):
        return "".join(f"{lbl}: .res {n}\n" for lbl, n in self.locals)

    def var(self, name, line):
        if name in self.vars:
            return self.vars[name]
        if name in self.globals:
            return self.globals[name]
        raise CompileError(f"line {line}: undefined variable {name}")

    def push(self):
        self.depth += 1
        self.fn_max[self.fn] = max(self.fn_max.get(self.fn, 0), self.depth)
        if self.depth > MAX_DEPTH:
            raise CompileError("expression too deeply nested for the software stack")
        self.ins("jsr cc_push")

    def pop(self):
        self.depth -= 1
        self.ins("jsr cc_pop")

    def load16(self, lbl):
        self.ins(f"lda {lbl}")
        self.ins("sta acc")
        self.ins(f"lda {lbl}+1")
        self.ins("sta acc+1")

    def store16(self, lbl):
        self.ins("lda acc")
        self.ins(f"sta {lbl}")
        self.ins("lda acc+1")
        self.ins(f"sta {lbl}+1")

    def address_of_label(self, lbl):
        self.ins(f"lda #<{lbl}")
        self.ins("sta acc")
        self.ins(f"lda #>{lbl}")
        self.ins("sta acc+1")

    def load_through(self, base):
        """acc is an address: load the element at it into acc (char: zero-extended)."""
        self.ins("lda acc")
        self.ins("sta cc_ptr")
        self.ins("lda acc+1")
        self.ins("sta cc_ptr+1")
        self.ins("ldy #0")
        self.ins("lda (cc_ptr),y")
        self.ins("sta acc")
        if base == "char":
            self.ins("lda #0")
            self.ins("sta acc+1")
        else:
            self.ins("ldy #1")
            self.ins("lda (cc_ptr),y")
            self.ins("sta acc+1")

    def store_through(self, base):
        """tmp is the address, acc the value: store the element (char: the low byte)."""
        self.ins("lda tmp")
        self.ins("sta cc_ptr")
        self.ins("lda tmp+1")
        self.ins("sta cc_ptr+1")
        self.ins("ldy #0")
        self.ins("lda acc")
        self.ins("sta (cc_ptr),y")
        if base == "int":
            self.ins("ldy #1")
            self.ins("lda acc+1")
            self.ins("sta (cc_ptr),y")

    def stmt(self, s):
        kind = s[0]
        if kind == "decl":
            _, base, ptr, name, arr, init, line = s
            if arr == "infer":
                arr = len(init[1]) + 1
            if arr is not None and init is not None:
                # a char array takes a string: copied in each time the declaration runs
                if base != "char" or ptr:
                    raise CompileError(f"line {line}: a string initialises a char array")
                if arr > 254:
                    raise CompileError(f"line {line}: a local char array takes a string of at most 254 bytes")
                if len(init[1]) + 1 > arr:
                    raise CompileError(f"line {line}: the string does not fit in {name}")
                v = self.declare(name, base, ptr, arr, line)
                lbl = self.add_string(init[1])
                for i in range(arr):
                    self.ins(f"lda {lbl}+{i}" if i <= len(init[1]) else "lda #0")
                    self.ins(f"sta {v.label}+{i}" if i else f"sta {v.label}")
                return
            v = self.declare(name, base, ptr, arr, line)
            if init is not None:
                t = self.expr(init)
                self.check((v.base, v.ptr), t, init, line, "initialise")
                self.store_scalar(v)
        elif kind == "assign":
            self.assign(s[1], s[2], s[3])
        elif kind == "expr":
            self.expr(s[1])
        elif kind == "return":
            if s[1] is None:
                self.ins("lda #0")
                self.ins("sta acc")
                self.ins("sta acc+1")
            else:
                self.check(("int", False), self.expr(s[1]), s[1], s[2], "return")
            self.ins("rts")
        elif kind == "if":
            _, cond, then, other, _line = s
            else_l, end_l = self.new_label(), self.new_label()
            self.test(cond)
            self.ins("bne *+5")         # true: skip the 3-byte jump to the else part (no label)
            self.ins(f"jmp {else_l}")
            self.stmt(then)
            self.ins(f"jmp {end_l}")
            self.lab(else_l)
            if other is not None:
                self.stmt(other)
            self.lab(end_l)
        elif kind == "while":
            _, cond, body, _line = s
            top_l, end_l = self.new_label(), self.new_label()
            self.lab(top_l)
            self.test(cond)
            self.ins("bne *+5")         # true: skip the 3-byte jump out of the loop (no label)
            self.ins(f"jmp {end_l}")
            self.stmt(body)
            self.ins(f"jmp {top_l}")
            self.lab(end_l)
        elif kind == "block":
            for x in s[1]:
                self.stmt(x)

    def store_scalar(self, v):
        if v.base == "char" and not v.ptr:
            self.ins("lda acc")
            self.ins(f"sta {v.label}")
        else:
            self.store16(v.label)

    def assign(self, lhs, rhs, line):
        if lhs[0] == "var":
            v = self.var(lhs[1], lhs[2])
            if v.arr is not None:
                raise CompileError(f"line {line}: cannot assign to the array {lhs[1]}")
            self.check((v.base, v.ptr), self.expr(rhs), rhs, line, "assign")
            self.store_scalar(v)
            return
        if lhs[0] == "deref":
            t = self.expr(lhs[1])
            if not t[1]:
                raise CompileError(f"line {line}: * needs a pointer")
            base = t[0]
        elif lhs[0] == "index":
            base = self.index_addr(lhs)[0]
        else:
            raise CompileError(f"line {line}: cannot assign to this")
        self.push()
        self.check((base, False), self.expr(rhs), rhs, line, "store")
        self.pop()
        self.store_through(base)

    def test(self, cond):
        """Leave acc's truth in the flags: Z set when the condition is false."""
        self.expr(cond)
        self.ins("lda acc")
        self.ins("ora acc+1")

    def index_addr(self, node):
        """a[i]: the element's address in acc. Returns the element type (base, True)."""
        _, base_e, idx_e, line = node
        t = self.expr(base_e)
        if not t[1]:
            raise CompileError(f"line {line}: a[i] needs a pointer or an array")
        self.push()
        ti = self.expr(idx_e)
        if ti[1]:
            raise CompileError(f"line {line}: an index must be a number")
        if t[0] == "int":
            self.ins("asl acc")
            self.ins("rol acc+1")
        self.pop()
        self.ins("jsr cc_add")
        return (t[0], True)

    def expr(self, e):
        """Leave the value of e in acc; return its type (base, is_pointer)."""
        kind = e[0]
        if kind == "num":
            v = e[1]
            self.ins(f"lda #{v & 255}")
            self.ins("sta acc")
            self.ins(f"lda #{v >> 8}")
            self.ins("sta acc+1")
            return ("int", False)
        if kind == "var":
            v = self.var(e[1], e[2])
            if v.arr is not None:
                self.address_of_label(v.label)
                return (v.base, True)
            if v.ptr:
                self.load16(v.label)
                return (v.base, True)
            if v.base == "char":
                self.ins(f"lda {v.label}")
                self.ins("sta acc")
                self.ins("lda #0")
                self.ins("sta acc+1")
                return ("char", False)
            self.load16(v.label)
            return ("int", False)
        if kind == "str":
            if 0 in e[1]:
                raise CompileError(f"line {e[2]}: a \\0 in a string would end it early; not in this slice")
            self.address_of_label(self.add_string(e[1]))
            return ("char", True)
        if kind == "call":
            _, name, args, line = e
            if name == "puts":
                self.puts(args, line)
            else:
                self.call(name, args, line)
            return ("int", False)
        if kind == "neg":
            if self.expr(e[1])[1]:
                raise CompileError(f"line {e[2]}: - of a pointer is not in this slice")
            self.ins("lda #0")
            self.ins("sta tmp")
            self.ins("sta tmp+1")
            self.ins("jsr cc_sub")
            return ("int", False)
        if kind == "deref":
            t = self.expr(e[1])
            if not t[1]:
                raise CompileError(f"line {e[2]}: * needs a pointer")
            self.load_through(t[0])
            return (t[0], False)
        if kind == "addr":
            return self.addr_of(e)
        if kind == "index":
            t = self.index_addr(e)
            self.load_through(t[0])
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
            self.address_of_label(v.label)
            return (v.base, True)
        if x[0] == "deref":
            t = self.expr(x[1])
            if not t[1]:
                raise CompileError(f"line {line}: * needs a pointer")
            return (t[0], True)
        if x[0] == "index":
            return self.index_addr(x)
        raise CompileError(f"line {line}: cannot take the address of this")

    def binary(self, e):
        _, op, a, b, line = e
        ta = self.expr(a)
        self.push()
        tb = self.expr(b)
        if tb[1]:
            raise CompileError(f"line {line}: a pointer cannot be the right side of {op} in this slice")
        if ta[1] and op not in ("+", "-"):
            raise CompileError(f"line {line}: a pointer can only be added to or subtracted from")
        if ta[1] and ta[0] == "int":
            self.ins("asl acc")          # scale the index by the element size (2 for int)
            self.ins("rol acc+1")
        self.pop()
        for routine in BINOPS[op]:
            self.ins(f"jsr {routine}")
        if ta[1]:
            return (ta[0], True)
        return ("int", False)

    def call(self, name, args, line):
        if name not in self.funcs:
            raise CompileError(f"line {line}: undefined function {name}")
        params = self.params[name]
        if len(args) != len(params):
            raise CompileError(f"line {line}: {name} takes {len(params)} argument(s), not {len(args)}")
        for a, (base, ptr, pname, _lbl) in zip(args, params):
            self.check((base, ptr), self.expr(a), a, line, f"argument {pname} of {name}")
            self.push()
        for base, ptr, _pname, lbl in reversed(params):
            self.pop()
            self.ins("lda tmp")
            self.ins(f"sta {lbl}")
            if not (base == "char" and not ptr):
                self.ins("lda tmp+1")
                self.ins(f"sta {lbl}+1")
        self.calls.append((name, line))
        self.call_sites.setdefault(self.fn, []).append((name, line, self.depth))
        self.ins(f"jsr fn_{name}")

    def puts(self, args, line):
        if len(args) != 1 or args[0][0] != "str":
            raise CompileError(f"line {line}: puts takes one string literal")
        data = args[0][1]
        if len(data) > 254:
            raise CompileError(f"line {line}: string literal is longer than 254 bytes (rt_puts indexes with Y)")
        if 0 in data:
            raise CompileError(f"line {line}: a \\0 in a string would end it early; not in this slice")
        lbl = self.add_string(data, share=True)
        self.ins(f"lda #<{lbl}")
        self.ins("sta cc_ptr")
        self.ins(f"lda #>{lbl}")
        self.ins("sta cc_ptr+1")
        self.ins("jsr rt_puts")
        self.ins("lda #0")
        self.ins("sta acc")
        self.ins("sta acc+1")


BINOPS = {
    "+": ["cc_add"],
    "-": ["cc_sub"],
    "*": ["cc_mul"],
    "/": ["cc_div"],
    "==": ["cc_eq"],
    "!=": ["cc_eq", "cc_not"],
    "<": ["cc_lt"],
    ">": ["cc_swap", "cc_lt"],
    "<=": ["cc_swap", "cc_lt", "cc_not"],
    ">=": ["cc_lt", "cc_not"],
}


def compile_c(src):
    """A long left-deep chain (a 600-term sum) recurses once per term in the parser's and the
    code generator's walk: the limit is raised for the compile, and only a chain past it is refused."""
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 6000))
    try:
        return compile_program(src)
    except RecursionError:
        raise CompileError("expression nested too deeply for the compiler") from None
    finally:
        sys.setrecursionlimit(limit)


def compile_program(src):
    funcs, globs = Parser(lex(src)).program()
    seen = set()
    for name, _, _, line in funcs:
        if name in seen:
            raise CompileError(f"line {line}: function {name} is defined twice")
        seen.add(name)
    try:
        text = Gen(funcs).program(funcs, globs)
    except RecursionError:      # the parser builds a left-deep tree; code generation recurses over it too
        raise CompileError("expression nested too deeply for the code generator") from None
    symbols = len(re.findall(r"^[A-Za-z_][A-Za-z_0-9]*:", text, re.M)) + 1   # + cc_ptr =
    if symbols > SYMTABLE:
        raise CompileError(f"program needs {symbols} symbols; as holds {SYMTABLE} for a program")
    return text


def main(argv):
    if len(argv) != 2:
        print("usage: cc.py prog.c > prog.s", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        src = f.read()
    try:
        sys.stdout.write(compile_c(src))
    except CompileError as e:
        print(f"{argv[1]}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
