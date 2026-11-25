# Soft 80 columns: spike (2026-11-20)

Question: can Breadbin have a software 80-column text mode on a stock C64, and which known techniques should it use? Spike only: nothing was assembled or run for this note. Every number marked *est.* is computed from the 6502 cycle tables, not measured. This refines the one-line row `[D20]` in `docs/design/research/next/D-console-cooler.md`.

## Verdict

Feasible on every platform tier, as a loadable module, not in the base kernel. The technique is settled and two independent implementations (ACE, Novaterm) converged on it:

- **Hires bitmap, 320x200, 4x8-pixel cells**, 80x25 characters.
- **One font table with each glyph stored in both nibbles of every byte** (2 KB for 256 glyphs). Drawing the left character is `(font & $F0) | (screen & $0F)`, the right one `(font & $0F) | (screen & $F0)`: no shifting, no glyph cache.
- Colour is **per 8x8 cell, so per pair of characters** (the hires colour matrix); there is no true per-character colour.

Costs for us: about **32 pool pages** (the bitmap), 8 for the font, a page or two of code. Scrolling is the weak spot (about 100 ms per line on a stock machine, *est.*; about 16 ms with an REU). Two kernel changes are needed first: a console output vector and a geometry query (D3). Nothing else gates it: the physical-1541 stall is closed (harness DMA, 2026-11-18), so VIC and raster tricks are fair game.

## Survey

