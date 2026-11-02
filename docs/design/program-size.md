# How big are the user programs?

Re-measured on `main` at `ba3b6d0` (43 programs, including `turbo`). An earlier measurement on `fix/iec-recover` (42 programs, 57,198 bytes) is superseded: the programs have shrunk since, by about 260 bytes each on `as` and `basic`. I did not bisect that drop. Method: `make`, then a relink of each program with `ld65 -m` to attribute bytes to modules. Blocks are 254 data bytes. Nothing in the tree was changed. Savings marked *est.* are arithmetic on these measurements, not builds.

## Totals

| | bytes | share |
|---|---|---|
| 43 programs in `/bin` (CX files) | 51,136 | 202 blocks, mean 1,189 bytes |
| relocation tables (2 bytes each, 4,289 relocs) | 8,578 | 16.8% |
| CX headers (9 bytes each) | 387 | 0.8% |
| image (code + rodata) | 42,171 | 82.5% |
| of the image: program's own code/rodata | 18,794 | |
| of the image: library modules | 23,377 | 46% of all bytes |
| block rounding (202 x 254 - 51,136) | 172 | under 1 block |

## Kernel modules (not in the program table)

Measured by breadbin-f7 on `main` `ba3b6d0` (CX header read, not relinked). They are loaded by the kernel from `/lib/km`, not exec'd: no argv, no process slot. They count toward root disk use, and toward pool pages only while loaded.

| module | on disk | blocks | pool pages while loaded |
|---|---|---|---|
| `uci.km` | 3,086 | 14 (13 data + 1 indirect) | 11 (10 image, 1 path slots), only while `/u` is mounted |
| `cbm.km` | 1,578 | 7 | 6, stays loaded after the first CBM mount |
| `hello.km` | 80 | 1 | 1 (loader regression test) |
| **total** | **4,744** | **about 21** | |

The 51,136-byte program total above does not include these.

## Top five

| program | bytes | blocks | own | library | relocs |
|---|---|---|---|---|---|
| `as` | 6,116 | 25 | 4,119 | 820 | 584 |
| `basic` | 5,150 | 21 | 3,399 | 620 | 561 |
| `sh` | 3,682 | 15 | 2,109 | 726 | 419 |
| `passwd` | 2,339 | 10 | 667 | 1,243 | 210 |
| `edit` | 2,099 | 9 | 1,470 | 158 | 231 |

`as` and `basic` are big because they are programs (their own rodata includes the opcode tables), not
because of the library. `passwd` is more than half library (its own `passwd.o` is 423 bytes plus the common set).
The `own` and `library` columns are the same attribution as the earlier note (the `as` split matches it exactly).

## What makes them big

Library module sizes (code + rodata) and how many programs link each one:

| module | per program | linked into | total |
|---|---|---|---|
| `err.o` | 368 | 26 | 9,568 |
| `lib.o` | 158 | 43 | 6,794 |
| `num.o` | 200 | 23 | 4,600 |
| `passwd.o` | 423 | 3 | 1,269 |
| `input.o` | 94 | 10 | 940 |
| `target.o` | 103 | 2 | 206 |

Every program that calls `perr` or `open_or_die` links all of `err.o`, whichever errno it can actually hit.
The smallest programs (192 to 228 bytes: `clear`, `pwd`, `echo`) are 158 bytes of library each, which is `lib.o` alone.

## Room, biggest first

1. **Error strings once, not 26 times: up to about 9.6 KB total, string share not re-split (est.).** `err.o`
   is now 368 bytes per program, down from 609 in the earlier note, so the saving is smaller than it was. The
   string part is the bulk of it, but I did not re-separate code from strings. Two shapes: a kernel
   `SYS_ERRSTR` (strings move into kernel space, which is scarce: 354 bytes below `$CF00`; each program keeps a
   stub), or a trimmed errno table per program. The kernel route is a new syscall, so it is a contract addition
   and should wait for the M0-7 space pass decision.
2. **Relocation encoding: about 4.3 KB (about 17 blocks) est.** Store each offset as a 1-byte delta from the
   previous one. The earlier measurement found only 3 of 4,491 relocs with a gap over 254, which need an escape;
   not re-checked on the 4,289 relocs of `main`. This changes the CX format (version 2, `tools/cx.py` and the
   loader), so it is a loader change, not a library one.
3. **Block rounding: 172 bytes now (under one block), unrecoverable by itself.** Nothing to gain here unless items 1
   and 2 change the sizes first.
4. **`lib.o` and `num.o` split: under 1 KB est.** `lib.o` (158 bytes) is linked into all 43 programs, including
   `echo`, so part of it is probably unused by the small ones. I did not read it function by function.
5. **`as` and `basic` tables: not estimated.** Their own rodata is where a change would pay off, but it needs a
   read of the tables.

Duplicate helpers across programs (a stated question) are not measured: I only attributed bytes by module, not by routine.

## How to reproduce

```sh
make
mkdir -p build/maps
for f in src/bin/*.s; do
  p=$(basename "$f" .s)
  ld65 -C src/prog.cfg -S 0 -m build/maps/$p.map -o build/maps/$p.0 build/p/$p.o build/lib/breadbin.lib
done
```

then read the "Modules list" section of each map (the `breadbin.lib(...)` entries are library modules).
