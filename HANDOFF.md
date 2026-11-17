# HANDOFF.md

## Current state
- Branch `e/holy-shit-assembly-skill` pushed at `9a55856` (4 commits, 967 lines across 6 study files)
- `main` at `9821e44`, pushed to origin
- Session in worktree `../breadbin-next` (detached HEAD at `9821e44`)

## What was done
1. Sent C agent study branch summary, received full review
2. C agent corrections: `reap` is iterative (tail-loop), `BIT $2C` is 3-byte encoding trick, glob claim contradictory, zero page/BSS conflated
3. C agent top suggestion: "The goal isn't to write fewer instructions. It's to make fewer independent things happen."
4. Built `rompool.s` — ROM pool experiment treating ROM as "pool of useful bytes"
5. Wired ROMPOOL into build (Makefile + kernel.cfg)
6. All 678 tests pass with ROMPOOL=1

## Key findings
- BASIC ROM ($C000-$DFFF) already paged in, readable at $C000-$CF00 (3840 bytes) with zero overhead
- KERNAL ROM ($E000-$FFFF) needs 8KB BSS backup: ~49K cycles round trip
- ROM pool module: 131 bytes code (ROMPOOL segment in KRAM) + 1 byte BSS

## Files modified
- `src/kernel/rompool.s` — ROM pool experiment (new)
- `src/kernel.cfg` — added ROMPOOL segment
- `Makefile` — added ROMPOOL=1 build option

## Files for reference
- `src/kernel/rompool-findings.md` — experiment findings summary
- `include/breadbin.inc` — kernel interface header
- `src/kernel/k.inc` — kernel internal definitions
- `.agents/skills/holy-shit-assembly/studies/` — 6 study files from holy-shit-assembly branch

## Open questions
1. Is BASIC ROM character set useful for custom font rendering?
2. What specific KERNAL data tables are worth 49K cycle access?
3. Can we page out BASIC ROM to access $C000-$DFFF as RAM?
4. Does the "pool of useful bytes" concept justify the overhead for real use cases?

## Build
```
make ROMPOOL=1 all   # build kernel with ROM pool
make ROMPOOL=1 test  # run all tests (678 tests)
```
