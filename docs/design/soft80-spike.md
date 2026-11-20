# Soft 80 columns: spike (2026-11-20)

Question: can Breadbin have a software 80-column text mode on a stock C64, and which known techniques should it use? Spike only: nothing was assembled or run for this note. Every number marked *est.* is computed from the 6502 cycle tables, not measured. This refines the one-line row `[D20]` in `docs/design/research/next/D-console-cooler.md`.

## Verdict

Feasible on every platform tier, as a loadable module, not in the base kernel. The technique is settled and two independent implementations (ACE, Novaterm) converged on it:

- **Hires bitmap, 320x200, 4x8-pixel cells**, 80x25 characters.
- **One font table with each glyph stored in both nibbles of every byte** (2 KB for 256 glyphs). Drawing the left character is `(font & $F0) | (screen & $0F)`, the right one `(font & $0F) | (screen & $F0)`: no shifting, no glyph cache.
- Colour is **per 8x8 cell, so per pair of characters** (the hires colour matrix); there is no true per-character colour.

Costs for us: about **32 pool pages** (the bitmap), 8 for the font, a page or two of code. Scrolling is the weak spot (about 100 ms per line on a stock machine, *est.*; about 16 ms with an REU). Two kernel changes are needed first: a console output vector and a geometry query (D3). Gate on the IEC stall work (see Risks).

## Survey

