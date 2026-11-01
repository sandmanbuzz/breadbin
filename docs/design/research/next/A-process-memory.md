# Lens A: process and memory model, for breadbin-next

Code read: the `footprint` worktree (`.claude/worktrees/reu-cache`), working tree including the uncommitted edits (pool edge `$A100`, `jsr enter` syscall entry, `CODEHI`). Those edits are still changing. Measurements come from a copy of that tree built in the scratchpad (`make`, ld65 maps, the CX headers). Tags: **V** means I read or ran it; **U** means inferred.

## 1. Executive summary

1. **Keep the model:** page-relocated CX, every process resident, preemptive round robin with copy-in/copy-out of ZP and stack. On a 6502 the alternatives (ZP banks, fixed stack slices, position-independent code, cooperative scheduling) cost more than they save.
2. A context switch costs about **3,300 cycles (about 3.3 ms)**. That only matters in one case: a lone CPU-bound process still pays a full save and restore every 3-tick slice, wasting **about 6% of the CPU**. A 10-byte fast path fixes it.
3. **The biggest memory win is the library, not the switch.** About 27.5 KB of the 45.6 KB of `/bin` image bytes are statically linked library objects (V, ld65 maps). A shared library at a fixed `$0800` saves about 1 KB of RAM per resident process, about 4 disk blocks per exec (about 2.2 s on the standard bus) and about 26 KB of the 170 KB disk.
4. **Move the 2,304 bytes of save areas out of kernel BSS** and into each process's own pages. Kernel BSS has 183 bytes of room. The pool pays about 0.75 page per process.
5. **The syscall page is nearly full:** `JUMPTAB` is 242 of 256 bytes (V), so only 2 more syscalls fit. exec, brk and ovload all need slots. Move `sys_lo/sys_hi` out of the page first.
6. **The ZP re-split is the compiler enabler:** programs get up to 64 bytes instead of 13, and a CX `zp_hi` field means small programs do not pay for that in switch time.
7. **Cheap protection:** a user `BRK` kills the process, not the machine; RESTORE kills the foreground process; syscall buffers are bounds-checked (EFAULT); the saved context carries a canary.
8. **The kernel is already TPA-agnostic at the binary level:** no program or library hardcodes the pool edge (V, grep). What is missing is runtime discovery (`memtop`, largest free run, `brk`).
9. **Order:** fast path, save areas, BRK/RESTORE and bounds checks, syscall page; then CX v2 header, ZP re-split, brk/memtop, exec; then the shared library; then overlays (with M0-6). REU swap is stretch.
10. Every proposal except swap is Classic tier.

## 2. Current-state findings that matter

