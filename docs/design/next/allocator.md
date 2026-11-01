# Tagged-page allocator (design note, wave 2)

Status: paper. Nothing here has been built or run. Base: branch `next/contract-free` at 07bdd09 (code = a9b6acf, pool edge `$A100`). Citations are `file:line` in that tree. **V** = I read it (or ran `make size` on a scratch copy of the tree), **U** = inferred. Cycle counts are hand counts from the 6502 tables, not measurements.

## 1. Goals and non-goals

**Goals.** Turn `pg_used` (one byte per pool page, 0/1: `mem.s:10`, `mem.s:57`, V) into an owner tag, so one allocator serves:

1. process images, `brk`, `exec`,
2. block-cache buffers on idle pages,
3. modules and shared-library text (top-down, pinned),
4. pipes,
5. clean, refetchable overlay pages,
6. swap-out of blocked processes (Expanded/Recommended only),
7. the pool edge as run-time data (`memtop`, `meminfo`).

Classic (no REU) keeps working and never swaps. `mem.s` today: 159 B CODE, 19 B INIT, 158 B BSS (`make size`, V).

**Non-goals.** Memory protection; moving live pages (run-time pointers are not in the relocation table, so a process always returns to the same pages); per-page refcounts; paging inside a running process.

## 2. Tag encoding

```
bit  7    6 5 4    3 2 1 0
     H    class    owner
```

| Class | Tag | Owner nibble | Taken by the allocator? |
|---|---|---|---|
| 0 FREE | `$00` | must be 0 | (is free) |
| 1 PROC | `$10+s` | process slot 0-11 (`MAXPROC=12`, `k.inc:5`) | never |
| 2 OVL | `$20+s` | slot; clean page of that process | not in v1 (see 7) |
| 3 CACHE | `$30+i` | block-buffer index 0-15 | yes, by reclaim |
| 4 PIN | `$40+m` | module/library id 0-15 | never |
| 5 KERN | `$50+k` | 0 pipe, 1 cache floor, 15 LOADING | never |
| 6, 7 | - | reserved; the allocator rejects them | - |

**H** (bit 7) marks the home page of a swapped-out process. It is always 0 on Classic and until swap exists.

**Why free stays 0.** Several places fill with zero and stay correct unchanged:

- `mem_init` zero-fills `pg_used` (`mem.s:18-23`, V).
- `kmain` clears all kernel BSS (`main.s:122-144`, V).
- `page_alloc`'s test is `lda pg_used,x / beq` (`mem.s:40-41`, V).

The one rule change: a free writes `tag AND #$80`, not `#0`, so it keeps H. On Classic that is `0`.

**Two availability tests:**

- *Strict* (PIN, KERN): the page is available iff `tag == $00`.
- *Borrow* (PROC, CACHE): the page is available iff `tag AND #$7F == 0`. A borrower may sit on a swapped process's home, because PROC and CACHE leave that home again when they exit or are reclaimed.

The written tag is `new OR (old AND #$80)`.

## 3. API (all in `mem.s`)

| Call | In | Out |
|---|---|---|
| `page_alloc` | Y = n, A = tag | C clear: A = first page; C set: A = `ENOMEM`. Bottom-up first fit |
| `page_alloc_hi` | same | same, top-down (PIN, KERN) |
| `page_retag` | A = old, X = new | Y = pages changed (H kept) |
| `page_free_tag` | A = tag | `page_retag` with new = 0 |
| `page_tag` | A = page | A = tag; C set if outside the pool |
| `page_count` | A = tag | Y = pages with that tag |
| `cache_reclaim` (blk.s, called by mem.s) | X = buffer index | returns; no I/O |

**Reclaim protocol (the only callback).** `page_alloc` first accepts FREE pages only. If that fails, and the requester is not CACHE, a second pass also accepts CACHE pages. For each CACHE page in the chosen run it calls `cache_reclaim` (X = owner nibble) before retagging. Three rules:

1. **CACHE pages are clean at every instant.** Today's cache is write-through: `bwrite` writes at once (`blk.s:6`, `blk.s:259-299`, V) and `bflush_all` is a bare `rts` (`blk.s:302-303`, V). Anything dirty must be KERN.
2. **Reclaim is synchronous**, cannot fail, block or do I/O. In blk.s it is `lda #0 / sta b_valid,x / sta b_page,x / rts`, 7 B.
3. **No caller holds `bp` across `page_alloc`.** That holds for spawn: the header is copied to `hdr` (`exec.s:126-134`), `iget` copies the inode into `ci` (`fs.s:232-248`), and `fs_read` re-runs `bread` per block (`fs.s:739`), all V. It also holds for pipes (`file.s:719`, V).

Overlay eviction in v1 is the owning process loading another section into its own OVL area. It is not reclaim.

## 4. Algorithms and costs

