# Lens B: syscall ABI and the user library

Source read: the footprint worktree (`.claude/worktrees/reu-cache`), committed tip `6fe063d` plus its **uncommitted** jtab change (`jsr enter` entries, `k_p`, `SYS_CACHE` n=31). That tree is still moving. Built a copy in the scratchpad (`make`, `make size`, `ld65 -m`). Nothing ran under VICE.

## 1 Executive summary

1. **Answer to the peer's question (c):** yes, replace the divide-by-3 loop. The new `enter` costs **108+7n cycles** to get into the handler: 171 for `read` and 178 for `write`, against 73 for the old 8-byte stubs. Every call is 35 to 290 cycles slower than before. A **stride-5 table with the handler vector inline** (`jsr enter` followed by `.word handler-1`) costs a constant **75 cycles** and takes **18 fewer bytes** of the `$CF00` page (224 against 242 B). It also drops the `php`/`k_p` carry dance, the dead `k_n` store and a redundant `cld`.
2. A lean `sys_return` fast path saves another 22 cycles. Round trip for `write`: **250 now, 147 with stride 5, about 121 with both changes.**
3. The real hot spot is the library, not the kernel. Every `putc`/`newline`/`print_dec` padding character is a full `SYS_WRITE` of 1 byte, about **540 cycles of overhead per character** on top of `con_putc`. **Buffered stdout in the library** (flushed on newline to a tty, when full, and before read/spawn/wait/exit) cuts that to about 40 per character and costs the kernel 0 bytes. This is the biggest win.
4. **Library duplication is 47% of all binary bytes.** The error strings (494 B) are linked into 24 programs, and the core, num and err objects are about 25.8 KB of the 54.7 KB in `/bin`. A resident shared library (CX v2 with a second relocation class) is the medium-sized prize.
5. Cheap missing calls that unlock features: a stderr fd in `spawn` (so `sh` can do `2>`), a SIGINT **catch** mode (so BASIC's RUN/STOP stops the program without killing `basic`), non-blocking raw console reads, a version/feature probe, and then exec-in-place, lseek and ioctl.
6. Keep the error model (carry plus errno in A) and the ZP argument registers r0–r2. Moving pointers into A/X would save only about 290 B across all binaries.
7. Migration: one ABI-v2 commit series, with the CX header version bumped from 1 to 2. `exec.s:145-147` already rejects any other version, so stale binaries fail with ENOEXEC instead of crashing.

## 2 Current-state findings (VERIFIED unless marked)

- **Entry (worktree, uncommitted):** the table is 32 × `jsr enter` at `$CF00`. `enter` does `sei; cld`, saves A, X and P to `k_a`/`k_x`/`k_p`, pulls the low byte of the return address and divides by 3 with an `inx; sbc #3; bcs` loop, then pushes `sys_return-1` and `handler-1`, restores P with `plp`, and does `cli; cld; rts` (`src/kernel/jtab.s:20-53`). The page holds 242 of 256 bytes (`kernel.map`: JUMPTAB size `$F2`; labels `enter=$CF60`, `sys_return=$CF93`, `sys_lo=$CFB2`).
- **`k_n` is dead in the syscall path.** No handler reads it. Its only other use is as a loop scratch byte in `proc_exit` (`proc.s:353,364`). The `stx k_n` in `enter` is wasted work.
- **The trailing `cld` in `enter` is redundant:** `k_p` is captured after the first `cld` (`jtab.s:22-27`), so the `plp` restores D=0.
- **Old path (main):** 8-byte stubs `sei; sta k_a; lda #I; jmp dispatch` (main `src/kernel/jtab.s:19-25`), 248 B.
- **`sys_return`** does `php; sei`, pushes A and X, calls `check_signal` (`proc.s:203-209`), tests `need_resched`, then clears `in_kernel` (`jtab.s:55-74`). Signals are always fatal: `check_signal` calls `proc_exit` (`proc.s:206-208`). The IRQ kills or preempts only when `in_kernel==0` (`proc.s:284-307`).
- **Preemption invariant:** `sei` in `enter` exists only because `k_a`/`k_x`/`k_p` are shared before `in_kernel` is set (`jtab.s:18-19`).
- **Argument registers:** r0–r2 are ZP `$02-$07` (`breadbin.inc:42-44`). They are saved per process along with all of `$02-$3F` (`k.inc:15`, `proc.s:114-118`), and the kernel's own scratch `$08-$1F` lives in the same per-process ZP (`k.inc:62-77`). Programs have `$23-$2F` (`prog.cfg`); the library uses `$30-$3F` (`lib/lib.inc`).
- **Call sites in `src/bin` (static grep):** EXIT 49 (46 of them `jmp SYS_EXIT`, bypassing the library's `exit`), CLOSE 19, READ 18, OPEN 16, WRITE 15, WAIT 7, STAT 6, CONMODE 6, SPAWN 5, and every other call 3 or fewer. Through the library: `print` 65, `putc` 37, `eprint` 27, `newline` 26, `print_dec` 18, `getc` 7, `set_input` 9. **At run time `write` dominates**, and most of it is 1-byte writes from `fputc` (`lib/lib.s:68-79`).
- **The library already buffers input:** `getc` reads 256 B at a time (`lib/input.s:21-58`). There is **no output buffering**. `edit` builds its own 64-byte `obuf` (`bin/edit.s:35`) and `sh` its own 256-byte `ibuf` (`bin/sh.s:29`): programs are reimplementing buffering.
- **Library sizes** (from the `ld65` map of `head`): core CODE 158, num CODE 200, input CODE 94 + BSS 259, err CODE 115 + **RODATA 494**. By source grep (UNVERIFIED as a count of what the linker actually pulls): err is used by 24 of the 40 programs, num by 21, input by 7, core by all. That makes about 14.6 + 4.2 + 0.7 + 6.3 = **25.8 KB of 54,683 B** total `/bin`.
- **spawn** passes only stdin and stdout. Stderr is always the parent's fd 2 (`exec.s:54-71`), and there is no dup, so `sh` cannot redirect stderr. `r2` is unused by spawn.
- **Missing calls:** no lseek (the OFT already has a 24-bit position, `f_pos0..2`, `file.s:72-77`), no exec-in-place (`login` spawns `sh`, then waits and stays resident, `login.s:57-62`), no non-blocking read, and no user-visible signal control: `SP_IGNINT` can only be set by the parent (`init.s:17,52`, `login.s:56`). `basic` has no break handling (grep finds nothing), so RUN/STOP kills the interpreter and the program in memory with it.
- **Directory read** is `read()` of raw 16-byte dirents (`bin/sh.s:641-662`), so the on-disk format is part of the ABI.
- **Per-device controls each take a slot:** ISATTY, CONMODE, DISKIO, CACHE, MOUNT, UMOUNT, MNTINFO. There are four separate "info" calls.
- **On-machine assembler:** `as` takes its syscall symbols from `breadbin.inc` (`bin/as.s:1295-1318`), so a rebuild updates it. User sources such as `rootfs/home/hello.s` use symbolic names and survive; only binaries already assembled would break.

## 3 Proposals

### Cycle comparison of entry options (answers peer question c)

Cycles from the caller's `jsr SYS_x` to the first handler instruction, plus from the handler's `rts` back to the caller. No signal or reschedule pending.

| Option | Entry | Exit | Round trip, read (n=9) / write (n=10) | Bytes in the `$CF00` page |
|---|---|---|---|---|
| main: 8-byte stubs | 73 | 72 | 145 / 145 | 93 table + 248 stubs in CODE |
| worktree: `jsr enter` with ÷3 loop | 108+7n | 72 | 243 / 250 (n=31: 397) | 242 |
| B3: stride 3, vectors indexed by the return low byte | 75 | 72 | 147 | 96+33+31+96 = **256, no room** |
| **B5: stride 5, `jsr enter; .word h-1`** | **75** | 72 | **147** | **224** (160 table + 33 + 31) |
| B5 + lean return (L2) | 75 | 50 | 125 | ~236 |
| B5 + lean return + `inc in_kernel` instead of `sei`/`cli` | 71 | 50 | 121 | ~234 |
| F: entry `cld; jsr h; jmp ret`, IRQ decides by PC | 8 | ~45 | ~53–62 | ~240 |

Arithmetic, worktree `enter`, in instruction order: jsr SYS 6, jsr enter 6, sei 2, cld 2, sta 3, stx 3, php 3, pla 4, sta 3, pla 4, ldx# 2, sec 2. The loop runs n+1 times at 7 cycles each, less 1 for the final untaken branch: 7n+6. Then pla 4, stx 3, lda#/sta 5, two push pairs 10, `lda abs,x`/pha ×2 14, lda/pha/plp 10, ldx/lda 6, cli 2, cld 2, rts 6. Total **108+7n**.

B5 `enter`:
```
sei; cld; sta k_a; stx k_x; pla; tax; pla        ; X = 5n+2
lda #1; sta in_kernel; push sys_return-1
lda $CF02,x; pha; lda $CF01,x; pha               ; handler-1 sits inline at 5n+3
ldx k_x; lda k_a; cli; rts
```
6+6+2+2+3+3+4+2+4+5+10+14+6+2+6 = **75** cycles, 33 bytes.

Carry is never disturbed (`pla`/`tax`/`lda`/`pha` leave C alone), so `k_p` and its `php`/`plp` go away. `k_n` is not stored.

Exit, current `sys_return`: handler rts 6, php/sei/pha/txa/pha 13, `jsr check_signal` 22, test `need_resched` 6, clear `in_kernel` 5, pla/tax/pla/plp/rts 20. Total 72.

### LOW (days, clear win)

**[L1] Stride-5 inline-vector entry** | Classic | Removes 96–222 cycles from every call compared with the worktree (n=0..31), is 2 cycles slower than the old stubs, and frees 18 B of the page. That room holds 3 more syscalls, or 6 with nothing else added. | ~2 h; −18 B in the page. | Contract break: `SYS_x = $CF00+5n` in `breadbin.inc`; every binary is rebuilt; the CX version goes to 2 (L8). | Depends on nothing. Do it on top of the peer's worktree change instead of their loop. | Risk: low. The page limit becomes 51 entries minus `enter`/`sys_return`, so about 38 calls; if more are needed, the table grows downward from `$CF00`. | Test: `make test-host`, `test-smoke`, and a microbench program that calls `getpid` 10,000 times and reads `SYS_TIME` (expect about 1 s saved per 10,000 calls against the worktree).

**[L2] Lean `sys_return`** | Classic | −22 cycles per call. Store A and X in `k_a`/`k_x` under `sei` instead of pushing them, and replace `jsr check_signal` with an inline `ldx cur; lda p_sig,x; ora need_resched; bne slow`. The slow path pushes `k_a`/`k_x` before calling `sched`, because another process will overwrite them. | +~12 B in the page. | No contract break. | Depends on L1 for page room. | Risk: losing A/X across `sched` if the slow path is written wrongly. | Test: the smoke test (Ctrl-C on a blocked reader, pipe), plus a test that delivers SIGINT while a reschedule is pending.

**[L3] Buffered stdout/stderr in the library, plus a crt0** | Classic | Per-character output goes from about 540 cycles of overhead to about 40, roughly 2.5–3.5× faster for `putc`-heavy output (`head`, `hexdump`, `print_dec_w` padding, `sh` prompts). Breakdown of the 540 (UNVERIFIED sum): `putc`→`fputc` 44 + round trip 250 + `fd_get` 61 + type dispatch 31 + `con_write` setup and one loop pass 84 + exit work. Buffered: about 25 to store the character, plus 540/len amortized (about 14 for a 40-character line). | Kernel 0 B. Library about 80–100 B code and 128 B BSS per program that writes. | Program-side break: 46 `jmp SYS_EXIT` become `jmp exit`. A `crt0` (entry stub) is linked first so that returning with `rts` also flushes; today an `rts` lands in the kernel's `user_ret` (`proc.s:187-189`), which bypasses any library flush. The library's `read`/`spawn`/`wait` wrappers flush first. | Depends on nothing; it is a prerequisite of M4. | Risk: lost or reordered output. Prompts without a newline (`sh`, the `more` prompt `--more--`) must flush before reading. Ctrl-C loses unflushed output, which matches Unix stdio. | Test: the smoke pipeline, `sh` prompt timing, `more`, `edit` (it already batches its own output), and output interleaving of `2>`.

**[L4] stderr fd for spawn in `r2`** (with `$FF` meaning inherit) | Classic | Makes `2>file` and `2>&1` possible in `sh` without dup2 or fork. | ~10 B kernel (one more `fd_get`, `exec.s:62-66`). | ABI: `spawn` reads `r2`. | Depends on nothing. | Risk: a caller that leaves junk in `r2`; mitigated because every binary is rebuilt. | Test: a new `sh` test, `ls nosuch 2>/tmp/e; cat /tmp/e`.

**[L5] `sysinfo(A=key)`: version and feature probe** | All tiers | Returns the ABI version, the syscall count, and a tier bitmap (REU size, UCI present, turbo). It becomes the one place programs probe, and `uname`/`version` stop hard-coding. Later it can absorb MEMINFO, FSINFO and PROCINFO by key, which frees slots. | ~30 B; one slot. | Additive. | Depends on L1 for the slot. | Risk: low. | Test: host test on `uname` output.

**[L6] SIGINT catch mode: `sigctl(A=0 default / 1 ignore / 2 catch)`** | Classic | In catch mode SIGINT sets a flag byte in the process's ZP (for example `$2F`, written live if the process is current, or into its `p_save` area otherwise) instead of killing it. Programs poll the flag. **BASIC gets a working RUN/STOP**; `edit` can refuse to quit with unsaved changes. Blocked syscalls continue; there is no EINTR yet (that is M5). | ~35 B (`sigint_fg`, `check_signal`, IRQ `@die`). | Additive; `SP_IGNINT` stays. | Depends on nothing. | Risk: the flag write into the save area must use the slot's ZP offset. | Test: VICE test, a BASIC `10 GOTO 10`, Ctrl-C, expect READY.

**[L7] Non-blocking raw console read** (CONMODE bit 1, or later through ioctl) | Classic | `raw_read` returns `r1=0` (or EAGAIN) when no key is waiting, which enables games, an editor with a clock, and `top`-style tools. | ~12 B (`con.s:679-687`). | Additive. | Depends on nothing. | Risk: busy loops; document `SYS_YIELD`. | Test: keyboard test.

**[L8] CX version 2 marks ABI v2** | All tiers | Free safety: `exec.s:145-147` already rejects other versions. | 1 byte in `tools/cx.py:33` and `exec.s:146`. | Every binary is rebuilt; stale ones fail with ENOEXEC. | Ship with L1. | Risk: none. | Test: run a version-1 CX, expect ENOEXEC.

### MEDIUM

**[M1] `exec(r0=path, r1=argv)`: replace the current image** | Classic | `login` execs `sh`, which frees about 1.5 KB of pool and one of the 12 process slots for the whole session. Also enables a `sh` `exec` builtin and program chaining (BASIC `RUN "x"`, `as` then run). | ~150 B kernel (UNVERIFIED estimate): reuse `spawn_common` with the current slot. Check the header and namei first, then free the old pages, then load. An I/O error after that point kills the process with exit code 128+EIO. | Additive. | Benefits from the M0-6 stream primitive. | Risk: the point of no return; a failure late in loading. | Test: `exec ls` from `sh` returns to `login`; `ps` shows one process fewer.

**[M2] `lseek(A=fd, r0/r1 = 24-bit offset, X=whence)` → ESPIPE on pipes and the console** | Classic (c64fs); Recommended (UCI has 32-bit seek) | Prerequisite for overlays (S2), random-access tools (`tail`, a database, BASIC random files) and the S11 UCI backend. | ~60 B. CBM DOS files return ESPIPE. | Additive. | Depends on nothing. | Risk: positions past EOF interacting with `fs_write` sparse handling (check `bmap`). | Test: write, seek, overwrite, read back.

**[M3] `ioctl(A=fd, X=req, r0=arg)` dispatched by open-file type or major** | All tiers | One extensibility point for driver-specific controls. Absorbs ISATTY, CONMODE and L7 now, and CACHE and DISKIO later through a `/dev` block node. Frees about 3 slots; new drivers (UCI, REU) add requests instead of slots. | About byte-neutral (a dispatcher replaces the entry glue). | Break: `edit`, `login`, `passwd` and `basic` (CONMODE/ISATTY callers) change. | Depends on L1. | Risk: low. | Test: the existing console tests.

**[M4] Resident shared library `libbb`** | Classic (it lives in the pool) | Disk: about −25 KB across `/bin` (47%), which shortens every command load on a 1541. Memory: −0.4 to −1.1 KB per running process, against a fixed cost of about 1.2 KB loaded once at boot. Break-even at about 2–3 processes; `init`, `login` and `sh` are always resident, so it pays immediately. Design:
  - The kernel loads `/lib/bb` at boot as a CX image (no process), with `lib_page` recorded.
  - **CX v2 adds a second relocation list "+ lib_page"**. `tools/cx.py` already finds relocations by linking twice (`-S 0` and `-S 256`, Makefile:45-46); a third link with the library shifted gives the library relocations.
  - Library state moves out of the library's BSS: small state in ZP `$30-$3F` (already per process), and the input and output buffers in the program's BSS through a ZP pointer that crt0 sets.
  - The library is called with plain `jsr`, with no extra trampoline.

  | Cost: ~40 B kernel (second relocation loop and boot load), the `cx.py` and Makefile change, crt0. | Break: the CX format and every binary. | Depends on L3 and L8. | Risk: library and program version skew (put the library version in the CX v2 header and have exec check it). | Test: the full suite; `free` before and after.

**[M5] EINTR: unwind a blocked syscall on a caught signal** | Classic | Ctrl-C interrupts a blocked `read` for catch-mode programs, such as BASIC's INPUT. | ~30 B: save SP at `enter` in a per-process kernel ZP byte (`$08-$1F`). In catch mode `check_signal` does `ldx saved; txs`, returns A=EINTR with carry set, and jumps to `sys_return`. | Additive errno (`EINTR=4`). | Depends on L6. | Risk: handlers that block mid-update (`pipe_write` partially done, so the count is lost); audit every `block_on` caller (`file.s`, `con.s`). | Test: Ctrl-C during `read` in catch mode.

**[M6] User REU access: `reu(A=op, r0=c64 addr, r1=len, r2=handle/offset)`** with per-process REU allocation | Expanded; ENODEV on Classic | Large data for `as` and the compiler symbol tables, and edit text paging, without growing the pool. Complements S12 `brk`. | ~80 B (the DMA code exists in `blk.s`; this adds an allocation table and a free on exit). | Additive. | Depends on L5 for the probe. | Risk: clashes with the REU ramdisk and cache layout. | Test: a VICE test with REU on and off.

### STRETCH

**[S1] Entries with no `enter` at all (option F).** Each entry is `cld; jsr handler; jmp sys_ret` (7 B × 32 = 224 B). The IRQ treats an interrupted PC ≥ `>KSTART` as "in kernel", which retires the `in_kernel` flag. That gives a ~55–62 cycle round trip. Cost: ~10 cycles per IRQ; risk: every kernel entry and exit path (`proc_entry`, the idle loop, INIT) must hold the "PC tells kernel or user" invariant. Do it only if measurements after L3 still show the syscall path dominating.

**[S2] Overlays:** `ovload(A=fd, X=overlay#, r0=dest)` reuses `exec.s` `relocate` (program and library relocation classes), with REU-cached overlays on Expanded. Depends on M2 and M4.

**[S3] Environment block at spawn** (copied like argv, `exec.s:311-450`), plus `getenv` in the library. Low value until `sh` has variables.

**[S4] Driver-registered calls:** loadable modules add `ioctl` requests or `sysinfo` keys rather than table slots. The table itself stays fixed and small.

### Migration (we rebuild every binary)

1. L1 + L8 + L2 in one commit: `jtab.s`, `breadbin.inc` and `exec.s` version byte, then `make`, `test-host`, smoke.
2. L3 with crt0, and the 46 `jmp SYS_EXIT` sites changed to `jmp exit`.
3. L4, L5, L6, L7 as additive slots.
4. M3 (ioctl consolidation, a coordinated break of 4 programs).
5. M4 (CX v2 library relocations), M1, M2.

Run the full suite at step 1 (it is an interrupt-path change), and again at M4.

### Kernel and program bytes (question 6)

- The 248 B of stubs are already gone in the worktree.
- L1 frees a further 18 B of the page; L2 spends 12 B of it.
- Proposals that cost kernel CODE: L4 +10, L5 +30, L6 +35, L7 +12, M1 +150, M2 +60, M4 +40. That is about 340 B against the 267 B free below `$CF00`, so it needs the footprint work or a `KSTART` decision.
- Program bytes: L3 +~100 B per writer until M4; M4 about −25 KB on disk.

## 4 Things I would not change

- **Carry for error, errno in A, count in r1, EOF = count 0.** `bcs` is the cheapest test there is, and the errno numbers are Unix numbers. Document that only C, A and the stated outputs are defined, and that Y and N/Z/V are clobbered.
- **ZP r0–r2 argument registers.** Passing the pointer in A/X would save about 4 B × 73 call sites, roughly 290 B across 54.7 KB of binaries. It would cost about 4 B and 6 cycles in each of about 15 handlers, and churn the whole tree.
- **No fork, no select/poll, no readv/writev, no "write string" call, no file locking, no mmap.** With buffered output (L3) a string call gains nothing. Nothing in the tree needs to wait on several fds; `more` reads its input and the console one after the other. There are no concurrent writers that need locks, and no MMU for mmap.
- **The `$CF00` fixed page as the only fixed kernel ABI point.** Keep it fixed and small; extend through ioctl and sysinfo keys instead.

## 5 Open questions for the humans

1. Should the peer land L1 instead of the ÷3 loop now? The loop is uncommitted, so changing course costs nothing today.
2. Should the shared library live at a fixed address (simpler, but pins memory) or be relocated through CX v2 (recommended)?
3. Signal semantics: polled flag only (L6), or EINTR unwinding too (M5)? Which programs besides `basic` and `edit` matter?
4. Should `login` exec `sh` (M1)? That changes what `ps` shows and what a shell `exit` does (back to `init`, which respawns `login`).
5. Is about 1.2 KB of resident library acceptable on Classic, given the pool edge (`KSTART=$A100`) is still being decided?