| # | Finding | Cite | Tag |
|---|---|---|---|
| F1 | The pool is `$0800`-`KSTART-1`. `KSTART=$A100` (uncommitted; it was `$8000`), so 153 pages (39,168 B). `KSTART` is duplicated by hand in `kernel.cfg` (`KRAM`). | `k.inc:4`, `mem.s:4-6`, `kernel.cfg` KRAM | V |
| F2 | First-fit contiguous page allocator. A process is one run: image, BSS, argv, with nothing after it. No growth. | `mem.s:32-73`, `exec.s:159-187,369` | V |
| F3 | CX v1: header `CX`,1,img,bss,nrel; 2-byte reloc offsets, high byte plus the load page. Built by diffing links at `$0000` and `$0100`. | `tools/cx.py`, `Makefile:43-47`, `exec.s:226-282` | V |
| F4 | Relocs over 40 programs: 4,343 (8.7 KB on disk). `as` has 593 (1,186 B, 18% of its file). | measured | V |
| F5 | Library bytes linked per program: `clear` 163 B of image is mostly `lib.o`; typical 967 to 1,061 B (core 158, err 115+494 B of strings, num 200, input 94+259 BSS). Total 27,551 B across `/bin`. | ld65 `-m` maps | V |
| F6 | The per-process save area is 62 B of ZP (`$02-$3F`) plus up to 130 B of stack, 192 B each × 12 = 2,304 B of kernel BSS. `proc` BSS is 3,315. | `k.inc:15-17`, `proc.s:31`, `make size` | V |
| F7 | `sched` always saves and restores, even when it picks the same process (the round robin wraps back to `cur`). | `proc.s:91-175` | V |
| F8 | The kernel runs on the caller's stack and keeps per-process state in `$08-$1F` (`s0..sb7`, `k_entry`). A process blocked in a syscall carries kernel frames in its stack slice. If the stack slice is over 130 B at switch time, the process is killed (exit 139). | `k.inc:62-77`, `proc.s:102-108` | V |
| F9 | Program ZP: `$23-$2F` (13 B). `$30-$3B` is used by lib, `$3C-$3F` is free. Kernel globals sit at `$40-$5A`; `$60-$8F` is unused and not saved. | `breadbin.inc:47-49`, `lib.inc`, `main.s:8-27`, `prog.cfg` ZP | V |
| F10 | `BRK` anywhere panics the whole machine; NMI (RESTORE) is a bare `rti`. | `main.s:208-237` | V |
| F11 | Syscalls write through user pointers with no check (for example `read` into `$E000` would overwrite kernel BSS). | `exec.s` / `file.s` use `(r0),y` and `fb` directly | V (no check found) / U (exploit path not run) |
| F12 | `JUMPTAB` is `$F2` (242 B) for NSYS=32. Each syscall costs 5 B (3 for the table, 2 for lo/hi), so at most 2 more fit. | `jtab.s:11-16,76-`, `kernel.map` | V |
| F13 | Programs size their buffers statically: `edit` TEXTMAX 12288, `as` OBMAX 8192 / NSYM 220, `basic` PROGSZ. Nothing references the pool edge. `prog.cfg` caps a link at `$9000`. | `edit.s:13`, `as.s:22-25`, grep for `$8000/$A000/KSTART` empty | V |
| F14 | Resident chain at the prompt: init (5 pages) spawns and waits for login (7), which spawns and waits for sh (18), so 30 pages before any command. There is no exec-replace. | `init.s:18-21`, `login.s:57-62`, CX sizes | V |
| F15 | Pipes take one pool page each when used; NPIPE=4. | `file.s:19-25` | V |

**Context-switch cost (V from code, cycle counts from the 6502 tables).** ZP save: `lda $0002,y` 4, `sta (p3),y` 6, `iny`/`cpy`/`bne` 7, so 17 × 62 = 1,054. Stack save: 19 per byte. ZP restore: 17 × 62 = 1,054. Stack restore: 19 per byte. `slot_save_ptr` (multiply by 192) is about 95 and runs twice. The pick loop is about 20 per slot.

Take a preempted user process (stack depth about 17: its own 8, the IRQ frame 6, `jsr sched` and `php` 3) switching to one blocked in `read` (depth about 30): 1,054 + 323 + 95 + about 60 + 95 + 1,054 + 570 + about 40, which is **about 3,290 cycles, about 3.3 ms**. With the tick at 60 Hz (U: the kernel never reprograms the CIA1 timer) and SLICE=3, a slice is 50 ms, so a lone CPU-bound process wastes 3.0k/50k, **about 6%**.

For pipes the overhead is about 2 switches per 256-byte page, about 25 cycles per byte. A bus talker delivers a byte every 1.8 ms. **The switch is not a bottleneck anywhere except that null-switch case.**

## 3. Proposals

### LOW (days, clear wins)

**[A1] Fast path when sched picks the current process** | Classic.
- **Benefit:** a lone CPU-bound process gets about 6% of the CPU back (an `as` run, the future compiler).
- **Cost:** about 10 B in `proc.s`. Pick first, and if the pick is `cur`, `plp`/`rts` without touching ZP or stack.
- **Contract break:** none.
- **Depends on:** nothing.
- **Risk:** low. The zombie and free paths already skip the save, and the order must stay "pick, then save the old one" only when they differ.
- **How to test:** a CPU-bound loop timed in jiffies before and after under VICE; `make test-smoke`. It touches the interrupt path, so the full suite runs at the milestone.