**Scan.** `pa_mask` = `$FF` (strict) or `$7F` (borrow). `pa_acc` = `$30` in pass 2, otherwise `$FF`.

```
@l:   cpx #NPOOL        ; 2
      bcs @fail         ; 2
      lda pg_used,x     ; 4
      and pa_mask       ; 3 (zp)
      beq @ok           ; 2/3
      and #$70          ; 2  class bits
      cmp pa_acc        ; 3
      beq @ok           ; 2/3
      lda #0            ; 2  run broken
      sta pa_run        ; 4
      inx               ; 2
      bne @l            ; 3
@ok:  ...as today (mem.s:46-53): start/extend the run, compare with pa_n
```

**Costs.**

| Case | Today | Proposed |
|---|---|---|
| Used page | 21 cycles (`mem.s:38-45`) | 29 cycles |
| Free page | about 37 cycles | about 40 cycles |
| Full scan, 153 pages (`NPOOL = $A1-$08`, `mem.s:4-6`, V) | about 3.2k cycles | about 4.4k per pass, about 9 ms for both passes |
| Marking | 12 cycles per page | 20 cycles per page (`and #$80 / ora pa_tag`) |
| Reclaim, per CACHE page | - | about 40 cycles |

A near-full scan is small next to the 0.5 s block read that spawn does anyway (lens F).

**Top-down.** The same loop with `dex`: when the run reaches n, the start is X itself. A direction byte shares the code: about +18 B.

**Free all pages for a slot.**

```
page_retag:          ; A = old, X = new
      sta pa_old
      stx pa_tag
      ldy #0
      ldx #NPOOL-1
@l:   lda pg_used,x  ; 4
      and #$7F       ; 2
      cmp pa_old     ; 4
      bne @n         ; 3
      lda pg_used,x  ; 4
      and #$80       ; 2  keep H
      ora pa_tag     ; 4
      sta pg_used,x  ; 5
      iny            ; 2
@n:   dex            ; 2
      cpx #$ff       ; 2
      bne @l         ; 3
```

- **Exit cost:** 153 × 20 + 18 × 21 ≈ 3.4k cycles, about 3.5 ms, against about 280 cycles for today's 18-page `page_free` (`mem.s:76-91`). Exit is rare.
- **Sizes (U):** `page_alloc` about 70 → 100 B. `page_free` 22 B → `page_retag` 36 B plus a 4 B entry. `page_tag` 12 B, `page_count` 16 B. `meminfo` about 65 → 80 B. `mem.s` CODE **159 → about 250 B**, BSS +2.

## 5. What it deletes or replaces (byte accounting, U except where cited)

| Item | Today | After | Δ resident |
|---|---|---|---|
| `p_mpage`, `p_mlen` | 2 × 12 B BSS (`proc.s:18-19`, V) | tags | −24 B KHI |
| Exit free (`proc.s:369-372`, V) | 9 B | `lda #$10 / ora cur / jsr page_free_tag`: 7 B | −2 |
| `setup_proc` stores (`exec.s:465-468`, V) | 10 B | 0 (spawn allocates with `PROC(sp_slot)` directly) | −10 |
| `procinfo` size (`proc.s:596`, V) | 3 B | `page_count`: about 8 B | +5 |
| Fixed buffers `bufs` | `NBUF*256` = 1,536 B KHI (`blk.s:42`, `k.inc:9`, V) | 2 floor pages in the pool (KERN 1) plus up to 14 CACHE pages | **−1,536 B KHI** |
| `buf_idx_ptr` (`blk.s:196-203`, V) | `adc #>bufs` | `lda b_page,x`; `b_page` = 16 B | +16 BSS, ±0 code |
| Cache growth in `cache_victim` (`blk.s:349-383`, V) | - | if `free_pages > CACHE_LOW` and there are fewer than 16 buffers, `page_alloc(CACHE i)` FREE-only | about +30 |
| Variable `NBUF` loops (`blk.s:308,325,350,358`, V) | constant | `ldx nbuf` | about +4 |
| `reu_detect` scratch (`blk.s:613-645`, V) | uses `bufs` in INIT | uses the INIT load area or `cmdbuf` (`blk.s:60`) | 0 (INIT) |

**Net.** About +90 B code in `mem.s` and +40 B in `blk.s`, against about **−1,544 B of KHI BSS**. KHI has 183 B of room today (`make size`, V). The pool pays two pages for the cache floor plus whatever the cache borrows while pages are idle, and borrowed pages come back on demand.

**The floor lives in the pool** (512 B of pool, not KHI, which is the scarcer of the two), tagged KERN so pass 2 never takes it.

## 6. Interaction with the rest of the kernel

