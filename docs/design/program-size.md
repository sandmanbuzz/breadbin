# How big are the user programs?

Measured on `fix/iec-recover` at `75de245`; rebased onto `origin/main` `67d0972`, whose only change under `src/lib`, `src/bin` and `tools/cx.py` is the new `turbo` program (43 programs, 57,870 bytes, 245 blocks there; the tables below are the 42-program measurement) (`make`, then a relink of each program with `ld65 -m`
to attribute bytes to modules). Blocks are 254 data bytes. Nothing in the tree was changed.
Savings below marked *est.* are arithmetic on these measurements, not builds.

## Totals

| | bytes | share |
|---|---|---|
| 42 programs in `/bin` (CX files) | 57,198 | 242 blocks, mean 1,361 bytes |
| relocation tables (2 bytes each, 4,491 relocs) | 8,982 | 15.7% |
| CX headers (9 bytes each) | 378 | 0.7% |
| image (code + rodata) | 47,838 | 83.6% |
| of the image: program's own code/rodata | 18,553 | |
| of the image: library modules | 29,285 | 51% of all bytes |
| block rounding (242 x 254 - 57,198) | 4,270 | about 17 blocks |

## Top five

| program | bytes | blocks | own | library | relocs | bss |
|---|---|---|---|---|---|---|
| `as` | 6,375 | 26 | 4,119 | 1,061 | 593 | 14,668 |
| `basic` | 5,409 | 22 | 3,399 | 861 | 570 | 8,960 |
| `sh` | 3,941 | 16 | 2,109 | 967 | 428 | 1,292 |
| `passwd` | 2,598 | 11 | 667 | 1,484 | 219 | 554 |
| `format` | 2,232 | 9 | 906 | 967 | 175 | 321 |

`as` and `basic` are big because they are programs (opcode tables in RODATA: 2,044 and 839 bytes), not
because of the library. `passwd` is more than half library (its own `passwd.o` is 423 bytes plus the common set).

## What makes them big

Library module sizes (code + rodata) and how many programs link each one:

| module | per program | linked into | total |
|---|---|---|---|
| `err.o` | 609 (115 code, 494 strings) | 26 | about 15.8 KB |
| `lib.o` | 158 | 42 | 6.6 KB |
| `num.o` | 200 | 22 | 4.4 KB |
| `input.o` | 94 | 10 | 0.9 KB |
| `passwd.o` | 423 | 3 | 1.2 KB |

Every program that calls `perr` or `open_or_die` carries all 17 error strings and the lookup table,
whichever errno it can actually hit. The seven smallest programs (192 to 492 bytes) are 158 to 358
bytes of library each.

## Room, biggest first

1. **Error strings once, not 26 times: about 12 KB (about 48 blocks) est.** Two shapes:
   a kernel `SYS_ERRSTR` (494 bytes of strings move into kernel space, which has 6,079 free bytes; each
   program keeps about 30 bytes of stub), or a trimmed errno table per program. The kernel route is a
   new syscall, so it is a contract addition and should wait for the M0-7 space pass decision. A
   cheaper change that needs no contract: shorten the strings and drop errnos no program can produce
   (not measured; would save a fraction of the 494).
2. **Relocation encoding: about 4.5 KB (about 18 blocks) est.** Store each offset as a 1-byte delta from
   the previous one. Of 4,491 relocs only 3 have a gap over 254, which need an escape. This changes the
   CX format (version 2, `tools/cx.py` and the loader), so it is a loader change, not a library one.
3. **Block rounding: up to 4.3 KB (17 blocks), unrecoverable by itself.** It shrinks only when items 1 and
   2 move programs under a block boundary, and can't be fixed on its own.
4. **`lib.o` and `num.o` split: under 1 KB est.** `lib.o` (158 bytes) is linked into all 42 programs
   including `echo` (228 bytes total), so part of it is probably unused by the small ones. I did not
   read it function by function.
5. **`as` and `basic` tables: not estimated.** Their own rodata (2,044 and 839 bytes) is where a
   change would pay off, but it needs a read of the tables.

Items 1 and 2 together are about 16.5 KB, roughly 29% of the 57 KB, which is the order of magnitude
of the 233 to 170 block target mentioned for breadbin-next's CP4. I did not ask that session for its numbers
and have not compared against them. Duplicate helpers across programs (a stated question) are not measured:
I only attributed bytes by module, not by routine.

## How to reproduce

```sh
make
for p in $(ls src/bin/*.s | xargs -n1 basename | sed 's/\.s$//'); do
  ld65 -C src/prog.cfg -S 0 -m /tmp/$p.map -o /tmp/$p.0 build/p/$p.o build/lib/breadbin.lib
done
```

then read the "Modules list" section of each map.
