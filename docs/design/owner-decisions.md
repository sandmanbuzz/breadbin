# Decisions for the owner

> **Historical (2026-11-23): a 2026-11-04 decision pack. CP2 is closed, NBUF is an approved experiment, the BRK kill and `$?` landed; the roster it cites is gone. Open items live in `docs/wip.md`.**

A pack of the decisions the owner holds, one section each: the evidence and where it comes from, the options, the cost in bytes or pages, and a recommendation. Nothing here is decided; the owner decides. Sources are the design notes on main and the fleet roster (`fleet-store:fleet/roster.md`, post dates given). A figure with no source I could find is marked **unverified**. Written 2026-11-04.

Room, as of the R17 measurement (roster, 2026-11-04, main ba69ca4): kernel room below `$CF00` 361 bytes; room above BSS and CODEHI 14 bytes; pool 154 pages, `$A200`. The policy keeps about one page of kernel headroom, so about 105 bytes are usable (`docs/wip.md:92`). Each pool page is 256 bytes of TPA at every prompt.

---

## 1. CP2: merge B's shell buffer change (21 versus 20 pages)

- **Evidence.** The criterion is in the backlog: "the criterion of at most 22 pages is already met on main at 21" (`fleet/backlog.md`, CP2 line). B's R17 table (roster, 2026-11-04): pool pages in use at the idle prompt are **21 on main ba69ca4 and 20 with B's `feat/cp2-sh-bss` change**; room below `$CF00` stays 361 and above the BSS 14; the sh CX size is 3,682 bytes in both. B's earlier CP2 post (roster, 2026-11-03, "CP2 on feat/cp2-sh-bss, not merged, held for the user") also holds the branch.
- **Options.** (a) Merge `feat/cp2-sh-bss`: one page back at every idle prompt, no room change. (b) Leave it unmerged: CP2 stays open at 21 pages, which the criterion already accepts.
- **Cost.** None in kernel bytes (the change is in sh's BSS: -128 bytes). One page of TPA is returned.
- **Recommendation.** (a). The criterion is met either way, and the change is free in room; the decision is whether the page is worth a merge now. The backlog holds it for the owner.

## 2. STKSAVE value (96 proposed)

- **Evidence.** `STKSAVE` is 130 bytes on main (`docs/design/next/modules-v1.md:23`; `k.inc:16` per `docs/design/research/next/E-baseline.md:118`). B's `feat/footprint-b-save-jtab` proposes 96 (commit b5d3654, roster 0d9a05 post, 2026-11-03, with the correction that the earlier commit had kept 130). Its after-state, per B's roster post: room below `$CF00` 358, BSS room 422, proc BSS 2,907 (from 3,315), idle pool pages 21 unchanged. The stack-reset commit `fd997b3` ("stack reset before the overflow kill") is on the same branch. Cycle cost: D measured the stride loop at **776 cycles against 184 worst case** per switch (roster, D's review, 2026-11-03); B's estimate was about 600 against about 60, not measured. `cx2-abi2.md:37` makes the user stack limit `STKSAVE` minus 48. The space pass on that branch is not merged.
- **Options.** (a) 96: 34 bytes less save area per process, a user stack limit of 48 bytes less, and the cycle cost above. (b) 130: the current value, no change to the user stack limit.
- **Cost.** Space: 34 bytes of save area per process (the BSS figures above). Time: the cycle figures above.
- **Recommendation.** Decide it with the user stack limit it sets. D's measurement is the one to rely on: 776 cycles per switch is a real cost, not the estimate. If the owner accepts the lower user-stack limit, 96 is sound; otherwise keep 130.

## 3. NBUF, NFILE and NPIPE

- **NBUF (block cache buffers).** 6 to 3 saves 768 bytes of KHI, or the buffers can come from idle pool pages (`docs/design/next/tpa-recovery.md:21`); the fixed buffers are `NBUF*256` = 1,536 bytes (`allocator.md:142`). The floor experiment (`NBUF=2`) is written up in `allocator.md:217` and not yet run. B's roster post (R17) and C's R10 post both call NBUF 6 to 3 the largest lever and unproven, since the cost to classic disk speed is not measured.
- **NFILE and NPIPE** (B, roster, 2026-11-03, from A's f_type dumps on the create-probe build). Idle prompt: 1 of 24 file entries in use (the console). A blocked three-stage pipeline (`cat | cat | cat`): 5 in use. A five-stage pipeline needs four pipes, which is 9 in use, so NFILE 24 is not tight for shell use. The tighter limit is **NPIPE 4**, which caps pipes system-wide before NFILE does. Price of growing NFILE: each entry is **9 bytes of BSS** across nine arrays (`f_type`, `f_ref`, `f_flags`, `f_dev`, `f_ino`, `f_pos0-2`, `f_pipe`), so 24 to 32 costs 72 bytes, past the 14-byte BSS margin.
- **Options.** (a) Run the NBUF=2 floor experiment before choosing a number. (b) Take the buffers from idle pool pages (the allocator note's version). (c) Raise NPIPE, the binding limit, before NFILE; each NFILE entry costs 9 bytes of BSS that the margin does not have.
- **Recommendation.** (a) first, since NBUF is the biggest lever and has no measured floor. For NFILE and NPIPE: leave NFILE at 24 (not tight), and decide NPIPE only if a shell pipeline above four stages is wanted, because it is the limit that bites first.

## 4. The seven CP3 decisions

From `docs/design/next/cp3-spec.md` section 9. Each is the owner's to answer.

1. **CP1 target versus CP3 cost.** CP1 needs room of at least 300; CP3 in full leaves about 168, a minimal build about 232. Which gives: the target, the probe's key 0, or the order (CP3 after more space is found)?
2. **Op numbering.** CTL op numbers are permanent ABI. The spec adds op 8 MODULE, which cx2 section 2.4 lacks. Accept the addition?
3. **CX version.** Not bumped in this spec; fold the bump into CP4 with the CX v2 trailer. Accept?
4. **"sched skips save and restore"** is in the CP3 row of `checkpoints.md` but not specified in CP3. Keep it in CP3's exit criteria, or move it to its own checkpoint?
5. **RESTORE** kills the foreground set, as RUN/STOP does; the shell survives. Accept? The alternative kills the shell, which logs the user out.
6. **"User BRK"** means the 6502 BRK opcode (a user-mode BRK kills the process). The memory `brk` syscall is CP5. Accept that reading?
7. **SYSINFO key 0.** Minimal now (3 bytes: `abi`, `nsys`, `nctl`) and extended later, or with `tier` and `kver` now?

Decided in the draft, not asked: slots 24, 30 and 31 stay ENOSYS holes; CONMODE keeps ignoring the fd (`cp3-spec.md` section 9).

## 5. Feature priority: BRK kill, RESTORE kill, shell `$?`, the line editor

Sources: `docs/design/feature-priority.md` on main, the R10 post (roster, C, 2026-11-03, landed 4d46120, which re-priced it in byte-equivalents of 256 per page), and its section 6.

- **BRK-opcode kill: 19 bytes** (16 + 3; `cp3-spec.md:72,84`). Value per byte 21. A BRK panics today; the kill is "the one thing a user cannot get from the shell".
- **RESTORE kill: 24 bytes** (21 + 3). Value per byte 8. RUN/STOP already kills the same set, so its value is small.
- **Full CP3: 186 bytes**, effectively a page of kernel room under the headroom policy.
- **Shell `$? && ||`: 0 kernel bytes, about one page of shell** (0.2 to 0.25 KB pool; `shell-operators.md:26`). Value per byte about 1.6. The register is free: `sys_wait` already returns the child's exit status in X (`src/kernel/proc.s:460`). The cost is in the shell and the programs: the shell must keep the value, programs that end in `rts` (cat, ls, wc, head) need a status, builtins and a failed spawn have no status, and there is no `false` program yet (C's R10 post, feature-priority section 6).
- **Line editor:** TAB first, +1 to 2 pages; history halves the value per cost. Value per byte about 1.0 for TAB only (R10 post).
- **Options.** The order in R10: (1) BRK kill, (2) shell `$?`, (3) line editor; or another order the owner sets.
- **Recommendation.** BRK kill first, standalone: 19 bytes buys the one thing the shell cannot give a user. The R10 post's own order is the same, with `$?` second because it costs no kernel bytes.

## 6. The create-path probe (21 bytes) and the full fix (88 bytes)

- **Evidence.** B's roster post (2026-11-03, `fix/create-entry-first` at `b7b1c91`, local). The fault: NFILE exhausted on `O_CREAT` leaves one inode behind; a failing test (`tools/test_nfile_sim.py`) is red before and green after. The full fix takes the entry first and frees the inode on failure: **88 bytes**, room below `$CF00` 361 to 273, BSS room 14 to 12, sharded suite 74 of 74 PASS on `b7b1c91`. Facilitator hold: 88 bytes is below the CP1 target of 300 and takes 2 of the 14 BSS margin bytes, so it is not landed. The probe is on `4eb9ece` (build-only, not for landing), priced at **21 bytes** in the same B post; B was trying a cheaper probe-first fix (target about 25 bytes or less).
- **Options.** (a) The probe only, 21 bytes: detects the fault and answers whether the full fix is needed. (b) The full fix, 88 bytes: changes the create path, untested on the `dir_add` and `iget` failure paths (read only).
- **Recommendation.** (a) first, if it localises the fault, since 21 bytes is cheap and reversible. The full fix waits for the owner's room decision, because 88 bytes is a third of the usable headroom.

## 7. S12b timing: `brk(n)` and the space pass

- **Evidence.** S12b is `brk(n)` in resident kernel code, "only if a program must size its memory at run time" (`docs/design/s12-brk.md:29`). Its total is about 80 to 100 bytes against 354 free when that note was written (`s12-brk.md:49`; room is 361 now). The note leaves open "whether S12a goes first (recommended: no kernel bytes) and whether S12b waits for the space pass" (`s12-brk.md:64`). The priority table ranks it 2 (`feature-priority.md:31`). Value per byte about 2 to 5 (R10 post).
- **Options.** (a) S12a first (no kernel bytes), S12b after the space pass (M0-7); (b) S12b now, 80 to 100 bytes.
- **Recommendation.** (a): S12a costs no kernel bytes, and the space pass decides where the room goes before S12b spends any.

## 8. Q4: disk-full

- **Evidence.** Q4 is the error set open in the UCI v1 spec: mkdir on an existing name, rmdir of a non-empty directory, DELETE of a directory, delete of a missing name, disk full, rename onto an existing name (`docs/design/next/uci-v1.md:214`). `docs/wip.md:39` says disk-full is "the owner's to run". The backlog lists it as a standing item (`fleet/backlog.md`, CP2 line).
- **Options.** The owner runs the disk-full case on the Ultimate with a full scratch image, never the physical disk; the Q4 errors are specified from the result.
- **Cost.** Test time on the Ultimate, not bytes.
- **Recommendation.** Run it on a scratch image. The hardware notes ask for expendable media for anything that writes (R8 and R13 entries in `docs/hardware-notes.md`).

## 9. Delete the lease-broker files

- **Evidence.** C's R9 post (roster, 2026-11-03), landed as the docs/ci.md change (main 2048e78, local): the lease-broker section of `docs/ci.md` is retired, and the files are **kept for the owner, not deleted**: `tools/ci/broker.py`, `tools/ci/lease`, `tools/ci/run-broker.sh`, `tools/ci/test_broker.py`, the `BREADBIN_BROKER` pass-through lines in `tools/ci/run.sh`, and the macOS and host-VICE recipes in `docs/testing.md` (kept as history). The original proposal is `docs/design/research/next/SYNTHESIS.md:77-78`, where per-run containerised VICE may make the `vice` lease unnecessary.
- **Options.** (a) Delete the four broker files and the `run.sh` pass-through lines. (b) Keep them until the containerised VICE run makes them unnecessary.
- **Recommendation.** (b), until the owner confirms the containerised run has replaced the `vice` lease. C's post already gives the list, so the deletion is one commit when decided.

---

*Recommendations are one agent's reading of the sources above, not decisions. Where a figure is marked unverified, the decision should wait for the branch that holds it.*
