# ROM Pool Experiment — Findings

## What works

`rompool.s` compiles, links, and passes all 678 kernel tests.

- **ROMPOOL segment**: 131 bytes of code in KRAM (not KHI), 1 byte BSS
- **`rompool_kernal_in/out`**: Page KERNAL ROM in/out with BSS backup (8KB)
- **`rompool_read_kernal`**: Read bytes from KERNAL ROM while paged in
- **`rompool_basic_read`**: Read bytes from BASIC ROM (already paged in)
- **`rompool_read_basic_safe`**: Read $C000-$CF00 (3840 bytes) freely

## Memory layout

```
$A300-$CF00  CODE        kernel code (safe from both ROMs)
$CF00-$D000  JUMPTAB     syscall jump table (overlaps BASIC ROM)
$C000-$DFFF  BASIC ROM   already paged in
$E000-$FFFF  KERNAL ROM  paged out (RAM)
$E000-$FFFA  BSS         overlaps KERNAL ROM
```

## BASIC ROM ($C000-$DFFF) — free to read

Already paged in. Can read $C000-$CF00 (3840 bytes) without backup.
Below the jump table, so no shadowing.

Contains:
- Character set (8x8 bitmap fonts)
- PETSCII <-> ASCII mappings
- BASIC string function tables
- Other useful byte sequences

**Overhead: 0 cycles to read, since ROM is already paged in.**

## KERNAL ROM ($E000-$FFFF) — expensive to access

Paged out (RAM at $E000-$FFFF). To read:
1. Back up BSS (8192 bytes) → shadow page: ~24K cycles
2. Clear bit 6 of $01: ~3 cycles
3. Read ROM bytes: varies
4. Restore BSS from shadow: ~24K cycles
5. Set bit 6 of $01: ~3 cycles

**Total round trip: ~49K cycles**

Contains:
- I/O routines (CHROUT, GETIN, CHRIN, OPEN, CLOSE, etc.)
- String manipulation functions
- Memory management
- Disk I/O

## Verdict

**BASIC ROM poaching is compelling** — free access to 3840+ bytes of useful data.
Character set, PETSCII mappings, and BASIC tables are all available at zero overhead.

**KERNAL ROM poaching is expensive** — 49K cycles for a round trip.
Worth it only if we're reading enough bytes to justify the overhead, or if we need
specific data tables/constants that would save more cycles elsewhere.

**The "pool of useful bytes" concept works** — we can read arbitrary ROM bytes
and use them as data or code. The key constraint is the backup/restore cost
for KERNAL ROM.

## Next steps (if worthwhile)

1. Add a `rompool_read_basic_safe` consumer that reads the BASIC character set
   and uses it for custom font rendering
2. Add a `rompool_kernal_in` consumer that reads specific KERNAL data tables
   (e.g., PETSCII conversion tables, string function lookup tables)
3. Benchmark: is reading a small ROM fragment worth 49K cycles?
4. Explore: can we page out BASIC ROM to access $C000-$DFFF as RAM?
