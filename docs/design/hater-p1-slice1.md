# Hater Review: P1 Slice 1 - Shell $? && || Operators

## Spec
- `$?` expands to decimal exit status of last command.
- `a && b` runs `b` only if `a` succeeded (exit status 0).
- `a || b` runs `b` only if `a` failed (exit status non-zero).
- Host tests green before VICE run.
- Zero kernel byte cost per feature-priority table.

## Evidence
- 672/672 host tests green
- 20/20 shard tests green
- Shell binary: 3968 bytes (20.5 pages)
- BSS usage: 1045 bytes (4.1 pages)
- New variables: last_status (1 byte), stage_stop (1 byte) = 2 bytes total

## Branch
- feat/p1-slice1-status (b57f83b) based on main 8945ed7

## What was NOT run
- VICE end-to-end tests (ShellOperators class not yet verified on real hardware/simulator)
- JiffyDOS-ROM sharded run
- Hardware list

## Diff
See git diff 8945ed7..b57f83b

## Files changed
- src/bin/sh.s: Core implementation
- src/lib/num.s: dec_str export
- tools/asim.py: WAIT returns exit 0 in X
- tools/test_sh.py: 6 new host tests
- tests/test_system.py: 8 new VICE tests
- tools/ci/shards.txt: Added ShellOperators to s3 shard
