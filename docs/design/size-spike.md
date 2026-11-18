# Size spike: what a demoscene-grade pass would pay (2026-11-18)

Read-only spike on `main` at 80c82a5. Question: if the kernel were squeezed the way a 6502
size-coder would squeeze it, how much would come back, and from where? Nothing in `src/` was
changed. Every figure is labelled: **measured** (assembled and run), **sketched** (assembled,
not run), **estimated** (counted by hand from the source), **speculative**.

## Baseline (`make size`)

CODE 10,329 + RODATA 600 + DATA 78 = 11,007 in the low region (room 257 below `$CF00`);
CODEHI 2,614 + BSS 5,553 in the high region (room 19). INIT 1,389 is released to the pool
after boot, so it costs nothing at run time. One pool page is 256 bytes freed in the low
region, *if* the high region can absorb cold code moved up (it cannot today; it can once
`p_save` leaves it, branch `feat/psave-io`).

## Already done (do not count these twice)

`jtab.s` is the return-address trick from the cookbook, already: `jsr enter`, the low byte of
the return address indexes a record table. Modules (`cbm`, `uci`), INIT release and CODEHI
are the "keep it out of the resident image" levers. So the low-hanging structural fruit is
picked; what is left is mostly fine-grained.

## What was measured

**P1 (measured): 1541 track geometry computed, not tabulated.** `trk_lo`/`trk_hi` (72 bytes),
`blk_to_ts` (40) and `ts_block` (21) = 133 bytes become `spt` (zone chain, 21 bytes),
`blk_to_ts` (46) and `ts_block` (27) = **94 bytes: -39**. Run in py65 against a reference
for all 683 blocks and every valid (track, sector): `experiments/size-spike/` (build line and entry points in the header of `t.py`). Costs: slower (a loop of at most 35 iterations, on a path
that then does a 1541 block I/O); blocks >= 683 are no longer clamped, so the caller's range
check must hold (to be confirmed in `blk.s` before landing).

**Duplicate-sequence scan (measured, a heuristic): `experiments/size-spike/dups.py`.**
Normalised instruction runs of 4+ with 2+ copies across `src/kernel/*.s`. Excluding the 26
`jmp cbm_none` vtable stubs (DATA, patched by modules), the factorable runs add up to roughly
**150-250 bytes**: the `iget` / `I_TYPE == T_DIR` / ENOTDIR check (7+ copies across `file`,
`fs`, `cbm`), `lda r0 / sta pp / lda r0+1 / sta pp+1 / jsr namei` (5), the `bmap / bread`
pair in `fs`, `asl a` x3 index scaling (9). Cheap, mechanical, low risk.

**Counts (measured):** 101 `lda #E / sec / rts` error exits (404 bytes), 143 `sec / rts`, 132
`clc / rts`. A chain of `lda #E1 / .byte $2C / lda #E2 ...` stubs with one shared `sec / rts`
saves one byte per exit in a cluster: **~30-60 bytes**, with the cost that each is a BIT
trick that needs a disassembly comment.

## What was sketched or estimated, by area

| Idea | Bytes | Basis |
|---|---|---|
| P1 geometry computed (above) | -39 | measured |
| `cmd_us` / `iec_write1` as templates (`U?:2 0 `, `B-P:2 0`) plus `cmd_tpl` | -16 | sketched; the call-per-character style costs 5 bytes a character |
| `keytab` 256 B: control table is `unshifted & $1F` for letters, shifted is `\| $80` for letters, plus `kb_mask`, `kb_tabsel`, `bitmask`; keep only the exceptions | -100..-130 | estimated; decoder ~40 bytes |
| `kbd_scan`: fuse the mask / new-key / copy-to-prev passes (four loops become one), drop `kb_cur`, scan loop ends on carry instead of `cpx #8`, reuse `$FF` left in A | -80..-100, plus 8 BSS | estimated from a partial sketch, not assembled |
| `sched` save and restore are the same loop with the direction swapped (patch `lda`/`sta` opcodes, or one routine with a flag), `slot_save_ptr` as shift-and-add with a 192-byte stride | -40..-50 | estimated |
| `oft_alloc`/`oft_free` share the scan, `pi_rd`/`pi_wr` as one array indexed by type, `fd_slot` / `fd_alloc` fusion | -40..-60 | estimated |
| `fs` / `file` / `cbm`: the `iget`-type-check, namei-prologue and dir-check tails as shared entry points | -150..-250 | from the duplicate scan |
| `reu_setup` / `reu_byte` / `cdma` as one register-block writer driven by a table | -40..-50 | estimated |
| Pipes (`sys_pipe`, `pipe_read`, `pipe_write`, 7 tables) as a module | -250 resident | estimated; needs load-on-first-`pipe` policy, and `sh` pipelines use it |
| mkdir / rmdir / unlink / rename and their helpers as a module | -400..-500 resident | estimated; the same policy question |

