#!/usr/bin/env python3
"""Generate sweep.s: every stable undocumented NMOS 6510 opcode in every addressing mode,
several input vectors each, against a software model (this file). One record per case; the
6502 runner (in the generated file) executes each op from a RAM trampoline and compares A, X,
Y, N V Z C and both data cells with the model's answer.
usage: gen_sweep.py OUT.s OUT.json     (json: case id -> description, for decoding failures)
Model = the standard documented behaviour of the stable ops in binary mode (D clear)."""
import json, random, sys

DZ, DA = 0xFA, 0xC100            # the data cell: zero page / absolute
IVS = (0x0F, 0xA5, 0xF3)         # index register values (high bit and wrap coverage)
PTRX = (0xE0, 0xE2, 0xE4)        # (zp,X): the pointer cell for IVS[k] is PTRX[k]
PTRY = (0xE8, 0xEA, 0xEC)        # (zp),Y: the pointer cell holds DA - IVS[k]

def nz(p, v):
    p &= ~0x82
    return p | (v & 0x80) | (0x02 if v == 0 else 0)

def adc(a, m, c, p):
    s = a + m + c
    r = s & 255
    v = (~(a ^ m) & (a ^ r) & 0x80) != 0
    p = (p & ~0x41) | (1 if s > 255 else 0) | (0x40 if v else 0)
    return r, nz(p, r)

def op_model(name, a, x, y, c, m, p):
    """-> a, x, y, p, m' (None: memory untouched). p: N V Z C bits as in $C3 mask."""
    cm = lambda p, c: (p & ~1) | c
    if name == "SLO":
        c2 = m >> 7; m = (m << 1) & 255; a |= m; return a, x, y, nz(cm(p, c2), a), m
    if name == "RLA":
        c2 = m >> 7; m = ((m << 1) | c) & 255; a &= m; return a, x, y, nz(cm(p, c2), a), m
    if name == "SRE":
        c2 = m & 1; m >>= 1; a ^= m; return a, x, y, nz(cm(p, c2), a), m
    if name == "RRA":
        c2 = m & 1; m = (m >> 1) | (c << 7); a, p = adc(a, m, c2, p); return a, x, y, p, m
    if name == "DCP":
        m = (m - 1) & 255; p = cm(p, 1 if a >= m else 0); return a, x, y, nz(p, (a - m) & 255), m
    if name == "ISC":
        m = (m + 1) & 255; a, p = adc(a, m ^ 255, c, p); return a, x, y, p, m
    if name == "SAX":
        return a, x, y, p, a & x
    if name == "LAX":
        return m, m, y, nz(p, m), None
    if name == "ANC":
        a &= m; p = nz(p, a); return a, x, y, cm(p, a >> 7), None
    if name == "ALR":
        a &= m; p = cm(p, a & 1); a >>= 1; return a, x, y, nz(p, a), None
    if name == "ARR":
        a = ((a & m) >> 1) | (c << 7)
        b6, b5 = (a >> 6) & 1, (a >> 5) & 1
        p = (p & ~0x41) | b6 | (0x40 if b6 ^ b5 else 0)
        return a, x, y, nz(p, a), None
    if name == "SBX":
        t = a & x; p = cm(p, 1 if t >= m else 0); x = (t - m) & 255; return a, x, y, nz(p, x), None
    if name == "SBC2":
        a, p = adc(a, m ^ 255, c, p); return a, x, y, p, None
    if name.startswith("NOP"):
        return a, x, y, p, None
    raise KeyError(name)

# mode -> (operand builder(iv_index) -> bytes, index register or None, cell checked)
MODES = ("zp", "zpx", "zpy", "abs", "absx", "absy", "indx", "indy", "imm", "imp")
def operand(mode, k):
    iv = IVS[k]
    return {"zp": [DZ], "zpx": [(DZ - iv) & 255], "zpy": [(DZ - iv) & 255],
            "abs": [DA & 255, DA >> 8], "absx": [(DA - iv) & 255, (DA - iv) >> 8],
            "absy": [(DA - iv) & 255, (DA - iv) >> 8], "indx": [(PTRX[k] - iv) & 255],
            "indy": [PTRY[k]], "imm": [], "imp": []}[mode]
def cell(mode):          # which data cell the op touches
    return "z" if mode in ("zp", "zpx", "zpy") else "a" if mode not in ("imm", "imp") else None
IDX = {"zpx": "x", "absx": "x", "indx": "x", "zpy": "y", "absy": "y", "indy": "y"}

OPS = []   # (name, mode, opcode)
def add(name, base, modes):
    for mode, opc in zip(("zp", "zpx", "abs", "absx", "absy", "indx", "indy"), modes):
        if opc is not None: OPS.append((name, mode, opc))