**[A2] Save areas live in the process's own pages** | Classic.
- **Benefit:** **−2,304 B of kernel BSS**, so the room below `$FFFA` goes from 183 to about 2,480. `slot_save_ptr` becomes `p3 = ((p_mpage+p_mlen)<<8) - 192` (about 14 B and about 20 cycles, against about 50 B and 95 cycles), saving about 150 cycles per switch. MAXPROC then costs 84 B per slot instead of 276.
- **Cost:** `exec.s` adds 192 to the npages sum (`exec.s:159-180`). Pool cost averages about 0.75 page per process (it often fits in the slack of the last page), so about 1.1 KB with 6 resident processes.
- **Contract break:** none for binaries (meminfo counts shift slightly).
- **Depends on:** none. It makes A7, M2 and S1 trivial: the save area moves with brk, the canary has a home, and a swapped process carries its context with it.
- **Risk:** a program that scribbles past its BSS now corrupts its own saved context. That is self-harm only, and A5 catches it.
- **How to test:** smoke; a pipeline plus Ctrl-C (save areas of blocked processes); `ps` and `free`.

**[A3] Free the syscall page** | Classic.
- **Benefit:** move `sys_lo/sys_hi` (64 B) out of `JUMPTAB` into RODATA, which allows NSYS up to about 58. Without this, A6, M2 and M4 cannot add their syscalls (F12).
- **Cost:** 0 B net (64 B move from the `$CF00` page to CODE/RODATA, which has 267 B of room).
- **Contract break:** none (table addresses unchanged).
- **Depends on:** coordinate with the footprint agent; the `jsr enter` rewrite is uncommitted.
- **Risk:** nil.
- **How to test:** host build, smoke.

**[A4] A user BRK kills the process; RESTORE kills the foreground process** | Classic.
- **Benefit:** a wild jump in a program usually lands on `$00`, which today halts the whole OS (F10).
- **Cost:** about 35 B in `main.s`. In `brk_handler`, if `in_kernel=0`, set the signal and `proc_exit` with 128+5. The NMI handler sets `p_sig=SIGKILL` on the non-BG, non-IGNINT processes (reusing `sigint_fg` with a different signal), which takes effect at the next tick or syscall exit.
- **Contract break:** a new exit status. Kernel BRK still panics.
- **Depends on:** none.
- **Risk:** NMI arriving mid-`sched`. It only sets a flag, and the existing `@die` path runs at the next IRQ.
- **How to test:** a test program that executes `BRK` checks that sh survives and `$?` reports 133; RESTORE via VICE keyboard injection on a spin loop.

**[A5] Cheap integrity checks** | Classic.
- **Benefit:** turns silent cross-process corruption into a clean kill.
- **What it adds:**
  - **(a)** `chk_buf(ptr,len)`: the range must lie inside `[p_mpage, p_mpage+p_mlen)` pages; otherwise return EFAULT (14). It is called from read, write, stat, getcwd, procinfo, meminfo, open and spawn (path and argv).
  - **(b)** A canary byte at save-area offset 191, written on save and checked on restore; if it is wrong, kill the process instead of `rts` into garbage.
- **Cost:** (a) is about 45 B and about 40 cycles per checked call; (b) is about 12 B and about 10 cycles per switch.
- **Contract break:** a new errno, EFAULT.
- **Depends on:** A2 for (b).
- **Risk:** programs that pass ZP or stack buffers would now fail. Allow `$0002-$01FF` explicitly (U: no program found doing it, but not audited).
- **How to test:** host unit-style test programs passing `$E000` or `$CF00` get EFAULT; full `test_system`.

**[A6] `exec` (replace the image in the same slot)** | Classic.
- **Benefit:** login execs sh, which frees 7 pages (1.75 KB) at every prompt. sh can exec the last command of a script.
- **Cost:** about 100 B in `exec.s`. Load into new pages, then free the old ones (keeping pid, fds, cwd and uid), then re-craft the context. One syscall slot (needs A3).
- **Contract break:** a new syscall; `init`/`login` change.
- **Depends on:** A3.
- **Risk:** it needs both images resident briefly (sh 18 + login 7 is fine).
- **How to test:** `ps` after login shows no login process; free pages go up by 7.

