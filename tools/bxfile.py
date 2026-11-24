"""The compiled BASIC file (BUILD, docs/design/basic.md section 6.1): "BX", 1, the code's length
(2), the variables' size (2), then the code. The code holds no addresses: this walk is the format,
the one bas.c's unreloc() writes and the runner's loader undoes. Every word operand is one of
  code   an offset from the code's start (JUMP, and an LA of a return or loop address)
  var    an offset from the variables' start with bit 15 set (LAW SAW LDV STV, and an LA of a variable)
  ncall  the offset from the first native (rt_mark) of an NCAL's target
  call   the offset from the first bytecode routine (rt_prs) of a CALL's target
An LA of 0 is the NEXT without a variable. This is a reference for the tests, not a tool."""
import struct

LA, CW, CB, CS, BRFLS, BRTRU, BRNCH, NCAL, CALL, LAW, SAW, JUMP, LDV, STV = (
    0x26, 0x2C, 0x2A, 0x2E, 0x4C, 0x4E, 0x50, 0x52, 0x54, 0x6A, 0x7A, 0xC4, 200, 202)
CLASS = {NCAL: "ncall", CALL: "call", LAW: "var", SAW: "var", LDV: "var", STV: "var", JUMP: "code"}


def parse(data):
    """(code length, variables' size, code) of a file; ValueError if it is not one."""
    if data[:3] != b"BX\x01" or len(data) < 7:
        raise ValueError("not a BX 1 file")
    n, v = struct.unpack("<HH", data[3:7])
    if len(data) != 7 + n:
        raise ValueError("length %d, header says %d" % (len(data) - 7, n))
    return n, v, data[7:]


def walk(code):
    """Yield (offset, opcode, class, operand) for each word operand, class as above (an LA is
    "code", "var" or "zero" by its value); raises ValueError on an operand running off the end."""
    i = 0
    while i < len(code):
        op = code[i]
        n = 1
        if op in CLASS or op in (LA, CW):
            n = 3
        elif op in (CB, BRFLS, BRTRU, BRNCH):
            n = 2
        elif op == CS:
            n = 2 + code[i + 1]
        if i + n > len(code):
            raise ValueError("instruction at %d runs past the end" % i)
        if n == 3:
            w = struct.unpack("<H", code[i + 1:i + 3])[0]
            cls = CLASS.get(op)
            if op == LA:
                cls = "zero" if w == 0 else "var" if w & 0x8000 else "code"
            if cls:
                yield i, op, cls, w
        i += n
