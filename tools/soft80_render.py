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


def load_font(path):
    with open(path, "rb") as f:
        d = f.read()
    if len(d) == 2050:
        d = d[2:]
    if len(d) != 2048:
        raise ValueError(f"font must be 2048 bytes (or 2050 with load address), got {len(d)}")
    if any((b >> 4) != (b & 15) for b in d):
        raise ValueError("font is not doubled-nibble (high nibble != low nibble)")
    return d


def screen_code(ch):
    """ASCII -> C64 screen code (letters lower/upper set; reverse = +128)."""
    o = ord(ch)
    if 0x40 <= o <= 0x5F:
        return o - 0x40          # @A-Z[\]^_  -> 0-31
    if 0x60 <= o <= 0x7F:
        return o - 0x60 + 0x40   # `a-z{|}~   -> 64-95 (our 6502 table would differ)
    return o                     # 0x20-0x3F identical


class Soft80:
    def __init__(self, font, fg=1, bg=6):
        self.font = font
        self.bitmap = bytearray(8000)
        self.colour = bytes([(fg << 4) | bg]) * 1000
        self.fg, self.bg = fg, bg
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

    def put_pair(self, col, row, left, right):
        """Two chars filling one cell: whole-byte writes, no read."""
        assert col % 2 == 0
        base = self.cell(col, row)
        for i in range(8):
            self.bitmap[base + i] = (self.font[left * 8 + i] & 0xF0) | (self.font[right * 8 + i] & 0x0F)
        self.writes += 8
        self.lastpos[row] = max(self.lastpos[row], col + 2)

    def put_string(self, col, row, codes):
        """Pair-aligned put: odd leading char, whole pairs, odd trailing char."""
        i = 0
        if col % 2 and codes:
            self.put(col, row, codes[0]); col += 1; i = 1
        while len(codes) - i >= 2:
            self.put_pair(col, row, codes[i], codes[i + 1]); col += 2; i += 2
        if i < len(codes):
            self.put(col, row, codes[i])

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

    def clear_row(self, r):
        nbytes = (self.lastpos[r] + 1) // 2 * 8
        b = self.cell(0, r)
        self.bitmap[b:b + nbytes] = bytes(nbytes)
        self.writes += nbytes
        self.lastpos[r] = 0

    # -- terminal -----------------------------------------------------------
    def write(self, text):
        """Console write with look-ahead: runs of text on a row go out as one
        put_string; LFs waiting at the bottom scroll in one pass."""
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "\n":
                i += 1
                self.cx = 0
                if self.cy == ROWS - 1:
                    n = 1
                    while i < len(text) and text[i] == "\n":
                        n += 1; i += 1
                    self.scroll_up(min(n, ROWS - 1))
                else:
                    self.cy += 1
                continue
            j = i
            while j < len(text) and text[j] != "\n" and j - i < COLS - self.cx:
                j += 1
            self.put_string(self.cx, self.cy, [screen_code(c) for c in text[i:j]])
            self.cx += j - i
            i = j
            if self.cx == COLS:
                self.cx = 0
                if self.cy == ROWS - 1:
                    self.scroll_up(1)
                else:
                    self.cy += 1

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