| Source | What it is | Licence / adoptable? | Technique worth taking |
|---|---|---|---|
| **ACE-64 `acesoft80.s`** | 6510 driver of Craig Bruce's ACE OS; read in full | `ace16.txt` (same directory as the source) says "This system is Public Domain Software." Adoptable; record the source and author in the file header | pair-aligned `put` (odd leading right char, even body in whole bytes, odd trailing left char); char backing store; XOR masks for reverse; underline flag; IRQ cursor; REU as memmove for scroll and fill; screen-save blank |
| **Novaterm 9.6** `80col.default`, `80col.fast-REU`, `font80.*`, `font81.*` | Terminal program's loadable drivers (1.8 KB each) plus fonts; disassembled, not fully traced | "public domain release" per the task brief; the disk carries no licence file, so the evidence is the release notice at the download site. Confirm before adopting | same nibble-mask font; row high-water array so clears and scrolls only touch used cells; same stock zero page as us (`$D1/$D2` row pointer, `$D3` column, `$D6` row, `$C7` reverse); swappable fonts as 2 KB files |
| **Screen-80** (Compute's Gazette, Sep 1984) | Magazine type-in, about 3 KB, hooks CHROUT; read from the article and the disk image, only partly disassembled | Copyrighted magazine listing: **not adoptable**, ideas only | hires screen at `$E000` under the KERNAL; one colour for the whole screen (what you get without a matrix); `Custom-80` joystick font editor is a good font-tool idea |
| **Color80** (Richvale, 1983) | Commercial product, the copy in the brief is a crack ("broken by Mr. Unprotector") | **Proprietary: do not copy, do not adopt.** Not studied beyond the loader (`$01=$34`, copies code to `$A000`) | per-character colour is its selling point; it needs a different layout (not traced). Out of scope |
| **SOFT80** (Lampton, 1984, CP/M) | 6510 side of a CP/M cartridge patch; docs read, binary only glanced at | "unlimited **non-commercial** distribution": **not compatible with an MIT repo**, ideas only | VIC bank 3: bitmap at `$E000`, colour matrix at `$D000`, code at `$D400`, all RAM under ROM and I/O; ESC sequences for cursor/colour/underline |

What I verified myself: in `font80.novaterm` all 2,048 data bytes have equal nibbles (the blit is mask-and-merge, `lda (font),y; and $CF`, with `$CF` = `$F0` or `$0F`); ACE's left/right echo routines use the same two masks; Novaterm's cursor XORs the same mask into pixel row 7 (an underline); `$D018 = $3C` selects the colour matrix and bitmap. Not traced: how Novaterm's fast-REU variant scrolls, and how its scroll routine is built.

## Techniques: adopt, adapt, skip

**Adopt**
1. **Doubled-nibble font and mask-merge blit.** Fastest per-character path without a precomputed shift table. Font as 8 page-aligned planes (`font_k[256]`, one per pixel row) lets an unrolled blit use `lda (cell),y / and #$0F / ora font_k,x / sta (cell),y` (about 19 cycles a row, about 150-200 per character with overhead, *est.*, 5-6 k characters per second).
2. **Pair-aligned string output** (ACE): an aligned pair is written without reading the bitmap, `font[L] & $F0 | font[R] & $0F`. Use it for `con_write` runs and `clear`.
3. **XOR masks for reverse, cursor and underline**: precompute `$00` or `$F0/$0F/$FF` once per put. Cursor blink from the tick (we already have `con_cursor_tick`) toggles mask bits in pixel rows.
4. **Zero-fill fast path for blanks** (clear, erase to end of line): no font reads, no per-row merge.
5. **Per-row high-water mark** (Novaterm) so `clear` and scroll skip cells that were never coloured.
6. **REU DMA as the scroll engine** when an REU is probed (ACE: stash then fetch, about 2 x 7.7k cycles for 7,680 bytes, *est.*; about 16 ms). Features by probing, as the tiers require.

**Adapt**
- **Backing store of characters (2,000 bytes).** ACE keeps one. It gives `$D1/$D2` a real meaning (start of the cursor row in a char array) which keeps the zero-page rule, lets redraw and font swaps work, and is what lets us defer scrolling. Cost 8 pool pages. Decide after a first measurement; the base design works without it.
- **Deferred scroll.** With a backing store, a burst of line feeds shifts the char array and the bitmap once (the pass costs about the same whatever the line count), not once per line. Likely the largest practical speedup on a stock machine; adds state, so a second step.
- **Colour matrix.** Two characters share one colour byte. Take the text colour from the global colour (`$0286`, as `scr_color` does), keep `ESC C` working for the whole screen only, and drop per-cell colour. Matches how the 40-column console works today.

**Skip**
- Per-character colour (Color80): needs more memory and cycles for little use.
- SuperCPU mirroring paths, the graphics-op API, mouse bounds (ACE is a windowing system; we want a console).
- A bank-3 layout (ACE, SOFT80): our kernel owns `$A300-$FAEF`, so there is no free 8 KB-aligned block there (below).

## Fit with Breadbin

**VIC memory.** Bank 3 and the RAM under the KERNAL are taken (`src/kernel.cfg`). Bank 0 works:

| Piece | Address | Cost |
|---|---|---|
| colour matrix | `$0400` (today's text screen) | 0 pool pages; the 40-column text screen is lost on entry, so keep a copy (4 pages or the REU) |
| bitmap | `$2000-$3F3F` | 32 pool pages, claimed |
| `$D018` | `$18` (matrix `$0400`, bitmap `$2000`) | none |
| font | anywhere the CPU can reach | 8 pages (or 4 with a one-nibble font plus a shift per glyph) |

Bank 0 leaves `$DD00` bits 0-1 at their stock value. I checked `src/kernel/iec.s`: `io_atn_begin` reads `PORT & $07` into `io_base` and every bus write ORs it back, so the VIC bank and RS-232 bits are preserved, and a bank other than 0 would also be safe. Pool: 155 pages become about 115 (about 29 KB) while the mode is on, so programs that need more must refuse or the mode must be off. A page claim (D9) is therefore a prerequisite: the bitmap needs fixed pages.

**Console hook.** `con_write` (`src/kernel/con.s:587`) calls `con_putc`, which calls `scr_put`, `scr_nl`, `scr_clear`, `scr_bs` and `scr_scroll`, all of which write `SCREEN` directly, hard-code 40 and 25, and keep `$D1-$D3`, `$D6`, `$C7`. For a module the smallest hook is one indirect jump at the top of `con_putc` (about 6 bytes, plus the cursor tick). Kernel room: 1,271 bytes below `$CF00`, 1,290 in `KHI` (`make size`), so the hook fits; the driver does not and should not. The module system already loads pool pages top-down and allows `init`/`fini` (`docs/design/next/modules-v1.md`), but the char-device class is unused ("only 0 is used by v1"). A `/lib/km/con80` is the right owner.

**Programs.** `edit`, `more` and the shell hard-code 24/39/22/40 (D3). The shell's line buffer is already 80 bytes (`LBMAX = 79`). D3 (a geometry query) is a prerequisite for anything to benefit.

**Rough numbers** (est.; the repo's own `scr_scroll` comment gives 13,400 cycles for the 960-byte text scroll, which these scale from):

| Operation | 40-col text today | 80-col soft |
|---|---|---|
| one character | about 30 cycles | about 150-250 |
| scroll one line | about 13.4k cycles | about 107k (14 cycles per byte x 7,680), about 70k unrolled, about 16k with an REU |
| clear screen | 1,000 bytes | 8,000 + 1,000 bytes |

A scrolling full-speed listing runs at about 8-9 lines per second on a stock machine. Fine for `cat`, `ls` and a terminal at 1200 baud, slow for `cat` of a long file; that is where deferred scroll earns its place.

## Risks and unknowns

- **IEC timing.** The JiffyDOS windows (`jif_safe`: no bad lines, no sprites) and the open physical-1541 stall work (`docs/wip.md`) both depend on VIC state. A bitmap screen has the same bad-line pattern as text, but it is a VIC change on the same bus; D19's rule applies: do this after the stall is understood, and run the disk and bus tests with the mode on.
- **Legibility.** A 4x8 cell leaves a 3x5 or 3x7 glyph. Composite and CRT shows it badly; on the Ultimate's HDMI it is usable. Needs a look on real hardware, not assumed.
- **Font source.** Not decided. Options: an ACE or Novaterm font (both stated public domain; check the licence evidence before adopting), or draw our own to include `{ } ~ \ | ^ _` for the S14 compiler (D17). Never derive it from the character ROM (repo rule).
- **Bitmap read-back.** Reading a glyph back from the bitmap is not needed with a backing store; without one `edit`'s screen restore would be impossible, a third reason to weigh the 8 pages.
- **Not checked:** the REU scroll numbers (est.); whether the cursor flicker at 50 Hz is visible; Screen-80's and Color80's internals beyond what is above.

## Suggested next steps

1. **Host proof**, no hardware: a script in `tools/` that renders a text file through a candidate font and the nibble-merge algorithm to a PNG, so we can judge the font and the cell shape. Cheap, and it settles the font question.
2. **D3 + D9 first** (geometry query, page claim); they are useful on their own and the soft-80 module needs both.
3. **`con80` module in VICE**: blit, cursor, scroll without an REU. Measure cycles with the host tools, then decide on the backing store and deferred scroll.
4. **REU scroll** behind a probe, and a hardware run (legibility, IEC with the mode on) once the stall is closed.

Sources: ACE `acesoft80.s` and `ace16.txt` (csbruce.com archive); Compute's Gazette, Sep 1984, "80 Columns For The 64" and its disk image; SOFT80.txt and SOFT80.com, Color80, the same set on mikenaberezny.com; Novaterm 9.6C (zimmers.net).
