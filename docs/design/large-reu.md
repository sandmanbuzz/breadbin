# What a full-size Ultimate REU could buy us (brainstorm, 2026-11-18)

Status: speculation. Nothing here is built, scheduled or measured; no kernel code was read for it beyond the notes cited. It records a conversation with the owner so the ideas are not lost, and ranks them. It adds no work to `docs/wip.md`.

## Premise

The Recommended tier (`docs/roadmap.md`, "Platform tiers") is an Ultimate with UCI, a large REU and turbo. The REU can be up to 16 MB: 256 banks of 64 KB. Today we use 2 MB on the hardware, and the block cache takes banks 8-10. The roadmap already says to extend detection from 8 MB to 16 MB; the REU RAM disk is capped at 2048 blocks by the drive cache's banks (`docs/roadmap.md`, "Block devices").

Sizes to keep in mind: the pool is 155 pages (39,680 bytes), so 16 MB is about 420 whole pools. An idle prompt holds about 23 pages (init 5, sh 18), so a typical *used* image is a few KB.

**More REU does not make what we already do faster.** The cache working set (a boot drive's blocks) saturates at 2 MB, which already holds about a dozen d64s. Past 2 MB only features whose working set scales gain anything: process images, files, history, scrollback.

## Timing: the DMA cost, and turbo

REU DMA halts the CPU for the length of the transfer. On a real REC that is about one byte per 1 MHz cycle, so one pool pass is about 40 ms, and that stall is the same class of hazard as the harness DMA that confounded the IEC stall work (`docs/design/io-attack-log.md`): a halt inside a serial transfer can corrupt or stall it.

Owner's point (2026-11-18): a machine with a 16 MB REU is a Recommended-tier machine and will run in turbo, almost certainly at the maximum (48 or 64 MHz), because no intermediate speed has a reason to exist. At that clock a cycle is very cheap in wall time, so large-REU features may require turbo and the DMA pain shrinks. That is plausible, with two unknowns that decide whether it holds:

- **Does DMA speed follow the CPU clock?** Unmeasured. `docs/hardware-notes.md` shows CPU-bound BASIC speeding up with turbo (257, 64, 15, 5 jiffies at 1, 4, 16, 48 MHz) but disk and boot times not changing at all, so the bus side is held to 1 MHz; the REU engine is a different thing and we have not asked it. If it scales, a pool pass is under a millisecond and most of the cost concerns below vanish. If it stays at 1 MB/s, the latencies in this note stand.
- **The IEC bus does not get faster with turbo** (`docs/roadmap.md`, "Turbo"). A multi-millisecond halt in the middle of a byte on the bus is still a hazard however fast the CPU is, so any large DMA is issued at syscall boundaries with the bus idle, chunked where it cannot be.

**Experiment E1 (hardware session; not run).** On the Ultimate, REU of 16 MB, turbo at off, 4, 16, 48 and 64 MHz: time stash, fetch and swap of 4 KB and 40 KB with a CIA timer (not jiffies, not a timer under `SEI`: see `docs/process.md`, "Measure before deciding"), once with the bus idle. Also check that the REC swap command (exchange of the two sides in one pass) works on the Ultimate's REU as the 1700 documents it. Answers: the real latency of everything below, and whether large-REU features should be gated on turbo as well as on REU size. Everything else in this note waits on it. It belongs in `docs/hardware-notes.md` (the hardware session's file), not here.

## Ideas, with takes

Much of this is already on paper; the point of a large REU is mostly that those designs get room. Cross-references name the existing notes so we do not design anything twice.

