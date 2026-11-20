# Soft 80-column console: memory cost and where it can live

Status: survey, 2026-11-20 (spike; nothing wired). Companion to `soft80-spike.md`. Owner direction:
perf is good enough (instant at 64 MHz, acceptable at 1 MHz), so footprint and the Classic-tier
cost come first; deliver as a runtime opt-in module, not a build variant.

## What is fixed

| item | bytes | why |
|---|---|---|
| bitmap | 8,000 | 80x25 glyphs of 4x8 pixels = 320x200 hires, one bit per pixel. VIC reads it from RAM only; an REU cannot hold the live bitmap |
| colour matrix | 1,000 | per-cell fg/bg in hires. At `$0400` it is the existing text screen: **free** |
| font | see below | |
| driver | ~1.1 K code and tables, ~0.2 K BSS | POC, not yet size-passed |

The first POC claimed about 46 pages (bitmap 32, font 8, code and BSS 6); see the reductions below.

## Where the bitmap can go (VIC banks, measured against `kernel.cfg` and `make size`)

| placement | result |
|---|---|
| **bank 0, bitmap `$2000`, matrix `$0400`** | costs 32 pool pages, matrix free, no kernel change. Splits the pool into `$0800-$1FFF` (24 pages) and `$4000-$A2FF`; the allocator is a first-fit page map (`mem.s`), so a hole is just 32 pages marked used, and the largest program (`as`, 7.7 K) still fits either side |
| bank 2, bitmap `$8000` | same 32 pages, but the matrix (1 K, 1 K-aligned) must sit at `$A000`, which collides with `KSTART` (`$A300`): the kernel would move up a page (1,271 bytes of room below `$CF00`, so possible) and the pool loses 4 more pages. Worse than bank 0 |
| bank 3, bitmap `$E000-$FF3F`, matrix `$DC00` (free RAM under I/O, which VIC sees as RAM) | the only placement that is not pool: but `$E000-$FAEF` is kernel BSS and `CODEHI` (6.9 K), which would have to move into the pool. Net gain about 1 K for a large layout change |
| bank 3, bitmap `$C000` | kernel code ends `$CA82`, `$CF00` is the syscall page (ABI), `$D000-$D9FF` is the process save area. No |

Verdict: bank 0 at `$2000`. The 8 K cannot be avoided; the question is only the other ~14 pages.

## Rejected: a text-mode soft 80 (a charset of character pairs)
A 1 K screen plus a 2 K charset of "pair" glyphs would cost 3 K instead of 8 K, but the charset
holds only 256 pairs. Measured on aligned character pairs per 25-line screen of this repo's own
text (README, roadmap, sources): median 79-300, max 207-337. Real screens routinely need more than
256 distinct pairs, so it fails on ordinary text with no graceful fallback. Rejected.

## Best-effort reductions (done in 94e0483, measured in py65)
The font-in-the-gaps idea (row-planar strips, 101 bytes of font and 155 of gap per page, driver in
the gaps) was superseded by something smaller: it only wastes less than the POC because the page
stride is forced, and the stride is forced only by the row-planar layout. Done instead:
1. **Glyph-major font, 101 glyphs (codes 0-$64, all `to_screen` returns): 808 bytes**, not 2,048.
   A glyph pointer is `FONT + code*8` (a page-aligned FONT makes it a shift of the code alone, 18
   bytes), so the draw loop is rolled: `lda (q),y`.
2. **One put loop for pair, left half and right half**, in the eor form
   `(p & $f0) | (q & $0f) = ((q ^ p) & $0f) ^ p`: a half that keeps the old cell just points its
   source at the cell itself. 16 bytes instead of ~280 (unrolled pair and read-modify-write).
3. Rows computed, not tabled (`row*320 = (row*5)<<6`); copy and fill count cells, not 16-bit
   bytes; BSS in the 192-byte tail of the bitmap's last page (`c80_clear` zeroes it with the bitmap,
   which is also what zeroes the high-water marks).

| | POC | now |
|---|---|---|
| code and tables | 1,132 B | 726 B |
| font | 2,048 B | 808 B |
| BSS | ~130 B pool | 0 (bitmap tail) |
| pool pages claimed | 46 (bitmap 32 + 14) | **38** (bitmap 32 + 6) |
| 78-char row, 1 MHz | 20.2 k cycles | 22.9 k (+13%) |
| 200 lines, 8 per write | 3.35 s | 3.68 s (+10%) |

Font and code are 1,534 bytes of the 1,536 in 6 pages: no slack. Not worth it: a single-nibble font
(shifts per row for 400 bytes), 24 rows (320 bytes, breaks 25-row programs), colour RAM as storage.

**Not yet in the driver, and it will grow:** the kernel console also has a cursor (blink, in the
IRQ), backspace, reverse video, `ESC =` addressing, `ESC K`, `ESC C` colours, and `con_write` is the
buffer-level entry to hook. Estimate (not measured): +200-250 bytes, so 7 pages, 39 in all.

## Result for the tiers
| tier | cost |
|---|---|
| Classic | pool 155 -> 117 pages (29.9 K) with the partial driver, about 116 once the console features are in; the fork started at 120. Fits `sh` + `edit` + `as` together. Realistic as "Classic, if you want it" |
| Expanded / Recommended | identical: the REU cannot hold the live bitmap. It helps nothing here, so there is no "REU recommended" lever for this feature |

## What is still open
- The allocator needs a **fixed-page claim** (mark `$20-$3F` and the module's pages used if all
  are free, else ENOMEM), run early at boot (from the boot script) so nothing is in the way.
- A hook so the console write path can be switched to `c80_write` (and back, if unload is wanted).
- The border/column-0 legibility on a 1702: try `$D020` = the background colour.
