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

- Undocumented opcodes: `experiments/illegal-ops` passes under VICE only; the Ultimate result
  is the gate. `LAX`/`DCP`/`ISC` would save a few dozen bytes at most.
- Zero page (owner's rule: [`docs/roadmap.md`](../roadmap.md), "Zero page policy").
- Reading the KERNAL ROM tables at boot to avoid shipping `keytab`: it moves 256 bytes from
  the low region to BSS, saves nothing, and the ROM may be JiffyDOS or custom.

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

## If it goes ahead

Per-module sessions (`blk`, `kbd`, `proc`, `file`/`fs`, `con`, `iec`), each with the plan,
change, review, hater-gate loop from the project rules; before and after `make size` in every
commit; `test-host` plus the targeted VICE tests per module and the full suite at the end
(the interrupt path, `proc` and `blk` are milestone-class changes). P1 is a safe first step: it
is verified, small, and in `blk`.
