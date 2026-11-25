#!/usr/bin/env python3
"""Host model of a soft 80-column console: hires bitmap, 4x8 glyphs.

    python3 tools/soft80_render.py FONT [-o out.png] [--fg 1] [--bg 6] [--scale 3] [TEXTFILE]

FONT is a doubled-nibble font: 256 glyphs x 8 bytes, screen-code order, each
glyph's 4 pixel columns stored in both nibbles of every byte (2048 bytes; a
2050-byte file with a 2-byte load address is accepted). TEXTFILE (default:
stdin) is ASCII, 80 columns, `\\n` = newline, scrolled like a terminal.

The model is the algorithm a 6502 driver would run, not a picture of it:
  * bitmap is 8000 bytes in VIC cell order (40 x 25 cells, 8 bytes each);
    column c lives in cell c//2, left char in the high nibble's pixels;
  * a char write is  byte = (glyph & mask) | (byte & ~mask)  with mask $F0
    (even column) or $0F (odd column): one read-modify-write per row;
  * a pair of chars landing on one cell writes whole bytes, no read
    (pair-aligned put, after ACE acesoft80.s);
  * scroll copies only up to each row's high-water mark (after Novaterm).
Every operation counts bytes read and written, so a design can be priced
before any 6502 is written. Colour is one fg/bg for the whole screen here
(the colour matrix is per 8x8 cell, so two chars share it).
"""
import argparse
import sys

COLS, ROWS = 80, 25
PALETTE = [  # Pepto's C64 palette
    (0x00, 0x00, 0x00), (0xFF, 0xFF, 0xFF), (0x68, 0x37, 0x2B), (0x70, 0xA4, 0xB2),
    (0x6F, 0x3D, 0x86), (0x58, 0x8D, 0x43), (0x35, 0x28, 0x79), (0xB8, 0xC7, 0x6F),
    (0x6F, 0x4F, 0x25), (0x43, 0x39, 0x00), (0x9A, 0x67, 0x59), (0x44, 0x44, 0x44),
    (0x6C, 0x6C, 0x6C), (0x9A, 0xD2, 0x84), (0x6C, 0x5E, 0xB5), (0x95, 0x95, 0x95),
]


def load_font(path, kernel=True):
    with open(path, "rb") as f:
        d = f.read()
    if len(d) == 2050:
        d = d[2:]
    if len(d) != 2048:
        raise ValueError(f"font must be 2048 bytes (or 2050 with load address), got {len(d)}")
    if any((b >> 4) != (b & 15) for b in d):
        raise ValueError("font is not doubled-nibble (high nibble != low nibble)")
    return kernel_order(d) if kernel else d


def screen_code(ch):
    """ASCII -> Breadbin screen code (con.s to_screen: the lowercase set, a-z = 1-26).
    None where the console prints nothing."""
    o = ord(ch)
    if o < 0x20:
        return None
    if o < 0x40 or 0x41 <= o <= 0x5A:
        return o                 # digits, punctuation, A-Z (0x41-0x5A)
    if o == 0x40:
        return 0
    if o < 0x5F:
        return o - 0x40          # [ \ ] ^
    if o == 0x5F:
        return 0x64              # _
    if o == 0x60:
        return None
    if o <= 0x7A:
        return o - 0x60          # a-z
    if 0x7B <= o <= 0x7E:
        return o - 0x16          # { | } ~ : the glyphs $65-$68 (sc80 in con80.inc)
    return 0x3F                  # the rest


def kernel_order(font):
    """Novaterm-style fonts hold graphics at 1-26, lowercase at 0x41-0x5A and capitals at
    0x61-0x7A; the kernel's screen codes want lowercase at 1-26 and capitals at 0x41-0x5A
    (what to_screen returns). Rotate the three blocks; graphics go to 0x61."""
    f = bytearray(font)
    for c in range(1, 27):
        f[c * 8:c * 8 + 8] = font[(c + 0x40) * 8:(c + 0x40) * 8 + 8]
        f[(c + 0x40) * 8:(c + 0x40) * 8 + 8] = font[(c + 0x60) * 8:(c + 0x60) * 8 + 8]
        f[(c + 0x60) * 8:(c + 0x60) * 8 + 8] = font[c * 8:c * 8 + 8]
    return bytes(f)


NGLYPH = 105                     # screen codes 0-$68: to_screen's 0-$64 and sc80's $65-$68