**Sum of the rewrite rows (no policy change): about 0.8-1.1 KB, 7-10% of CODE+RODATA, 3-4 pool
pages.** The two module rows add about 650 bytes (2-3 pages) at the cost of a disk load the
first time `mkdir`, `mv`, `rm` or a pipe is used in a session.

## BSS (counts against the high region, which holds the cold code that frees the low one)

| Item | Bytes now | Possible |
|---|---|---|
| `p_save` (10 x 190) | 1,900 | in flight: under I/O (`feat/psave-io`) |
| `p_cwd` (10 x 48 strings) | 480 | keep the inode and device already in `p_cwdino`/`p_cwddev`, rebuild the string with `..` on demand: ~-400, +~80 of code |
| block cache `bufs` (6 x 256) | 1,536 | `NBUF=4` experiment exists: -512 on Classic, no loss with an REU cache |
| `rbuf`, `mt_path`, `p_name`, `p_fd` | 128, 128, 110, 80 | not looked at |

## What I would not do

- Banning undocumented opcodes: they are allowed. `experiments/illegal-ops` passes on the
  Ultimate (21 checks, 2026-10-31), and `sweep.s` (every stable op, every addressing mode,
  646 cases against a model) passes on VICE and on the Ultimate (2026-11-18). The saving is
  still small per site (`LAX`/`DCP`/`ISC`/`SAX`: a few bytes each), but it is free.
- Zero page (owner's rule: [`docs/roadmap.md`](../roadmap.md), "Zero page policy").
- (Struck: "reading ROM tables at boot saves nothing". Once `p_save` leaves the high region
  the high region has room, so a table copied into BSS at INIT frees low-region bytes, a page
  per 256. It needs a checksum guard for JiffyDOS and custom ROMs.)

## Reading of the result

The cookbook's biggest levers (return-address dispatch, fall-through, derived tables, shared
tails) mostly apply to this kernel in small doses: the routines are short, the mechanisms are
already compact, and the remaining waste is scattered over ~800 labels. A thorough rewrite
pass is worth **about 1 KB** in the low region without touching policy and **about 1.7 KB** with
the two module splits, i.e. 4-7 pool pages, or the same bytes as kernel room. The larger
numbers are in the high region (`p_save`, `p_cwd`, `bufs`: about 2.8 KB) and those are design
decisions, not tricks.

Speculative, not measured: a small byte-coded interpreter for the repetitive validate-then-act
sequences in `fs`/`file`/`cbm` (the same four-step check opens most syscalls) could beat shared
tails by another 5-10% of those three modules. It trades speed and debuggability; try it on one
syscall family before believing it.

## Small wins count

Features have landed for less than 100-200 bytes; a hundred here and fifty there is how two
pages come free. Judge each rewrite by bytes per hour of review, not by whether it moves the
total on its own. P1 (-39 B) is the unit of account.

## Transient ROM paging (not measured, constraints only)

Idea: bytes that cost no permanent address space. With IRQ masked and NMI safe, bank in a ROM,
copy or run a short sequence, bank it out.