| # | Idea | What the REU adds | Existing note | Take |
|---|---|---|---|---|
| 1 | **Process swap, job control** (Ctrl-Z, `fg`, `bg`; a resident editor you pop in and out of; `exec` that resumes instead of reloading) | Swap moves only the pages a process uses (about 5 KB for `sh`, so about 5 ms at 1 MB/s, not 40), and 16 MB holds hundreds of images | `docs/design/next/allocator.md` (tag bit H for a swapped home), `docs/design/job-control.md`, upstream `3ad7236` (`docs/design/upstream-survey.md`) | The one that changes what the system is. Cooperative (at syscall boundaries; no MMU, no moving live pages). Needs the allocator (CP5) and the stop state (CP3 and later); not first. |
| 2 | **Banked memory for user programs**, XMS-like: alloc, free, copy in and out by handle, freed at process exit | Capacity. The REU has no mapping, so this is copying, not true EMS | none; new | Cheapest new surface, and the foundation of idea 1 (same driver, same bank owner). Enables sort, a paged editor, `grep` over large input, larger pipe buffers. Pick for first prototype. |
| 3 | **`ramfs` as a kernel module** (`/tmp`, scratch) | Unbounded files in practice | roadmap "Block devices" (2048-block cap); module pattern in `docs/design/next/modules-v1.md` | Small, and a good fit for `/lib/km`. Needs wider inode numbers and geometry in the superblock (roadmap) or a non-block backend. |
| 4 | **Virtual consoles and scrollback** | Screen, colour RAM and VIC state are about 2 KB per console; scrollback is cheap | checkpoint 7 ("2 virtual consoles"), screen save and restore | Nearly free once a stash and fetch primitive exists. Pure feel, no capability. |
| 5 | **REU-resident `/bin` and overlays, modules loaded from the REU** | `exec` of any command at DMA speed; the cold kernel and modules paged in on demand | roadmap S8, S11b; `docs/design/next/cx2-abi2.md` (overlay table); kernel room pressure (`docs/roadmap.md`) | Real value for kernel room, but the pager itself costs resident bytes, and the block cache already gives most of the exec speed. After the size pass, not before. |
| 6 | **Sample playback and bitmap frame stores** (`play`: REU to `$D418` with a fixed C64 address, paced by a timer; page-flipped bitmaps) | Capacity and DMA streaming | checkpoint 7 ("per-tick user callback and a `play` command") | Fun and a demo, not a story. Needs the DMA rate under turbo, and VIC timing is not changed by turbo. |
| 7 | **Bigger or write-back cache, many drives cached** | Little: it saturates (see Premise) | `docs/design/write-back-cache.md` | Not a reason for a big REU. Skip as a driver of this. |

Unknown, worth a look and not claimed: whether the REST or UCI APIs let the host read or write the REU (preloading it at boot, saving it across a power cycle, filling it from a file at network or card speed). That would turn the REU from a cache into a place where `/bin` and a ramfs survive resets. It was not researched; see "Open questions".

## GeoRAM

The Ultimate offers GeoRAM, but it is exclusive with the REU (owner, 2026-11-18). GeoRAM is a real mapped window (256 bytes at `$DE00`, two bank registers): no DMA, no CPU halt, true EMS semantics, and upstream used it for `/tmp` (`docs/design/upstream-survey.md`, rejected there because the core never requires an REU). Against it: no bulk DMA at all (every byte moves through the CPU), no swap-in at DMA speed, and our block cache, the UCI `LOAD_REU` staging and `docs/design/next/cx2-abi2.md` all assume REU DMA. Moving to it later is a very large structural change; it is not recommended now. The only thing worth doing now is to keep a banked-memory API (idea 2) in terms of handles and copies, so that a different backend could implement it; that is a shape, not an extension point to build.

## Pick and order

1. **E1** first: a short hardware experiment, no kernel change; it prices everything else.
2. **Banked memory (idea 2)** as the first prototype, once the single control syscall of checkpoint 3 exists, with a bank allocator owned by one module (the cache's fixed banks 8-10 become a client of it). It is the smallest new surface and the base for 1 and 3.
3. **`ramfs` (3)**, then **process swap and job control (1)** on the allocator (CP5). Virtual consoles (4) whenever convenient.
4. Hold 5 to 7.

Features sized for a big REU are gated by a probe of the REU size (as in `docs/roadmap.md`: "each capability has a probe and a fallback"); whether they also require turbo waits on E1. None of this touches Classic or Expanded: the core still never requires an REU or an Ultimate.

## Open questions

- E1 above (DMA rate under turbo; swap command on the Ultimate).
- Host-side access to REU contents over REST or UCI (unresearched).
- A bank map: who owns which banks of 256 (cache, ramfs, swap, handles) and whether it is static by REU size or allocated; the first cut can be static.
- Whether a swap pass is allowed while an interrupt-driven transfer is in flight (no: syscall boundaries only) and what happens to a signal that arrives during one.
