# Getting TPA back: ranked structural moves (f7, 2026-11-01)

Question (from the owner via the kernel session): beyond uci.km (~9 pages) and cbm.km (~4-5), what structural moves recover the most pages? Favour low risk; TPA is nice-to-have, a clean campsite is the goal. Numbers are the repo's `make size`, the lens reports in `docs/design/research/next/` and `docs/design/next/allocator.md`; page estimates are **UNVERIFIED** unless marked, and each should be measured before claiming it.

## Two kinds of pages

1. **Pool pages the kernel takes** (`KSTART`): every 256 bytes of resident *code* in KRAM costs one page. BSS does not: it lives at `$E000+` and costs *room*, not pages.
2. **Pages a running system uses**: init + login + sh are resident at an idle prompt. That is 5 + 6 + 17 = **28 pages (7 KB)** (E-baseline CX table; A-process-memory F14) before any command. Stock BASIC's "38,911 bytes free" counts none of this, so this is where the comparison with stock is least fair and the most is recoverable.

BSS savings turn into pool pages only if there is **movable code** to put in the freed KHI space (CODEHI is the existing mechanism: cbm.s already lives there). So **every 256 BSS bytes freed = one page, as long as a cold code segment is parked above the BSS.** Moves 3-6 below depend on move 7.

## Ranked list

| # | Move | Pages | Breaks / risk | Effort |
|---|---|---|---|---|
| 1 | **login becomes part of sh (or `exec`)**: one program prompts for the login and then is the shell, so login's 6 pages are not resident behind sh. User-space only, no kernel change. The general form is `exec` (replace image), the A6 proposal in A-process-memory, which also lets init `exec`-chain | **~6 at every idle prompt** | `login` program changes; password code (`passwd.o`, 423 B) is shared. A failed login must still return to the prompt. Low | 1 day |
| 2 | **uci.km** (already planned) | ~9 on non-Ultimate machines | the module loader; UCI sim tests move to loading the module | in progress |
| 3 | **cbm.km** (already planned) | ~4-5 | a CBM mount needs `/lib/km/cbm` on the root disk | in progress |
| 4 | **Cold kernel code above the BSS (CODEHI) without modules**: park the rarely used resident code (`mkdir/rmdir/rename/unlink`, `format`/`diskio` helpers, `mount/umount/mntinfo`, `cache` ops) in KHI. Pure placement through the linker config; no behaviour change | each 256 B moved = 1 page, **capped by the free KHI space** (58 bytes today, so it needs 5 or 6 below first) | none functionally; check that nothing in the IRQ or boot path runs it before it is in place; `make size` shows it | hours each |
| 5 | **Per-process save areas into the process's own pages** (allocator note, A2): `p_save` is 12 x 192 = 2,304 B of BSS | **~9 KHI pages freed**; net after cost about 9 - 0.75 x (resident processes): about **+6 at an idle prompt**, 0 with 12 processes | touches `sched`/`proc_exit` (context-switch path): full suite, JiffyDOS, hardware. Medium | 2-3 days |
| 6 | **Block cache buffers: `NBUF` 6 -> 3**, or taken from idle pool pages (allocator note step 4) | 3 KHI pages at once (768 B); the pool-backed version returns the rest when memory is short | Classic (no REU) disk gets slower: exec re-reads dir/inode blocks. Measure with the Cache and Boot classes and the cold-boot read count (`make CACHE=2`, `cache stat`) before deciding. Low-medium | 1 day to try |
| 7 | **`p_cwd` (12 x 48 = 576 B): store cwd as an inode, rebuild the string on demand** (roadmap lever 4) | ~2 KHI pages | `getcwd` must walk `..` (costs disk reads on c64fs); a mounted UCI path cannot be rebuilt this way (it is a host path) so the UCI cwd string must stay. Medium | 1-2 days |
| 8 | **Err strings out of `err.o`, then the shared library** (F, A-process-memory M4): 494 B of messages linked into 24 programs; init/login/sh link them. Shared library saves ~1 KB per resident process | ~2 pages at idle (err strings alone), ~4-6 with the shared library | CX v2 for the library class; `perr` reads messages from a file on the error path only. Medium-high | 1 week |

Rough total if 1, 2, 3 and 4+5 land: **+6 +9 +4.5 +6 = about 25 pages** on top of today's 142 (the same order as the kernel session's own 155-160 estimate for modules alone, plus idle usage).

## What I would not do

- **Shrink `MAXPROC` or `NFD`**: small bytes, real capability loss (A-process-memory "not to change").
- **Compress programs on disk to save RAM**: it does not help RAM; it helps stock-disk reads only.
- **Move the syscall page or hardware vectors**: fixed.
- **The `pg_used` array** (143 B): not worth touching until the tagged allocator exists; the allocator needs that byte anyway.
- **Raise `KSTART` by making the kernel unrepresentative**, e.g. deleting features, before measuring the idle chain in 1: a free 6 pages are available without removing anything.

## Order I would take

1 (login into sh) first: biggest user-visible win, no kernel risk, and it tests the "idle footprint" idea cheaply. Then 2 and 3 (already moving). Then 4 as the conversion layer for BSS savings, then 6 (`NBUF` experiment, one build constant, quickly reversible), then 5 only when the sched path is next quiet. 7 and 8 are optional.

## Measure before claiming

`free` at an idle prompt (pages in use) before and after each move; `make size` for room; the Boot, Pool, Cache and Console classes in the container; the cold-boot read count for move 6.