**Spawn.** The slot is chosen before allocation (`exec.s:89-98`, V), so the tag is `$10|sp_slot`. The failure path (`exec.s:216-223`) becomes `page_free_tag`. `k_entry` already holds the base in the saved context (`exec.s:539-544`, V).

**No switch during a load.** `block_on` is called only from the pipe, console, wait and sleep paths (`file.s:524,652`, `con.s:604,686`, `proc.s:472,538`, V), and the IEC paths busy-wait. So one LOADING tag (KERN 15) is safe.

**`exec` (lens A6).**

1. Allocate the new image as KERN 15.
2. Load and relocate it.
3. `retag(PROC s → 0)`, then `retag(KERN 15 → PROC s)`.

On failure: `page_free_tag(KERN 15)`, and the old image survives.

**`brk(A = n)`.** Find the top page tagged `PROC s` (scan down, about 2k cycles). Borrow-test the next n pages, reclaiming CACHE as `page_alloc` does. Tag them or return `ENOMEM`. About 45 B. Invariant: a process is one contiguous run. If lens A2 puts the save area in process pages, it goes at the bottom (open question 2).

**`meminfo` and `memtop`.** The first five bytes stay (`mem.s:93-119`, V). Appended: the pool's first and end page, the reclaimable (CACHE) pages, the largest strict run, the largest borrow run. `free_pages` counts FREE only. Programs size their heap from the borrow run, so `KSTART` (`k.inc:4`, `kernel.cfg:10`, V) stays a build constant that no program sees.

**Modules (lens C4).** `page_alloc_hi(PIN m)`; unload = `page_free_tag(PIN m)`; size = `page_count`.

**Shared library.** `PIN m` plus a refcount byte per id in the module table. Spawn increments it when CX v2 `libabi` names the library; exit decrements it through a `p_flags` bit (`proc.s:15`, V). Only a single library is designed here.

**Pipes.** `KERN 0`. `file.s:138` and `file.s:771` keep a thin `page_free(A = page, Y = n)`, about 18 B.

## 7. Eviction policy and swap

| Requester | Pass 1 | Pass 2 | Pass 3 (Expanded/Recommended) |
|---|---|---|---|
| PROC (spawn, `brk`, `exec`) | borrow test | + CACHE | swap a victim, retry |
| PIN, KERN | strict test | + CACHE | none: `ENOMEM` |
| CACHE growth | FREE only, while `free_pages > CACHE_LOW` (≈ 8) | none | none |

**Classic** stops at pass 2. Exhaustion is `ENOMEM` as today (`exec.s:184-186`, V), but idle cache pages now count as memory.

**Measured transport** (hardware session, as relayed to this note):

- UCI `LOAD REU` moves a 32 KB file into the REU in about 6 ms, about 5 MB/s.
- Byte reads through the UCI register run at about 16 KB/s.
- REU↔C64 DMA moves 1 byte per cycle: 256 cycles per page, about 4.7 ms for an 18-page `sh`.

So **the REU is the backing store, and UCI only fills it in bulk.** A 4.6 KB image through the register would take about 0.3 s (U, assuming writes run at the read rate).

**Refetch recipes.** A page is *clean* when its bytes equal a copy elsewhere:

- **(a)** an REU copy: refetch is one DMA, 256 cycles per page;
- **(b)** file + offset + relocation: refetch is a disk read plus a relocation pass.

On Expanded and Recommended, the loader stashes the *relocated* program and overlay pages to an REU staging area at load time (256 cycles per page), so OVL pages get recipe (a) and are never relocated again. On Recommended, staging a CX file is one `LOAD REU`; the register path is never used, and the relocation runs once over the DMA'd copy. Classic has only (b): an overlay switch re-reads the file (about 0.55 s per block, lens F), and OVL pages are never lent out.

**Stretch: lending clean OVL pages.** Only with recipe (a). A lent page keeps H, because its owner needs that exact page back. The next `SYS_OVLOAD(n)` waits until the page is free, then DMAs it in.

**Swap.**

- **Victims:** `PS_BLOCKED` on `CH_CHILD` or `CH_KEY`, not `cur`. The typical case is `sh` waiting on a big child (lens A, S1).
- **Never swapped:** `cur`, zombies, READY processes, and init while it is the only other process.
- **Swap-out:** PROC pages are DMA'd to REU swap banks next to the cache (`blk.s:21-33`, V). OVL pages with recipe (a) are not written. The swap record (home run, slot) lives in the slot's REU area; the resident cost is a 2-byte `p_swapped` bitmap. Pages become `$80`.
- **What does not move:** the save area, `p_save` in KHI (`proc.s:31`, V), which holds the ZP image and the stack slice, including the blocked syscall's kernel frames (`proc.s:3-7`, V). If A2 moves it into process pages, it travels with them, which is still correct because the process returns to the same addresses.
- **Swap-in:** a woken swapped process is READY but skipped by `sched`. At each `sched`, and when a page is freed, the kernel checks the home run. It proceeds if every page passes the borrow test, is CACHE, or is held by a swappable blocked process. It then swaps the holder out, DMAs this process in, and recomputes H from the remaining records (homes can overlap).
- **Deadlock and starvation:** a home held by a READY CPU-bound process means the swapped process waits until that process blocks or exits. That is never worse than Classic, which would have refused the spawn. The strict test for PIN and KERN means a `mount` or a pipe can never strand a swapped `sh`. With no victim available, the result is `ENOMEM`.
- **Signals:** `proc_exit` runs in `cur` context (`proc.s:333-397`, V), so in v1 a killed swapped process is swapped in to die (open question 4).