for name, ops in (("SLO", (0x07, 0x17, 0x0F, 0x1F, 0x1B, 0x03, 0x13)), ("RLA", (0x27, 0x37, 0x2F, 0x3F, 0x3B, 0x23, 0x33)),
                  ("SRE", (0x47, 0x57, 0x4F, 0x5F, 0x5B, 0x43, 0x53)), ("RRA", (0x67, 0x77, 0x6F, 0x7F, 0x7B, 0x63, 0x73)),
                  ("DCP", (0xC7, 0xD7, 0xCF, 0xDF, 0xDB, 0xC3, 0xD3)), ("ISC", (0xE7, 0xF7, 0xEF, 0xFF, 0xFB, 0xE3, 0xF3))):
    add(name, 0, ops)
OPS += [("SAX", "zp", 0x87), ("SAX", "zpy", 0x97), ("SAX", "abs", 0x8F), ("SAX", "indx", 0x83),
        ("LAX", "zp", 0xA7), ("LAX", "zpy", 0xB7), ("LAX", "abs", 0xAF), ("LAX", "absy", 0xBF), ("LAX", "indx", 0xA3), ("LAX", "indy", 0xB3),
        ("ANC", "imm", 0x0B), ("ANC", "imm", 0x2B), ("ALR", "imm", 0x4B), ("ARR", "imm", 0x6B), ("SBX", "imm", 0xCB), ("SBC2", "imm", 0xEB)]
OPS += [("NOP", "imp", o) for o in (0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA)]
OPS += [("NOP", "imm", o) for o in (0x80, 0x82, 0x89, 0xC2, 0xE2)]
OPS += [("NOP", "zp", o) for o in (0x04, 0x44, 0x64)]
OPS += [("NOP", "zpx", o) for o in (0x14, 0x34, 0x54, 0x74, 0xD4, 0xF4)]
OPS += [("NOP", "abs", 0x0C)] + [("NOP", "absx", o) for o in (0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC)]

rng = random.Random(6510)
EDGE_M = (0x00, 0x01, 0x7F, 0x80, 0xFF)
def vectors(name, mode, n):
    """n input vectors (a, x, y, c, m); every carry and the edge memory values appear."""
    out = []
    for i in range(n):
        v = dict(a=rng.randrange(256), x=rng.randrange(256), y=rng.randrange(256), c=i & 1,
                 m=EDGE_M[i % 5] if i < 10 else rng.randrange(256), k=i % 3)
        if i == 2: v["a"] = 0x50; v["m"] = 0x50          # ADC overflow
        if i == 5: v["a"] = 0x80; v["m"] = 0x7F
        if i == 7: v["a"] = 0x00
        out.append(v)
    return out

cases, recs = [], []
for name, mode, opc in OPS:
    nvec = 2 if name == "NOP" else 12 if name in ("ARR", "SBX", "SBC2", "ANC", "ALR") else 10
    for v in vectors(name, mode, nvec):
        k = v["k"]; a, x, y, c, m = v["a"], v["x"], v["y"], v["c"], v["m"]
        if mode in IDX:
            if IDX[mode] == "x": x = IVS[k]
            else: y = IVS[k]
        opb = [opc] + operand(mode, k)
        if mode == "imm": opb.append(m)          # the immediate IS the data
        p0 = nz(c, a)
        ea, ex, ey, ep, em = op_model(name, a, x, y, c, m, p0)
        ez = ea_ = m
        if em is not None:
            if cell(mode) == "z": ez = em
            else: ea_ = em
        recs.append([len(opb)] + (opb + [0, 0, 0])[:3] + [a, x, y, c, m, ea, ex, ey, ep & 0xC3, ez, ea_])
        cases.append(f"{name} {mode} op={opc:02X} a={a:02X} x={x:02X} y={y:02X} c={c} m={m:02X} -> a={ea:02X} x={ex:02X} y={ey:02X} p={ep & 0xC3:02X} dz={ez:02X} da={ea_:02X}")

# record layout (15 bytes): len, op0, op1, op2, A, X, Y, C, M, eA, eX, eY, eP, eZ, eAbs
rows = recs
for r in rows: assert len(r) == 15, r

with open(sys.argv[1], "w") as f:
    f.write(open(__file__.replace("gen_sweep.py", "sweep_runner.inc")).read().replace("@NCASES@", str(len(rows))).replace(
        "@INIT@", "".join(f"        lda #${DA & 255:02x}\n        sta ${PTRX[k]:02x}\n        lda #${DA >> 8:02x}\n        sta ${PTRX[k] + 1:02x}\n"
                          f"        lda #${(DA - IVS[k]) & 255:02x}\n        sta ${PTRY[k]:02x}\n        lda #${(DA - IVS[k]) >> 8:02x}\n        sta ${PTRY[k] + 1:02x}\n" for k in range(3))))
    f.write("\nrecs:\n")
    for r in rows: f.write("        .byte " + ",".join(f"${b:02x}" for b in r) + "\n")
    f.write("        .byte 0\n")
json.dump(cases, open(sys.argv[2], "w"), indent=0)
print(len(rows), "cases")
