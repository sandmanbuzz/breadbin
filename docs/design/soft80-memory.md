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

The POC claims about 46 pages (bitmap 32, font 8, code and BSS 6): the pool goes 155 -> ~109.

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

## Best-effort reductions (in order of payoff)
1. **Font strips with the driver in the gaps.** The font is row-planar, page `I` holds glyph row
   `I` for all codes, but `to_screen` yields at most `$64` (101 codes), so each of the 8 pages is
   101 bytes of font and 155 bytes free: 1,240 bytes of gaps, about the size of the driver. Code,
   `rowlo/rowhi` and BSS go in the gaps (one linker memory area per gap; routines over 155 bytes,
   `pair` is about 180, split with a jump). Claim becomes 32 + 8 = **40 pages** (was 46), and the
   bitmap's unused tail `$3F40-$3FFF` (192 bytes) holds the spill.
2. **Size pass on the driver itself.** The POC was written for cycles, not bytes (8x unrolled
   copy and pair). Perf has headroom now, so the unrolls can go back to loops where the saving
   pays; target a gap-sized driver (under 1,240 bytes with all tables).
3. Not worth it: a single-nibble font (the strips already waste the page stride, so halving the
   bytes saves no pages once the code fills the gaps); 24 rows (saves 320 bytes, breaks 25-row
   programs); colour RAM as storage (500 usable bytes, needs I/O banking on every access).

## Result for the tiers
| tier | cost |
|---|---|
| Classic | pool 155 -> 115 pages (29.4 K), about where the fork started (120). Fits `sh` + `edit` + `as` together. Realistic as "Classic, if you want it" |
| Expanded / Recommended | identical: the REU cannot hold the live bitmap. It helps nothing here, so there is no "REU recommended" lever for this feature |

## What is still open
- The allocator needs a **fixed-page claim** (mark `$20-$3F` and the module's pages used if all
  are free, else ENOMEM), run early at boot (from the boot script) so nothing is in the way.
- A hook so the console write path can be switched to `c80_write` (and back, if unload is wanted).
- The border/column-0 legibility on a 1702: try `$D020` = the background colour.