## 8. Migration in buildable steps

Each step is one commit; "smoke" means `make test-smoke` plus `make test-host`.

1. **Floor experiment.** Set `NBUF=2` (`k.inc:9`) and run `Boot.test_05/07/10/19/24`, `Drives.test_cbm_disk`, `Persistence`, and `Cache` with `CACHE=0`. This proves a floor of two buffers is enough, or names the path that needs a third. Revert afterwards.
2. **Tags, old behaviour.** `page_alloc` takes a tag; frees write `AND #$80`. Add `page_retag` and `page_count`; switch exit and `procinfo` to them; delete `p_mpage`/`p_mlen`. Tests: smoke, `Boot.test_08/12/13/15/22`.
3. **`page_alloc_hi` and `meminfo` v2**, updating `free.s` and `uptime.s` (the `SYS_MEMINFO` users, V by grep). Tests: smoke, `Boot.test_22`, and a host-side allocator model (see 9).
4. **Cache in the pool.** Add `b_page`, the KERN 1 floor, growth, reclaim and pass 2; drop `bufs`; quote `make size`. Tests: `Cache`, `REU`, `Persistence`, `Drives`, `Boot.test_15/19`. This is a memory-map change, so it is a **milestone**: the full suite with stock ROMs, then the disk and bus tests with JiffyDOS.
5. **`exec`/`brk`** (with A6 and M3, after the syscall-page work). Tests: `Boot.test_25`, `test_24`.
6. **Modules** (C4). Tests: devzero load/unload, `free` before and after.
7. **Swap and REU staging** (wave 4). Tests: `REU`, `Cache.test_small_reu`, a new `-reu` pressure test; the UCI `LOAD REU` path on hardware.

## 9. Risks and adversarial review

| Corruption | Failure scenario | Mitigation |
|---|---|---|
| Reclaim with `bp` live | a future `brk` inside an fs path gives a process a page that the fs then writes to disk as a block | rule 3; pass 2 skips `b_idx` (`blk.s:49`), +6 B; a debug build poisons reclaimed pages |
| Dirty data in CACHE | a write-back module keeps a dirty block in a CACHE page; reclaim loses the write | CACHE means clean; write-back must be KERN with its own flush |
| H lost | a habitual `lda #0 / sta pg_used,x`; a module lands on a swapped home; swap-in overwrites it | frees only via `page_retag`/`page_free`; a host grep test: no `sta pg_used` outside `mem.s` |
| Bad owner | `ora cur` with `cur=$FF` at boot (`main.s:150-151`) gives `$FF`, pages never freed | `spawn_kernel` uses `sp_slot`; the debug build asserts class < 6 |
| Shared LOADING tag | two concurrent `exec`s both use KERN 15 | impossible today (section 6); if loads ever block, give LOADING a per-slot owner |
| Overlapping homes | a stale H lets a borrower be overwritten at swap-in | recompute H before each swap-in; the host model covers overlap |
| IRQ writes into a swapped process | an interrupt stores into a blocked process's buffer | U: none found; audit `con.s:604-686` before step 7 |

**Evidence.** A Python host model of the tag rules (random alloc/free/retag/reclaim/swap) with three invariants: one owner per page; `free_pages` equals the count of `$00`/`$80` pages; no PIN or KERN page on a home. Under VICE, after `Boot.test_15`, read `pg_used` through the monitor: an exited slot's tag must be gone.

## 10. Open questions

1. Is a floor of 2 buffers enough? (Step 1 decides.) Is a maximum of 16 buffers (the owner nibble) the right cap?
2. If the save areas move into process pages (lens A2), do they go at the bottom of the run, or in a separate PROC page?
3. Refcounting more than one shared library: a per-process library mask (12 B), or one library only?
4. Can `proc_exit` be made to work on a non-current slot, so killing a swapped process does not swap it in?
5. Does UCI `LOAD REU` support an offset or a partial load, so one overlay section can be staged without the whole file? The measurement was a whole 32 KB file.
6. Should the reserved classes 6 and 7 hold a future "dirty write-back" class with a flush callback, or stay rejected?