| Source | What it is | Licence / adoptable? | Technique worth taking |
|---|---|---|---|
| **ACE-64 `acesoft80.s`** | 6510 driver of Craig Bruce's ACE OS; read in full | `ace16.txt` (same directory as the source) says "This system is Public Domain Software." Adoptable; record the source and author in the file header | pair-aligned `put` (odd leading right char, even body in whole bytes, odd trailing left char); char backing store; XOR masks for reverse; underline flag; IRQ cursor; REU as memmove for scroll and fill; screen-save blank |
| **Novaterm 9.6** `v9.6/80col/*.src`, `misc/font80.*`, `font81.*` (in `novaterm-source.tgz`, the author's source release; read, not assembled) | Terminal program's loadable 80-column drivers, 900-1,000 lines of source each, plus fonts | **Owner asserts it adoptable (2026-11-20)**: the author released the source free, and the C64OS author (a commercial project) includes NovaText from it. The tarball has no licence text (checked), so this assertion is the whole evidence: say so in each adopted file's header, credit the author | see "The Novaterm family" below: the nibble-mask font, per-row high-water marks, **look-ahead scroll**, a sprite cursor, an REU variant, and a clean driver ABI |
| **Screen-80** (Compute's Gazette, Sep 1984) | Magazine type-in, about 3 KB, hooks CHROUT; read from the article and the disk image, only partly disassembled | Copyrighted magazine listing: **not adoptable**, ideas only | hires screen at `$E000` under the KERNAL; one colour for the whole screen (what you get without a matrix); `Custom-80` joystick font editor is a good font-tool idea |
| **Color80** (Richvale, 1983) | Commercial product, the copy in the brief is a crack ("broken by Mr. Unprotector") | **Proprietary: do not copy, do not adopt.** Not studied beyond the loader (`$01=$34`, copies code to `$A000`) | per-character colour is its selling point; it needs a different layout (not traced). Out of scope |
| **SOFT80** (Lampton, 1984, CP/M) | 6510 side of a CP/M cartridge patch; docs read, binary only glanced at | "unlimited **non-commercial** distribution": **not compatible with an MIT repo**, ideas only | VIC bank 3: bitmap at `$E000`, colour matrix at `$D000`, code at `$D400`, all RAM under ROM and I/O; ESC sequences for cursor/colour/underline |

## The Novaterm family (source)

Novaterm ships one driver per hardware case behind one jump-table ABI (`jmp` slots at fixed offsets: `init80`/`enter80`, `outchr`, `blcrsr` (cursor blink), `calcloc`, `scroll`, `insert`, `erase`, `putchar`, then `clrtoeol`, `clrfrombol`, `setattr`, `specattr`, `saveattr`/`restattr`; data slots for `sctop`, `scbot`, `lines`, `under`, `color80`, `border80`, `scrlahd`). Variants, by diff against `default.src` (all share the `$CF` mask and the stock zero page):

| Driver | What differs |
|---|---|
| `default.src` | Reference. Bitmap at `$A000` (rows `$140` apart) in VIC bank 2, colour matrix and per-row colour arrays, CPU banks with `$01=$36` while drawing |
| `default-sprite.src` | The cursor is a hardware sprite (position from the column/row, doubled in X and Y, one 24x21 shape) instead of an XOR into pixel row 7: no bitmap write per blink, no read-modify-write race with output |
| `reu80.src` | Same screen, but scroll, erase and colour moves are REU DMA (the `$DF00` registers, with the address-control register for a fixed-address fill, then `reu_length` and `reu_command` repeated per chunk); address control and chunk sizes not traced |
| `scpu80.src`, `ss80.src` | SuperCPU speed-ups (mirroring, the `-p2` assembler pass); ss80 is a copy with the same comment line. Irrelevant to us |
| `vdc*.src` | The C128's VDC chip: a different problem, nothing to take |

Two techniques in `default.src` that I had not seen in ACE, and that matter more than the blit:

1. **Look-ahead scroll (`scrlahd`).** When a line feed would scroll, the driver counts the line feeds already waiting in the receive buffer (`recbuf` between `rhead` and `rtail`) and scrolls up to 12 lines in **one** pass. A pass costs about the same whatever the count, so a screenful of output scrolls about as fast as one line. For us the "buffer" is the argument of `con_write` (`r0`/`r1`), which we already hold whole: counting `$0A` in it needs no backing store, so this beats my earlier "backing store and deferred scroll" idea on cost. Keep the 8 pages for the backing store only if redraw needs it.
2. **Per-row high-water mark (`lastpos`).** Each text row remembers the right-most pixel cell it ever drew; a scroll copies `max(lastpos of the source, lastpos of the destination)` bytes of each pixel row (a 32-byte unrolled `lda (next),y / sta (loc),y / iny` body, about 13 cycles a byte), not 320. Real output is mostly short lines, so the typical copy is a fraction of the 7,680-byte worst case. This answers the scroll worry in the numbers below.

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
- **Look-ahead scroll** (Novaterm `scrlahd`, above) in place of a deferred-scroll design: count the line feeds in the `con_write` buffer and scroll that many lines in one pass. Likely the largest practical speedup on a stock machine, with no backing store.
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

- **IEC timing.** The physical-1541 stall is closed (the test harness's REST DMA halted the CPU mid-byte; owner, 2026-11-18), so VIC changes are not blocked by it. One real rule remains: the JiffyDOS windows need no bad lines and no sprites (`jif_first` reads `$D015` and stays on the standard protocol if a sprite is on). A bitmap screen has the text screen's bad-line pattern; a **sprite cursor** (the `default-sprite` idea) would silently drop JiffyDOS transfers to the standard protocol while it shows, so either hide it across disk I/O or keep the XOR cursor. Run the disk and bus tests with the mode on. The harness rule stands: never DMA during a transfer.
- **Legibility.** A 4x8 cell leaves a 3x5 or 3x7 glyph. Composite and CRT shows it badly; on the Ultimate's HDMI it is usable. Needs a look on real hardware, not assumed.
- **Font source.** Not decided. Options: an ACE or Novaterm font (both stated public domain; check the licence evidence before adopting), or draw our own to include `{ } ~ \ | ^ _` for the S14 compiler (D17). Never derive it from the character ROM (repo rule).
- **Bitmap read-back.** Reading a glyph back from the bitmap is not needed with a backing store; without one `edit`'s screen restore would be impossible, a third reason to weigh the 8 pages.
- **Not checked:** the REU scroll numbers (est.); whether the cursor flicker at 50 Hz is visible; Screen-80's and Color80's internals beyond what is above.

## Suggested next steps

1. **Host proof**, no hardware: a script in `tools/` that renders a text file through a candidate font and the nibble-merge algorithm to a PNG, so we can judge the font and the cell shape. Cheap, and it settles the font question.
2. **D3 + D9 first** (geometry query, page claim); they are useful on their own and the soft-80 module needs both.
3. **`con80` module in VICE**: blit, cursor, scroll without an REU. Measure cycles with the host tools, then decide on the backing store and deferred scroll.
4. **Look-ahead scroll and row high-water marks** in the first driver; **REU scroll** behind a probe afterwards. Then a hardware run (legibility, IEC with the mode on).

Sources: ACE `acesoft80.s` and `ace16.txt` (csbruce.com archive); Compute's Gazette, Sep 1984, "80 Columns For The 64" and its disk image; SOFT80.txt and SOFT80.com, Color80, the same set on mikenaberezny.com; Novaterm 9.6C binaries and `novaterm-source.tgz` (zimmers.net, `pub/cbm/c64/comm/Novaterm/`).

## Host model (POC, 2026-11-20)

`tools/soft80_render.py FONT [TEXT] -o out.png` models the driver's algorithms
on the host (`tools/test_soft80_render.py` checks them against per-pixel
drawing): the nibble-merge put, pair-aligned put_string, high-water-mark
scroll and look-ahead scroll, counting bitmap bytes read and written. The
font is a parameter (doubled-nibble, 2048 bytes); none is committed, since
the Novaterm font's licence is owner-asserted only.

What it showed:

- The doubled-nibble merge is right: random puts in any order equal the
  per-pixel reference, and rendered text with the Novaterm font is clean and
  legible at 80 columns (the 4-pixel cells hold up; `m`, `w` and `@` are the
  weak glyphs).
- Pair-aligned put_string needs under half the bitmap reads of per-char put
  (test asserts it): a pair never reads the cell.
- Look-ahead scroll beats one-LF-at-a-time (test asserts fewer bytes moved).
- On a synthetic 200-line listing (~31 columns average): 697k bytes read and
  744k written, against 1.40M each for per-char RMW with full-width scrolls.
  Scrolling still dominates (176 scrolls); this is the number a REU-DMA scroll
  or a smaller scroll window would attack. Bytes, not cycles: the 6502 cost
  per byte is still an estimate.

Next: the 6502 `con80` put/scroll in a VICE test, with this model as the
oracle for the bitmap contents.

## 6502 core (POC, 2026-11-20)

`src/mod/con80.inc` is the driver core (moved from `experiments/con80/con80.s`): `c80_init`, `c80_write` (r0/r1 as
`con_write`), nibble-merge single put, pair put, run collection through the kernel's
`to_screen`, wrap, LF look-ahead scroll with per-row high-water marks. 1,132 bytes of
code and tables plus about 130 bytes of BSS, plus the 2 KB font. It keeps `$D3`/`$D6` as
column and row, and uses only kernel scratch (p1-p4, tmp0-tmp3). The font is 808 bytes, not 2 KB (below). `tools/test_con80_sim.py`
assembles it against the kernel image's label addresses and runs it in py65 beside the
host model (`tools/soft80_render.py`); bitmap, high-water marks and cursor agree on random
floods, every alignment, wraps at 80, FF, tabs, skipped codes, one-byte writes, and look-ahead
edges (ESC, FF and BS in the buffer, 30 LFs in a row), reverse, BS, ESC = R r K C (also split across
writes), the cursor and the colour matrix.

Decisions the work forced:

- **Font layout is glyph-major**: 101 glyphs (screen codes 0-$64, all `to_screen` returns), 8
  bytes each, page aligned, so a glyph pointer is `code*8` (808 bytes; the row-planar layout of the
  first cut is gone, see `soft80-memory.md`). Novaterm's font has capitals at screen codes 1-26 and
  lowercase at `$41-$5A`; Breadbin's `to_screen` is the other way round, so the font is
  swapped when loaded (`kernel_order()`), and the driver consumes `to_screen` output unchanged.
- **Look-ahead is across lines, not just consecutive LFs.** At the bottom row, count the LFs in
  the next 255 buffer bytes (stop at FF, ESC or BS, cap 24), scroll that many rows at once, and put the
  cursor n-1 rows up; the following LFs only move it. Same final bitmap as sequential
  execution (tested), 1/n of the scrolls.

Measured (py65 cycle counts, so the 6502's, not an estimate; PAL 985,248 cycles/s):

| case | cycles |
|---|---|
| 78-char row, one write | 20,200 (about 260/char incl. run collection) |
| one char | 707 |
| scroll 1 line, rows ~17 columns | about 35,000 |
| scroll 1 line, full rows | about 110,000 (copy at 13.4 cycles/byte) |
| 200 lines (6,410 chars, 5-60 cols), 8 lines per write | 3.3 M = 3.35 s |
| same, 1 line per write | 12.7 M = 12.9 s |

So output speed is decided by how many lines arrive per `con_write`. In large writes the
look-ahead keeps it near 60 lines/s; line-at-a-time writers (a shell echoing, `ls` if it writes per
entry) pay a full scroll every line, 3-6 times slower than text mode today (about 13,400 cycles per
scroll). The ways to buy that back, in order of cheapness: have the producers write whole buffers
(`ls`, `cat`, pipes: check their buffer sizes); keep the high-water marks honest (short rows
are the common case); REU DMA behind a probe (about 8,000 cycles for a full scroll); a
self-modified absolute-addressed copy (about 10 cycles/byte instead of 13.4).

## Kernel wiring (2026-11-20)

- **Seam in `con.s`:** `cursor_hide`, `cursor_show`, `con_putc` and `con_write` are four consecutive `jmp` stubs (12 bytes resident) to `c40_hide`, `c40_show`, `c40_putc` and `c40_write`, the 40-column bodies. Internal callers keep the stub names. The module patches the operands (IRQ off) and puts the `c40_*` addresses back on unload. The blink in `con_cursor_tick` goes through the same stubs.
- **`src/mod/con80.s`** (`/lib/km/con80`, class 2, name id 5): includes the core with `MODULE`, `CUR_EXT` (the kernel's `cur_vis` is the cursor flag) and `FONT` its own data (`src/mod/con80.font`, 808 bytes, from the Novaterm font, credited in the module header, evidence owner-asserted). `init` is refused unless `mod_busy`, refused as a second copy (the `con_putc` stub no longer points at `c40_putc`), claims the fixed pool pages `$20-$3F` directly in `pg_used`/`free_pages` (all 32 free, else ENOMEM), hides the 40-column cursor, runs `c80_init`, patches the stubs, then sets `$D018=$18`, `$D011=$3B`. `fini` hides the cursor, restores the stubs and `$D011=$1B`/`$D018=$16`, frees the pages, refills colour RAM and clears the screen through the restored 40-column code. `m_putc` preserves A, X, Y and p1/p2; `m_write` and `m_putc` save p3..tmp3 (11 contiguous bytes, asserted at link time) and hold `con_busy`; the blink hooks preserve X, Y, p3, tmp2.
- **`kapi.txt`** gained 15 names (`tmp2 tmp3 con_write cursor_hide cursor_show c40_hide c40_show c40_putc c40_write con_busy cur_vis to_screen scr_color pg_used free_pages`), which changes the API hash: a reviewed ABI act.
- **Opt-in:** `/etc/con80` present makes `init` run `mod load /lib/km/con80` before the first shell. This is the reliable path, and in practice the only one: the claim needs `$20-$3F` free, and on the default boot `sh` sits across them (first fit after `init` and `login`; from the current header sizes the image lands at `$12-$28`, the spike's `$13-$29` was an earlier build). So `mod load` from a shell fails on a standard boot (no `/etc/con80`). A boot-loaded session can unload and reload (the shell was laid out around the window; VICE `test_load_80_columns_unload_reload`). The module is a boot option despite being a km. The loader reports any refused `init` as ENODEV, whatever the cause.
- **Size:** the module image is 2,197 bytes (code 1,094 + font 808 + wrapper 295), 9 pages: claim 41, pool 114. Eight pages (pool 115) needs about 149 bytes out; candidates are in `soft80-memory.md`.
- **Test:** `tests/test_con80.py` (in shard s5) boots an image with `/etc/con80`, reads the bitmap back through the font (what the VIC would show), logs in, echoes a 78-character line, checks it, unloads (40-column text again), reloads (the pages are free again) and unloads. Hardware: not yet.