def glyphs(font):
    """The 6502 driver's font: the first NGLYPH glyphs in code order, 4 bytes each: byte j holds
    row j in the high nibble and row j+4 in the low (the doubled-nibble input has one nibble a row)."""
    out = bytearray()
    for c in range(NGLYPH):
        g = font[c * 8:c * 8 + 8]
        out += bytes((g[j] & 0xF0) | (g[j + 4] & 0x0F) for j in range(4))
    return bytes(out)


def unglyphs(packed):
    """Inverse of glyphs(): NGLYPH * 4 bytes -> NGLYPH * 8 doubled-nibble bytes."""
    out = bytearray()
    for c in range(NGLYPH):
        g = packed[c * 4:c * 4 + 4]
        out += bytes((b & 0xF0) | (b >> 4) for b in g) + bytes((b << 4 & 0xF0) | (b & 0x0F) for b in g)
    return bytes(out)


class Soft80:
    def __init__(self, font, fg=1, bg=6):
        self.font = font
        self.bitmap = bytearray(8000)
        self.colour = bytes([(fg << 4) | bg]) * 1000
        self.fg, self.bg, self.border = fg, bg, 0
        self.rev = 0                   # $C7: nonzero = reverse video
        self.esc = 0                   # escape sequence state (con.s esc_st)
        self.erow = 0
        self.cur = 0                   # cursor drawn
        self.lastpos = [0] * ROWS      # per row: columns drawn (high-water mark)
        self.cx = self.cy = 0
        self.reads = self.writes = 0   # bitmap bytes touched

    # -- primitives ---------------------------------------------------------
    @staticmethod
    def cell(col, row):
        return (row * 40 + col // 2) * 8

    def put(self, col, row, code, reverse=False):
        """Single char: read-modify-write 8 bytes (what the 6502 does)."""
        mask = 0xF0 if col % 2 == 0 else 0x0F
        base, g = self.cell(col, row), code * 8
        for i in range(8):
            gb = self.font[g + i] ^ (0xFF if reverse else 0)
            self.bitmap[base + i] = (gb & mask) | (self.bitmap[base + i] & ~mask & 0xFF)
        self.reads += 8
        self.writes += 8
        self.lastpos[row] = max(self.lastpos[row], col + 1)

    def put_pair(self, col, row, left, right, reverse=False):
        """Two chars filling one cell: whole-byte writes, no read."""
        assert col % 2 == 0
        base = self.cell(col, row)
        for i in range(8):
            self.bitmap[base + i] = ((self.font[left * 8 + i] & 0xF0) | (self.font[right * 8 + i] & 0x0F)) \
                ^ (0xFF if reverse else 0)
        self.writes += 8
        self.lastpos[row] = max(self.lastpos[row], col + 2)

    def put_string(self, col, row, codes):
        """Pair-aligned put: odd leading char, whole pairs, odd trailing char."""
        i = 0
        if col % 2 and codes:
            self.put(col, row, codes[0], self.rev); col += 1; i = 1
        while len(codes) - i >= 2:
            self.put_pair(col, row, codes[i], codes[i + 1], self.rev); col += 2; i += 2
        if i < len(codes):
            self.put(col, row, codes[i], self.rev)

    def scroll_up(self, n=1):
        """Move rows up n; copy each row only to max(src, dst) high-water mark."""
        for r in range(ROWS - n):
            width = max(self.lastpos[r + n], self.lastpos[r])
            nbytes = (width + 1) // 2 * 8
            s, d = self.cell(0, r + n), self.cell(0, r)
            self.bitmap[d:d + nbytes] = self.bitmap[s:s + nbytes]
            self.reads += nbytes
            self.writes += nbytes
            # beyond dst's old mark we never wrote; src's tail is blank by invariant
            self.lastpos[r] = self.lastpos[r + n]
        for r in range(ROWS - n, ROWS):
            self.clear_row(r)

    def clear(self):
        self.bitmap[:] = bytes(8000)
        self.lastpos = [0] * ROWS
        self.cx = self.cy = 0
        self.rev = 0
        self.writes += 8000

    def clear_row(self, r):
        nbytes = (self.lastpos[r] + 1) // 2 * 8
        b = self.cell(0, r)
        self.bitmap[b:b + nbytes] = bytes(nbytes)
        self.writes += nbytes
        self.lastpos[r] = 0

    # -- terminal -----------------------------------------------------------
    def advance(self, rest):
        """Next line. At the bottom, scroll for every LF still waiting in `rest` too
        (up to 24, within 255 bytes, stopping at FF or ESC): the blank rows are made in one
        pass and the following LFs just move the cursor down (Novaterm's look-ahead)."""
        self.cx = 0
        if self.cy < ROWS - 1:
            self.cy += 1
            return
        n = 1
        for ch in rest[:255]:
            if ch in "\f\x1b\b":
                break
            if ch == "\n":
                n += 1
                if n == ROWS - 1:
                    break
        self.scroll_up(n)
        self.cy = ROWS - n

    def cursor(self):
        """Toggle the cursor: XOR the half cell at (cx, cy) (the 6502's tog)."""
        mask = 0xF0 if self.cx % 2 == 0 else 0x0F
        base = self.cell(self.cx, self.cy)
        for i in range(8):
            self.bitmap[base + i] ^= mask
        self.cur ^= 1

    def blank_half(self, col, row):
        mask = 0x0F if col % 2 == 0 else 0xF0      # the bits kept
        base = self.cell(col, row)
        for i in range(8):
            self.bitmap[base + i] &= mask

    def bs(self):
        if self.cx == 0:
            if self.cy == 0:
                return
            self.cy -= 1
            self.cx = COLS
        self.cx -= 1
        self.blank_half(self.cx, self.cy)

    def eol(self):
        """ESC K: blank from the cursor to the end of the row."""
        if self.lastpos[self.cy] <= self.cx:
            return
        for c in range(self.cx, COLS):
            self.blank_half(c, self.cy)
        self.lastpos[self.cy] = self.cx

    def recolour(self):
        self.colour = bytes([(self.fg << 4) | (self.bg & 15)]) * 1000

    def escape(self, ch):
        """One byte of an escape sequence (con.s con_escape; 80 columns, bitmap colours)."""
        st, v = self.esc, ord(ch)
        if st == 1:
            self.esc = 0
            if ch == "=":
                self.esc = 2
            elif ch == "R":
                self.rev = 0x12
            elif ch == "r":
                self.rev = 0
            elif ch == "C":
                self.esc = 4
            elif ch == "K":
                self.eol()
            return
        v = (v - 32) & 255
        self.esc = st + 1
        if st == 2:
            self.erow = v
        elif st == 3:
            self.esc = 0
            self.cx, self.cy = min(v, COLS - 1), min(self.erow, ROWS - 1)
        elif st == 4:
            self.fg = v & 15
            self.recolour()
        elif st == 5:
            self.bg = v
            self.recolour()
        else:
            self.esc = 0
            self.border = v

    def write(self, text):
        """Console write: runs of text on a row go out as one put_string; a scroll looks
        ahead in the buffer (advance). The cursor is hidden first and stays hidden."""
        if self.cur:
            self.cursor()
        i = 0
        while i < len(text):
            ch = text[i]
            if self.esc:
                self.escape(ch); i += 1
                continue
            if ch == "\x1b":
                self.esc = 1; i += 1
                continue
            if ch == "\f":
                self.clear(); i += 1
                continue
            if ch == "\b":
                self.bs(); i += 1
                continue
            if ch != "\n" and ch != "\t" and ord(ch) < 0x20:
                i += 1                 # other controls: ignored
                continue
            if ch == "\n":
                i += 1
                self.rev = 0
                self.advance(text[i:])
                continue
            j, codes = i, []
            while j < len(text) and (text[j] == "\t" or ord(text[j]) >= 0x20) and len(codes) < COLS - self.cx:
                c = screen_code(" " if text[j] == "\t" else text[j])
                if c is not None:
                    codes.append(c)
                j += 1
            self.put_string(self.cx, self.cy, codes)
            self.cx += len(codes)
            i = j
            if self.cx == COLS:
                self.advance(text[i:])

    # -- output -------------------------------------------------------------
    def pixel(self, x, y):
        b = self.bitmap[((y // 8) * 40 + x // 8) * 8 + y % 8]
        return (b >> (7 - x % 8)) & 1

    def to_png(self, path, scale=3):
        from PIL import Image
        img = Image.new("RGB", (320, 200))
        fg, bg = PALETTE[self.fg], PALETTE[self.bg]
        img.putdata([fg if self.pixel(x, y) else bg for y in range(200) for x in range(320)])
        img.resize((320 * scale, 200 * scale), Image.NEAREST).save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("font")
    ap.add_argument("textfile", nargs="?")
    ap.add_argument("-o", "--out", default="soft80.png")
    ap.add_argument("--fg", type=int, default=1)
    ap.add_argument("--bg", type=int, default=6)
    ap.add_argument("--scale", type=int, default=3)
    a = ap.parse_args()
    if a.textfile:
        with open(a.textfile) as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    s = Soft80(load_font(a.font), a.fg, a.bg)
    s.write(text)
    s.to_png(a.out, a.scale)
    print(f"{a.out}: {s.reads} bitmap bytes read, {s.writes} written")


if __name__ == "__main__":
    main()
