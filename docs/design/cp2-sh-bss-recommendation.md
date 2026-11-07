# Recommendation: feat/cp2-sh-bss (sh input buffer 256 -> 128)

Written 2026-11 for the owner's decision. Docs only; nothing was merged or changed in code.

## What the branch does

`feat/cp2-sh-bss` at 6a99281 (two commits on top of an older main) changes one constant in `src/bin/sh.s`: the input buffer `ibuf` goes from 256 to `IBUFSZ = 128` bytes, and the read length passed to the kernel goes with it (255 -> 128). The read length is one byte, so `IBUFSZ` must stay at or below 255. A host test in `tests/test_system.py` pins the idle-page count.

## What it buys

- **BSS:** 128 bytes less in `sh`, so `sh` has 128 bytes less BSS. Its code is unchanged (3,682 bytes either way).
- **Idle pool:** R17 (2026-11-04, on main `ba69ca4`) measured 21 pool pages at an idle prompt on main and 20 with this change. The owner has since accepted 21 as CP2's exit, so the page is not needed for the criterion.
- **Room above BSS:** the freed 128 bytes of BSS count as room in `KHI` for cold code. Room above BSS on main is now 14 bytes (after the KSTART step), which is the constraint for parking more cold code. With this change it is about 142 bytes, enough for `mkdir` (110 bytes), which L1 could not fit.

## What it costs

- Piped and script input is read in 128-byte chunks instead of 256. More read calls for the same input. Not measured.
- No kernel bytes. No syscall change.

## Evidence still owed before a landing

- Re-measure on current main: pages at idle (`free`), room below `$CF00`, room above BSS (`make size`). The R17 figures are from an older main.
- `make test-host` on the merged tree (the branch was based on an older main, so a merge is needed).
- The VICE `Boot`/idle test that pins the page count (the new test in `tests/test_system.py`), run with `tools/ci/run.sh test-only` on the merged tree.
- A check that line input still works at the 127-character `LINEMAX` (the line is built from the buffer, so 128 bytes is enough for one line).

## Recommendation

Hold it as a ready option, do not land it now:

1. The page it buys is not needed for CP2, and the KSTART step already gave a page.
2. Its real value is the 128 bytes of room above BSS. That matters only when cold code is next to move (`mkdir`/`rmdir`, about 248 bytes together). Land it when that move is next, and it lands with that move.
3. Before landing: rebase onto main, then the four checks above.

If the owner wants it now for the page alone, the owner should say so; the evidence above is then the gate.