- KERNAL ROM (needs HIRAM) hides `$E000-$FFFF`: the high region, BSS, CODEHI and the vectors.
  BASIC ROM (LORAM+HIRAM) hides `$A000-$BFFF`: the kernel low region. So the code doing the
  paging must live outside what the ROM hides (the `$CF00` page or the user pool), and NMI
  needs a stub reachable while the vectors are hidden (the ROM's own path goes through `$0318`).
- Cleanest use: read ROM data **at INIT** (keytab, the charset for `con`) into BSS and
  release the code; no run-time paging.
- Run-time use (executing ROM snippets) costs a trampoline plus a call-site cost that eats
  short-sequence wins; ROM revisions and JiffyDOS differ, so each use needs a checksum guard
  and a fallback copy, which cancels the gain unless the Classic tier keeps a fallback.
- The Ultimate/REU variant is a different design (overlay store) and breaks "core never
  requires an REU or an Ultimate".

## If it goes ahead

Per-module sessions (`blk`, `kbd`, `proc`, `file`/`fs`, `con`, `iec`), each with the plan,
change, review, hater-gate loop from the project rules; before and after `make size` in every
commit; `test-host` plus the targeted VICE tests per module and the full suite at the end
(the interrupt path, `proc` and `blk` are milestone-class changes). P1 is a safe first step: it
is verified, small, and in `blk`.

## Pass 2: structural findings (2026-11-18)

A second pass over main at 47f849e, read with the cookbook's first questions: which
information is duplicated, where state lives, and what the target gives for free.
`.blocks/routine-sizes.py` prints the size of every routine and table (from
`build/kernel.lbl` and `build/kernel.map`) and is what the figures below come from. Low =
below `$CF00` (1196 bytes free at 47f849e), high = below `$FFFA` (643 free). Cold code
moves from low to high, so a high-region byte is worth a low-region byte as long as cold
code is left to move.

| # | Finding | Region | Estimate | Status |
|---|---|---|---|---|
| S1 | **A page per process under I/O.** `$D000-$DFFF` RAM holds `p_save` (1,900 bytes at `$D040-$D7AB`), and `$D7AC-$DFFF` (2,132 bytes) is unused. The `$D800` cap comes from the simulators in `tools/`, which map `$D000-$DFFF` flat (`tools/test_psave_sim.py`); colour RAM is a separate chip, so on the machine that RAM is free. Give slot N the page `$D0+N`: the zero page save at 0, the stack at `ZPSAVE`, the cwd string at 192 (48 bytes), the name at 240 (11). `p_cwd` (480) and `p_name` (110) leave the BSS, and the two multiply loops (`cwd_ptr` *48, `slot_save_ptr` *190) become "page = `$D0` + slot". Cwd and name readers bank `$01` like `sched` does. Uses `$D000-$D9FF` and leaves `$DA00-$DFFF` (1.5 KB). The simulators must learn the `$01` banking first. | high | -590 BSS, about -50 code | done: high +676, low -8 (the windows are in CODE) |
| S2 | **`sys_return` in the `$CF00` page.** The page has 31 free bytes after `enter`; `sys_return` is 34 bytes in CODE. `need_resched` and `in_kernel` only hold 0 and 1, so `lsr` both tests and clears them (-7), and it fits. | low | -34 | done: low +31 |
| S3 | **The path pointer.** Seven syscalls `jsr set_pp_r0` and four copy `r0` to `pp` inline (`file.s:232`, `exec.s:137`, `cbm.s:128`, `cbm.s:359`). The inline ones become calls. Not done: copying `r0` to `pp` in `enter` for every syscall, which would also remove the seven calls, because a syscall that sleeps would then have its `pp` clobbered by any syscall, not only path syscalls. | low | -20 | done: low -4 (`namei_r0` moves to CODE), high +45 |
| S4 | **Page allocator.** `page_alloc` and `page_alloc_hi` are the same first-fit loop in two directions (about 120 bytes together); `total_pages` is the constant `NPOOL` kept in BSS. One loop with the step (`inx`/`dex`) as a parameter. `pg_used` (155 bytes, 0 or 1 per page) stays: a bitmap saves 135 bytes of BSS but costs about as much code in three places. | low | -40 | done: low +69 |
| S5 | **P1 needs a clamp.** The prototype in `experiments/size-spike/p1.s` keeps counting tracks past 35: block 700 becomes 37/0 and 720 becomes 38/3 (py65). `format` (`src/bin/format.s:161`) relies on the clamp to tell a 1541 from a 1581: on a 1581 without `/lib/km/d81`, 38/3 exists, so the probe takes the 1581 path and fails on block 1560 with a raw I/O error instead of saying to load the module. P1 also uses `tmp0-tmp2`, which the table version does not: each caller of `blk_to_ts` needs checking. With the clamp, about -35. | low | -35 | done with the clamp: low +34 |

Measured on `size/research` (`make size` after each step): low room 1196 -> 1318, high room
643 -> 1364, 843 bytes in all; the pool is unchanged at 155 pages. Proof per step: `make
test-host`; new py65 tests for the allocator (`tools/test_mem_sim.py`, a random walk against a
model) and the geometry (`tools/test_geometry_sim.py`, every block of 35 and 40 tracks); S1's
banking is checked by `tools/test_psave_sim.py`, whose guard now runs on a simulator that banks
the RAM under I/O by `$01` (`tools/uci_sim.py` `Mem.under`). After S1 a slot page is: saved
zero page and stack 0-189, cwd at `PCWD` (192), name at `PNAME` (240), all in `k.inc`;
`$DA00-$DFFF` stays free.

After merging `main`'s eject work (MAXPROC 10 -> 8, 3-byte syscall records and the eject gate in
`enter`): the `$CF00` page overflowed by 2 bytes; `enter` now sets `in_kernel` with `inc` (it is always 0
there), and the page is exactly full, so the next syscall needs room found first. Against `main`
0c060a4 (low 1149, high 687) the merged tree has low 1271, high 1290: 725 bytes, 118 fewer than
above because MAXPROC 8 already shrank the `p_cwd`/`p_name` arrays S1 removes. The slot pages are
`$D000-$D7FF`; init takes slot 7 and the shell slot 6.

Read and not pursued:

- Instruction n-gram duplicates over the kernel sources: the most common 4- to 8-instruction
  sequences repeat 3 to 6 times (`lda nm_dev / ldx nm_ino / jsr iget / bcs`, the `pp` copy).
  Apart from S3, each is worth a handful of bytes; they belong to the per-module sessions.
- The syscall records are three bytes with a spare `.byte 0` each (the index is `3n+2`).
  The 32 spare bytes are interleaved and only fit a per-syscall flag byte; no flag pays
  for its test in `enter` today.
- Running cold, pure-computing code (`build_path`, `relocate`) from the RAM left under I/O
  after S1, through a banking trampoline with interrupts off. Possible, but it puts
  interrupts-off spans in the shell's hottest path; worth it only if the high region runs
  out of cold code to take.
