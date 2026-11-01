# Checkpoints: proposed stopping points for a loose sprint (f7, 2026-11-01)

Not MVPs: each is a point where the tree is clean, the claims are measured, and stopping costs nothing. Built from `docs/design/research/next/SYNTHESIS.md`, `REV2.md` and the notes in `docs/design/next/`. "Pages" are pool pages at an idle prompt (`free`) or `KSTART`; every exit criterion names the command that proves it. `main` may be red between checkpoints; at a checkpoint it should be green on the named tests. Opus-heavy items are marked (O) so they can be scheduled away from a window that is nearly spent.

| # | Checkpoint | Exit criteria (measured) | Depends on | Notes |
|---|---|---|---|---|
| **0** | **Done: dev unblockers** | UCI v1 mounts and runs on the real Ultimate (Agent 2's run); module loader + `hello.km`; design notes (allocator, CX v2/ABI v2, UCI v1, modules, exec, TPA recovery) | | landed on main |
| **1** | **Modules repay the loan** | `cbm.km` loads at the first CBM mount; `uci.km` loads only on `mount uci`; `KSTART` back at or above the post-footprint value (pool >= 153 pages = 39,168 B, i.e. more than the fork's 120); Modules + Drives (cbm) + UCI sim green; `make size` room >= 300 B below `$CF00` | cbm.km (Agent 3), uci.s as a module (seam: the `bmi` dispatch sites become the ops row) | the point of the whole loan; biggest TPA step |
| **2** | **Idle footprint** | `SP_EXEC` implemented (exec.md); login `exec`s sh; `free` at an idle prompt shows <= 22 pages in use (was 28-30); Exec test class green; `Boot.test_15` updated | CP1 for room; exec.s/proc.s (Agent 3); sim tests (f7) | the user-visible memory win; kernel change, so full suite + JiffyDOS |
| **3** | **Contract tidy (ABI v2 foundation)** | one control syscall absorbing ISATTY/CONMODE/CACHE/DISKIO; a `sysinfo` version/feature probe; user `BRK` and RESTORE kill the process instead of panicking; `sched` skips save/restore when it picks the same process; CX version byte bumped (old binaries fail ENOEXEC, not crash); all in-tree programs rebuilt | CP2 (exec is one of the freed slots) | cx2-abi2.md section 6 has the commit list; (O) for the spec review |
| **4** | **Smaller programs** | CX v2 (trailer + delta relocs); error strings out of `err.o`; buffered stdout in the lib; exec reads past the block cache; `/bin` <= ~170 blocks (was 233); cold-boot bus reads measured (`make CACHE=2`, `cache stat`) before and after | CP3 | disk and boot time, Classic-visible |
| **5** | **Memory allocator** | `NBUF` experiment decided; tagged `pg_used` (owner/class); block cache buffers from idle pool pages; `brk`/`memtop`; `edit`/`as` size their buffers from `memtop`; pool edge no longer hard-coded in `prog.cfg` | CP3; allocator.md steps 1-4 | milestone-size change (memory map): full suite, JiffyDOS, hardware list |
| **6** | **Fast dev loop (Recommended tier)** | exec from `/u` works; LOAD REU staging for program loads and the REU cache fill (pristine images only); shared library as a relocation class; an edit-assemble-run loop under 15 s on the Ultimate | CP4, CP5; UCI hardware numbers (have them) | the roadmap's S15 target |
| **7** | **Cooler** | kernel line editor with history; screen save/restore (`edit`/`more` return to an intact screen); blanker; per-tick user callback + a `play` command; `turbo` command; 2 virtual consoles | CP3 (ctl call), CP5 for room | each item is independent; pick by wow-per-byte (D-console-cooler.md) |
| **8** | **Stable-cut decisions** | filesystem decision for Classic (keep c64fs v1 / v2 / other) made after living on UCI; physical-1541 root-mount reliability (deferred, not blocking until here); full suite + JiffyDOS subset + hardware list on one commit; hygiene pass (no `.o`/`.bin` tracked, no absolute paths) | all | release tag candidate |

## Suggested order and scheduling

1 -> 2 -> 3 are the spine; 4 and 5 can interleave (4 is lower risk, so first if the window is short). 7 items can be taken by anyone at any time once CP3's ctl call exists. Opus-heavy runs worth doing only with a fresh window: the CP3 spec review, the CP5 allocator review (hater), and CP6's shared-library design. Everything else is Sonnet-sized or hand work.

## What each checkpoint buys if the sprint stops there

CP1: more TPA than the fork with UCI available. CP2: the same OS uses ~6 pages less at every prompt. CP3: a contract we can extend without fighting the full syscall page. CP4: faster boots and loads on a stock 1541. CP5: memory that adapts. CP6: the Ultimate pays off. CP7: it feels like an OS. CP8: something we can tag.
