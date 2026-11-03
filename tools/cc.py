#!/usr/bin/env python3
"""S14 host-side reference: a small C subset compiled to `as` source (no kernel bytes, no device).

  python3 tools/cc.py prog.c > prog.s        then on the C64:  as prog.s prog

Subset (first slice): `int` only (16 bit), functions with no parameters, local `int` variables
(static storage: no recursion yet), `= + - == != < > <= >=`, unary minus, calls, `if`/`else`,
`while`, `return`, blocks, decimal and 0x numbers, and `puts("...")` (the one builtin, prints a
string literal through sys_write one byte at a time, as hello.s does).

Not in this slice: char, arrays, pointers, `for`, `*` `/`, parameters, globals, `#include`.
Emitted code: `as` syntax (labels, .byte, .res, `#<`, `(zp),y`), symbols at most 15 characters.
Calling convention: the value of an expression is in `acc` (16 bit, lo then hi); a binary
operator pushes the left value on a memory stack (`cc_stk`, 32 levels) and pops it into `tmp`.
"""
import re
import sys

KEYWORDS = {"int", "if", "else", "while", "return"}
MAX_DEPTH = 31                       # cc_stk holds 32 two-byte values
SYMMAX = 15                          # `as` symbol names

TOKEN = re.compile(r"""
    (?P<ws>\s+) | (?P<lc>//[^\n]*) | (?P<bc>/\*.*?\*/) |
    (?P<num>0[xX][0-9a-fA-F]+|[0-9]+) |
    (?P<str>"(?:\\.|[^"\\\n])*") |
    (?P<id>[A-Za-z_][A-Za-z_0-9]*) |
    (?P<op>==|!=|<=|>=|[-+<>=(){};,])
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
            out.append(ord(c))
        i += 1
    return bytes(out)


LEVELS = [("==", "!="), ("<", ">", "<=", ">="), ("+", "-")]


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

    def program(self):
        funcs = []
        while not self.at("eof"):
            funcs.append(self.function())
        return funcs

    def function(self):
        self.expect("kw", "int")
        name, line = self.expect("id")[1], self.peek()[2]
        self.expect("op", "(")
        if not self.at("op", ")"):
            raise CompileError(f"line {line}: parameters are not in this slice")
        self.expect("op", ")")
        return name, self.block(), line

    def block(self):
        self.expect("op", "{")
        stmts = []
        while not self.at("op", "}"):
            if self.at("eof"):
                raise CompileError(f"line {self.peek()[2]}: missing '}}'")
            stmts.append(self.stmt())
        self.take()
        return stmts

    def stmt(self):
        line = self.peek()[2]
        if self.at("kw", "int"):
            self.take()
            name = self.expect("id")[1]
            init = None
            if self.at("op", "="):
                self.take()
                init = self.expr()
            self.expect("op", ";")
            return ("decl", name, init, line)
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
        if self.at("kw", "return"):
            self.take()
            value = None if self.at("op", ";") else self.expr()
            self.expect("op", ";")
            return ("return", value, line)
        if self.at("op", "{"):
            return ("block", self.block(), line)
        if self.at("id") and self.peek(1)[:2] == ("op", "="):
            name = self.take()[1]
            self.take()
            value = self.expr()
            self.expect("op", ";")
            return ("assign", name, value, line)
        value = self.expr()
        self.expect("op", ";")
        return ("expr", value, line)

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
        return self.primary()

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
        bcc cc_lt_1
        lda #0
        sta acc
        sta acc+1
        rts
cc_lt_1:
        lda #1
        sta acc
        lda #0
        sta acc+1
        rts
cc_eq:                          ; acc = 1 if tmp == acc, else 0
        lda tmp
        cmp acc
        bne cc_eq_0
        lda tmp+1
        cmp acc+1
        bne cc_eq_0
        lda #1
        sta acc
        lda #0
        sta acc+1
        rts
cc_eq_0:
        lda #0
        sta acc
        sta acc+1
        rts
cc_not:                         ; acc = 1 if acc == 0, else 0
        lda acc
        ora acc+1
        beq cc_not_1
        lda #0
        sta acc
        sta acc+1
        rts
cc_not_1:
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
"""

DATA = """\
; --- data ---
acc:    .res 2
tmp:    .res 2
cc_ptr: .res 2
cc_y:   .res 1
cc_ch:  .res 1
cc_sp:  .res 1
cc_stk: .res 64
"""


class Gen:
    def __init__(self, funcs):
        self.funcs = {name: line for name, _, line in funcs}
        self.out, self.n, self.depth = [], 0, 0
        self.strings, self.locals, self.calls = [], [], []
        self.fn, self.vars = None, {}

    def ins(self, text):
        self.out.append("        " + text)

    def lab(self, name):
        self.out.append(name + ":")

    def new_label(self, prefix="L"):
        self.n += 1
        return f"{prefix}{self.n}"

    def program(self, funcs):
        if "main" not in self.funcs:
            raise CompileError("no function main")
        self.lab("start")
        self.ins("lda #0")
        self.ins("sta cc_sp")
        self.ins("jsr fn_main")
        self.ins("lda #0")
        self.ins("jmp sys_exit")
        for name, body, line in funcs:
            self.function(name, body, line)
        for name, line in self.calls:
            if name not in self.funcs:
                raise CompileError(f"line {line}: undefined function {name}")
        return "\n".join(self.out) + "\n" + RUNTIME + self.strings_text() + DATA + self.locals_text()

    def function(self, name, body, line):
        self.fn, self.vars = name, {}
        self.lab("fn_" + name)
        for s in body:
            self.stmt(s)
        self.ins("lda #0")
        self.ins("sta acc")
        self.ins("sta acc+1")
        self.ins("rts")

    def strings_text(self):
        return "".join(f"{lbl}: .byte {', '.join(str(b) for b in data + b'\0')}\n"
                       for lbl, data in self.strings)

    def locals_text(self):
        return "".join(f"{lbl}: .res 2\n" for lbl in self.locals)

    def var(self, name, line):
        if name not in self.vars:
            raise CompileError(f"line {line}: undefined variable {name}")
        return self.vars[name]

    def load(self, lbl):
        self.ins(f"lda {lbl}")
        self.ins("sta acc")
        self.ins(f"lda {lbl}+1")
        self.ins("sta acc+1")

    def store(self, lbl):
        self.ins("lda acc")
        self.ins(f"sta {lbl}")
        self.ins("lda acc+1")
        self.ins(f"sta {lbl}+1")

    def stmt(self, s):
        kind = s[0]
        if kind == "decl":
            _, name, init, line = s
            if name in self.vars:
                raise CompileError(f"line {line}: {name} is already declared in {self.fn}")
            lbl = f"v_{self.fn}_{name}"
            if len(lbl) > SYMMAX:
                raise CompileError(f"line {line}: {lbl} is longer than {SYMMAX} characters (as limit)")
            self.vars[name] = lbl
            self.locals.append(lbl)
            if init is not None:
                self.expr(init)
                self.store(lbl)
        elif kind == "assign":
            _, name, value, line = s
            lbl = self.var(name, line)
            self.expr(value)
            self.store(lbl)
        elif kind == "expr":
            self.expr(s[1])
        elif kind == "return":
            if s[1] is None:
                self.ins("lda #0")
                self.ins("sta acc")
                self.ins("sta acc+1")
            else:
                self.expr(s[1])
            self.ins("rts")
        elif kind == "if":
            _, cond, then, other, _line = s
            else_l, end_l = self.new_label(), self.new_label()
            self.test(cond)
            self.ins(f"beq {else_l}")
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
            self.ins(f"beq {end_l}")
            self.stmt(body)
            self.ins(f"jmp {top_l}")
            self.lab(end_l)
        elif kind == "block":
            for x in s[1]:
                self.stmt(x)

    def test(self, cond):
        """Leave acc's truth in the flags: Z set when the condition is false."""
        self.expr(cond)
        self.ins("lda acc")
        self.ins("ora acc+1")

    def expr(self, e):
        kind = e[0]
        if kind == "num":
            v = e[1]
            self.ins(f"lda #{v & 255}")
            self.ins("sta acc")
            self.ins(f"lda #{v >> 8}")
            self.ins("sta acc+1")
        elif kind == "var":
            self.load(self.var(e[1], e[2]))
        elif kind == "str":
            raise CompileError(f"line {e[2]}: a string literal is only an argument to puts")
        elif kind == "call":
            _, name, args, line = e
            if name == "puts":
                self.puts(args, line)
            else:
                if args:
                    raise CompileError(f"line {line}: arguments are not in this slice")
                self.calls.append((name, line))
                self.ins(f"jsr fn_{name}")
        elif kind == "neg":
            self.expr(e[1])
            self.ins("lda #0")
            self.ins("sta tmp")
            self.ins("sta tmp+1")
            self.ins("jsr cc_sub")
        elif kind == "bin":
            _, op, a, b, _line = e
            self.expr(a)
            self.push()
            self.expr(b)
            self.depth -= 1
            self.ins("jsr cc_pop")
            for routine in BINOPS[op]:
                self.ins(f"jsr {routine}")

    def push(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CompileError("expression too deeply nested for the software stack")
        self.ins("jsr cc_push")

    def puts(self, args, line):
        if len(args) != 1 or args[0][0] != "str":
            raise CompileError(f"line {line}: puts takes one string literal")
        lbl = f"s_{len(self.strings) + 1}"
        self.strings.append((lbl, args[0][1]))
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
    "==": ["cc_eq"],
    "!=": ["cc_eq", "cc_not"],
    "<": ["cc_lt"],
    ">": ["cc_swap", "cc_lt"],
    "<=": ["cc_swap", "cc_lt", "cc_not"],
    ">=": ["cc_lt", "cc_not"],
}


def compile_c(src):
    funcs = Parser(lex(src)).program()
    seen = set()
    for name, _, line in funcs:
        if name in seen:
            raise CompileError(f"line {line}: function {name} is defined twice")
        seen.add(name)
    return Gen(funcs).program(funcs)


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