**[A7] Delta-encoded relocs (CX v2 header, see M1)** | Classic.
- **Benefit:** one byte per reloc (gap; `$00` escapes a 16-bit gap), so about −4.3 KB of `/bin` on disk; `as` −590 B, about 2.3 blocks, about 1.3 s per `as` exec on the standard bus.
- **Cost:** about 0 B in the kernel (the loop changes shape); `cx.py` about 15 lines.
- **Contract break:** CX version 2.
- **Depends on:** M1 header (do them together).
- **Risk:** low.
- **How to test:** `make test-host` with a cx round-trip test, every program runs.

### MEDIUM

**[M1] CX v2 header** | Classic.
- **Fields:** `CX`, 2, flags, img, bss, nrel, `zp_hi`, `heap_min` (pages), `sstack` (software stack pages), `libabi`, `nsect` (1 for now), plus a section table entry per section (file offset, size, nrel, load offset).
- **Benefit:** one format change that unlocks M2, M3, M4 and A7. The brief's "flag what is cheaper later" item.
- **Cost:** about 40 B in `exec.s`; `cx.py`.
- **Contract break:** all binaries are rebuilt (free per the brief).
- **Depends on:** none.
- **Risk:** low.
- **How to test:** test-host and test-smoke.

**[M2] ZP re-split plus `zp_hi`** | Classic.
- **New map:**
  - `$02-$07` r0-r2
  - `$08-$1F` kernel per-process
  - `$20-$22` argv/argc
  - `$23` memtop (page)
  - `$24-$2F` lib (12 B; lib's `lval`/`lp*`/`lt*` plus num's 7 B BSS moved into ZP, which reentrancy needs for M3)
  - `$30-$6F` program, **64 B** (up from 13)
  - `$70-$8F` kernel globals (32 B; 27 used today)
- `$90-$FF` stay stock. That is within policy (`$02-$8F` is BASIC's old area).
- **Switch cost:** the kernel saves `$02..zp_hi`, from the CX header, which defaults to `$2F` if the program declares no ZP. The `$08-$1F` block is skipped when the outgoing process was preempted in user mode (`in_kernel` was 0 at the IRQ; the kernel is not preemptible, F8). For a typical utility that is 46 B (or 22 B when user-preempted) instead of 62, saving 16 to 40 × 17 cycles each way, **about 540 to 1,360 cycles per switch**. A compiler that uses all 64 B pays 34 cycles per extra byte per switch, about 1,100.
- **Save area:** grows to 110 + 130 = 240 B worst case, still one page with A2.
- **Cost:** about 30 B kernel.
- **Contract break:** `breadbin.inc`, `lib.inc`, `prog.cfg`, `kernel.cfg` ZP, every binary.
- **Depends on:** M1. A2 recommended.
- **Risk:** it moves the kernel ZP, which counts as a memory-map change, so the full suite runs with stock and JiffyDOS ROMs. Any stray hardcoded `$4x` in the kernel would break (U).
- **How to test:** full suite; a test program that fills `$30-$6F` with patterns in two concurrent processes and checks them.

**[M3] brk plus memtop (S12)** | Classic.
- **What it adds:** `SYS_BRK(A = pages to add)` returns A = new end page and grows in place if the following pages are free, otherwise ENOMEM. Spawn reserves `heap_min` and writes `memtop` (`$23`) at entry. `SYS_MEMINFO` gains the pool's first and last page and the largest free run.
- **Policy:** keep first fit. The newest child is usually the highest, so the program that wants to grow (as, the compiler) usually has room. The save area at the top moves for free, since the current process's save area is dead while it runs (A2).
- **Software stack:** the compiler's software stack goes at the top of the allocation, growing down from `memtop` (`sstack` pages), with its pointer in program ZP.
- **Cost:** about 70 B kernel. `edit` and `as` move their static buffers onto the heap (`edit`'s 12 KB BSS becomes "what is free").
- **Contract break:** new syscall and ZP field.
- **Depends on:** A3, M1, M2.
- **Risk:** fragmentation (U; acceptable at 153 pages).
- **How to test:** `edit` opens a file larger than 12 KB when memory allows; `as` with more than 220 symbols.

**[M4] Shared resident library at `$0800`** | Classic.
- **What it holds:** core, err and num (about 970 B code and strings, rounded up to 4 pages; `input` stays static because it has a 256 B buffer of state). It is linked at a fixed address with a jump table at `$0800` (`jsr LIB_print`, 3 B per entry). The kernel loads `/lib/bb` raw in `kmain_run` before spawning init; the pool starts at `$0C00`.
- **Why the bottom:** the bottom never moves while the top edge does, which keeps it TPA-agnostic. The `INIT` and stub load area is dead by then (U on exact layout).
- **Benefit:**
  - **Disk:** about −26 KB on `/bin`.
  - **RAM:** about −1 KB per resident process. Net positive from 2 processes; the prompt already has 3, so about +2 KB.
  - **Exec:** about −4 blocks per exec. Boot saves about 12 blocks against 4 for the lib, about 4.4 s on the standard bus.
  - **Relocs:** lib calls stop being relocated.
- **Cost:** about 40 B kernel loader. The lib must hold no static state (num's 7 B and lib's 1 B move to ZP per M2) and no self-modifying code (U: not audited).
- **Contract break:** linking (an ABI include of absolute symbols), `prog.cfg`, the CX `libabi` check.
- **Depends on:** M1, M2.
- **Risk:** a lib bug hits everything. Boot needs one more file, so panic clearly if it is missing.
- **How to test:** full suite; two concurrent processes printing numbers through the lib (reentrancy under preemption).

**[M5] Overlays in the kernel: `SYS_OVLOAD(A = section)`** | Classic, faster on Expanded.
- **How:** the kernel records each process's executable (dev, ino; 24 B BSS) at spawn and, on request, reads CX section n into its declared load offset inside the process's image, then relocates it with the existing `relocate`. It lives in the kernel because the relocator is already there and a program cannot reliably reopen itself: argv[0] can be relative, and cwd or the file may have changed.
- **The shared loader:** the internal `load_section(ino, off, len, dest, nrel)` that spawn, exec and ovload share **is M0-6**. Build it once, and S11b (UCI DMA or LOAD_REU) speeds all three.
- **Where it helps:** on Expanded the REU block cache already makes reloads cheap. On Classic each overlay load costs about 0.55 s per block, so use overlays for phase-structured programs (compiler passes, `as` pass 2), not hot paths.
- **Cost:** about 120 B kernel.
- **Contract break:** a new syscall and `nsect > 1`.
- **Depends on:** M1, A3, M0-6.
- **Risk:** medium (a stale section after a rebuild; mitigated by the inode generation and size check).
- **How to test:** a two-overlay test program alternating sections and checksumming them.

### STRETCH

**[S1] Swap blocked processes to the REU** | Expanded.
- **What:** when spawn or brk hits ENOMEM, DMA a blocked process (sh in `wait` is the ideal victim) to reserved REU banks, at 1 byte per cycle: sh's 18 pages is 4.6k cycles, about 4.7 ms. It swaps back in at the **same pages**, because runtime pointers are not in the reloc table, so the process sitting there is evicted first.
- **Benefit:** the pool can be oversubscribed (edit plus as plus the compiler).
- **Cost:** about 300 B kernel and REU banks next to the cache (banks 8-10).
- **Contract break:** none.
- **Depends on:** A2 (the context travels with the pages).
- **Risk:** eviction ping-pong; the swapped state must be visible to `ps`.

**[S2] Kernel modules as CX in the pool** | Classic.
- **What:** for example `cbm.s` (1.9 KB) is loaded by mount into pool pages through `load_section` and called through a vector table.
- **Benefit:** frees CODEHI for UCI.
- **Note:** coordinate with the footprint agent, who just moved `cbm` above BSS. The same format and loader cost about 60 B more.

## 4. Things I would not change

| Idea | Why not (numbers) |
|---|---|
| Position-independent code instead of relocation | The 6502 has no PC-relative addressing beyond branches: every `jsr`, table and data access would need trampolines or `(zp),y`, about 1.5-2× code. Relocation costs about 50 cycles per reloc, once, at load. |
| Shared text for `sh × N` | 6502 code is self-modifying and addresses its data absolutely. Sharing would need a per-switch data copy or all data through ZP pointers. Two sh instances cost 18 pages, and that is rare. |
| Fixed per-process ZP banks or ZP relocation | ZP is not relocatable on the 6502. The 110 non-stock bytes divided by 12 processes is 9 B each, which is useless. M2's `zp_hi` gets most of the cycle win. |
| Fixed hardware-stack slices (no copy) | 256 / 12 = 21 B per process, while a blocked syscall already uses about 30 B of stack. The stack copy is about 19 cycles per byte, which is not the bottleneck. |
| Cooperative, one resident foreground process | It kills concurrent pipelines and background jobs. Preemption costs about 6%, and only for a lone CPU-bound process, which A1 removes. |
| A smaller MAXPROC, NFD or NPIPE | After A2 a slot costs 84 B. 12 processes, 8 fds and 4 pipes fit a 3-stage pipeline plus background jobs. Revisit cwd strings (48 B × 12) only if BSS gets tight again. |
| Unrolled ZP copy | It saves about 370 cycles per switch for about 300 B of kernel code. Kernel bytes are the scarcer resource. |

## 5. TPA-agnostic kernel (addendum answer)

**Today (V):** no binary hardcodes the pool edge. Programs are relocated per page, buffers are static, and the only fixed user-visible address is `SYS_BASE=$CF00` (`breadbin.inc:6`). Moving `KSTART` from `$8000` to `$A100` needs no program rebuild.

**What hardcodes it:**
- `k.inc:4` and `kernel.cfg` KRAM: two copies kept in step by hand.
- `prog.cfg` `size=$9000`: a link cap below the new 39 KB pool.
- `edit` and `as`, which size their buffers at assembly time.

**Target:**
1. **One source for the edge.** A Makefile variable passed as `ca65 -D KSTART` and `ld65 -D`, with the `kernel.cfg` and `prog.cfg` sizes taken from it (U: check that ld65 accepts symbols in MEMORY attributes; otherwise generate the cfg).
2. **Runtime discovery.** `memtop` in ZP at entry, and `meminfo` reporting the pool's first and last page and the largest free run.
3. **brk (M3)**, so programs size their buffers to what is free.
4. **Fixed addresses only at the bottom or the top that never moves:** the syscall page and a shared library at `$0800` (M4), never something keyed to `KSTART`.

The result is that `KSTART` becomes a build knob the footprint pass can turn at the last minute, which is what the roadmap already wants ("decided last").

## 6. Order and dependencies

A1 → A2 → A4, A5 → A3 → A6 (all Classic, little contract change), then
M1 + A7 → M2 (milestone: full suite, JiffyDOS run) → M3 (S12, which unblocks S13/S14) → M4 → M5 alongside M0-6 → S1 and S2 when Expanded or UCI work wants them.

## 7. Open questions for the humans

1. Is the pool edge fixed at `$A100` for this cycle? M4 assumes the library goes at the bottom (`$0800`) so it does not care.
2. Should EFAULT reject ZP and stack pointers, or allow `$0002-$01FF`? It depends on whether any program passes stack buffers (not audited).
3. Is a boot-time dependency on `/lib/bb` acceptable, or should the kernel embed the library? Embedding costs about 1 KB of kernel space.
4. Is 64 B of program ZP the right reservation before S14 measures the compiler's real need? M2 makes the cost per byte explicit and per program, so over-reserving is cheap.
5. Who owns the syscall-page change (A3), given the uncommitted `jsr enter` work in the footprint tree?
