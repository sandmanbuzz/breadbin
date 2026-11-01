# exec: replace the caller's image in its own slot (design note)

Status: paper only, nothing built or run. Base: main at 315cafd (`cx_load` split, modules v1). Goal: `login` execs `sh`, which frees login's 7 pages (1,198 B image + 498 B BSS + argv; `tpa-recovery.md` move 1) at every idle prompt. **V** = VERIFIED (I read the cited line). **U** = UNVERIFIED (inferred or arithmetic).

## 0. Decisions

- **Entry: a flag on SPAWN** (`SP_EXEC = $80` in Y), not a new syscall. All 32 slots are taken (jtab.s:13, 46-110 V). `SYS_CACHE` op 7 would also work (blk.s:989-999 V), but it would have to duplicate spawn's NULL-argv default (exec.s:79-94 V). The flag reuses `sys_spawn` and `spawn_common` as they are. If cx2-abi2 later frees slot 24 for EXEC, that slot's record becomes `ldy #SP_EXEC` followed by `sys_spawn`.
- **Atomic.** The old and new images are resident together. Every step that can fail runs before anything of the caller's is written. Peak memory is the same as `spawn` today.
- **Restart**: write the live zero page, then `sei`/`ldx #$ff`/`txs`/`jmp proc_entry`. No `p_save` surgery.
- **Cost**: about 80 resident bytes (U).

## 1. Contract

`spawn(r0 = path, r1 = argv or NULL, Y = SP_EXEC)`.

- A and X (the fds) and the other Y bits are ignored.
- On success the call does not return. The new image starts at its entry with `argv` ($20) and `argc` ($22) set exactly as spawn sets them (breadbin.inc:47-48 V, exec.s:549-562 V).
- On failure: carry set, A = errno, the caller unchanged. The return goes through `sys_return` as usual (jtab.s:113-132 V).
- The errors are the ones `cx_load` and `measure_args` already give:
  - ENOENT or ENOTDIR from namei (exec.s:128 V).
  - ENOEXEC for a CBM device, a non-file, a bad magic, a short image or a short reloc table (exec.s:131-136, 141-145, 161-176, 230-235, 274-277 V).
  - ENOMEM (exec.s:183-213 V).
  - E2BIG (exec.s:358, 372 V).
  - Whatever `fs_read` returns.
- There is no EAGAIN, because exec needs no free slot.

| State | After exec |
|---|---|
| pid, ppid, `p_pslot`, `p_uid`, `p_flags` | kept (never written) |
| fds (`p_fd`, `f_ref`) | all kept; no close-on-exec, since there is no fcntl (open question 1) |
| cwd (`p_cwd`, `p_cwddev/ino`) | kept (`copy_cwd` is not called) |
| `p_name` | basename of the path (`set_name`, exec.s:598-625 V) |
| `p_mpage/p_mlen` | the new run; the old run is freed |
| ZP $02-$3F | zeroed, then argv, argc and `k_entry` set as spawn does (exec.s:543-568 V) |
| stack | empty, with the same frame state spawn produces (§3) |
| pending `p_sig` | kept and acted on at commit: the new image dies before its first instruction |
| raw console mode | dropped (`con_release`, con.s:408-415 V) |
| children and zombies | kept as children (same slot); `wait` still reaps them (proc.s:448-490 V) |
| ZP outside $02-$3F, `$01` | untouched, as with spawn (proc.s:113-118 V) |

## 2. Algorithm

### 2.1 Dispatch (exec.s changes)

```
sys_spawn:                       ; exec.s:64
        sty sp_flags
        stx sp_out
        cpy #SP_EXEC             ; NEW 4 B: exec skips the fd lookups
        bcs @argv
        ...                      ; fd_get x3, unchanged (67-78)
@argv:  lda r1 ...               ; label on line 79: NULL -> {path}, then spawn_common

spawn_common:                    ; exec.s:97
        ldx cur                  ; NEW 7 B
        bit sp_flags
        bmi @slot                ; exec: the caller's own slot
        ldx #MAXPROC-1           ; slot search, unchanged (99-106)
        ...
@slot:  stx sp_slot
        jsr measure_args         ; FAILS: E2BIG
        bcs @sr
        lda #0
        sta ld_hi
        jsr cx_load              ; FAILS; frees its own run on failure (exec.s:240-247 V)
        bcs @sr
        jsr zero_bss             ; cannot fail
        jsr copy_args            ; cannot fail; reads argv in the OLD image, still mapped
        bit sp_flags             ; NEW 5 B
        bmi exec_commit
        jsr setup_proc
        clc
@sr:    rts
```

The boot path is unaffected: `spawn_kernel` sets `sp_flags = SP_IGNINT` (exec.s:59-60 V), so bit 7 is clear.

### 2.2 Commit

```
exec_commit:                     ; ---- point of no return: nothing below can fail ----
        jsr set_name             ; pp -> path, still in the old image (cx_load 124-127)
        ldx cur
        lda p_mpage,x
        ldy p_mlen,x
        jsr page_free            ; old image back (mem.s:119-134 V)
        ldx cur
        lda base
        sta p_mpage,x
        lda npages
        sta p_mlen,x
        lda p_pid,x
        jsr con_release          ; raw mode is keyed by pid (con.s:394-399 V)
        lda #$02                 ; p3 -> the LIVE zero page, not the save area
        sta p3
        lda #0
        sta p3+1
        jsr init_ctx             ; setup_proc's zero + argv/argc/k_entry block
        jsr check_signal         ; a pending signal kills the NEW image, interrupts on
        sei
        ldx #$ff
        txs                      ; drop the user stack and the sys_return frame
        jmp proc_entry           ; in_kernel=0, push user_ret, cli, jmp (k_entry)
```

`init_ctx` is exec.s:543-568 plus an `rts`. `setup_proc` becomes `jsr slot_save_ptr`, `jsr init_ctx`, then the stack frame (569-581).

The share is safe because the block only writes offsets below `ZPSAVE` through `(p3),y`. `p3` itself lives in kernel ZP at $40 and up (main.s:9-18 V, kernel.cfg:7 V), so it is not overwritten. The stack-frame writes at offset `ZPSAVE` must stay out of `init_ctx`: with p3 = $0002 they would land on `cur` and `in_kernel`.

### 2.3 Atomicity and memory

**Nothing of the caller changes before `exec_commit`**: earlier writes go only to kernel scratch (`sp_*`, `hdr`, `base`, `rbuf`, block cache) and the new pages. The kernel is not preemptible (in kernel mode the IRQ only sets `need_resched`, proc.s:302-306 V) and nothing on the load path blocks (`block_on` callers are pipes and console only: file.s:548, 680; con.s:604, 686 V by grep).

**Memory**: a contiguous free run of the new `npages` while the old run is held. That is exactly spawn's requirement, and today's login path already holds both images (login waits on sh, login.s:54-62 V), so exec never fails where today works. Login's freed run becomes a low hole that first fit (mem.s:33-74 V) gives to the next small command.

**Free-first: rejected.** It would load images larger than free + old, but needs path and argv bounced into kernel BSS, and every later failure (read error, bad relocs, fragmentation) becomes "exit 128+errno" instead of an error return. Opt-in bit later, if ever needed.

## 3. The hard part: restarting from inside a syscall

`enter` pops the user's return address, sets `in_kernel`, pushes `sys_return-1` then the handler (jtab.s:22-43 V). The caller is `cur`: its ZP $02-$3F and stack page are **live**; its `p_save` slice is stale, written only when `sched` switches it out (proc.s:101-125 V). So `p_save` and `p_sp` are not touched; the next `sched` refreshes both. Exec rewrites:

1. **Live ZP**: zero $02-$3F; `argv` ($20/21) = base+img+bss, `argc` ($22) = nargs, `k_entry` ($1E/1F) = base:00 (k.inc:77, exec.s:549-568 V): the bytes `sched` would copy from the save area (proc.s:159-164 V).
2. **Stack**: spawn crafts P=$04 + `proc_entry-1` at $FD-$FF, `p_sp=$FC` (exec.s:569-581 V); `sched`'s `plp`/`rts` (proc.s:165-175 V) reaches `proc_entry` with SP=$FF, I=1, D=0. Exec gets there directly: D is clear (`enter`'s `cld`, jtab.s:24 V), then `sei`/`ldx #$ff`/`txs`/`jmp proc_entry`, which clears `in_kernel`, pushes `user_ret-1` (SP=$FD, as spawn), `cli`, `jmp (k_entry)` (proc.s:178-186 V).
3. **`sys_return` is skipped**: its signal check is the explicit `check_signal`; a leftover `need_resched` costs one spare `sched` at the next syscall (jtab.s:120-124 V). `in_kernel` is cleared with I=1, so no IRQ sees user mode on a kernel stack.
4. **Interrupts**: on during the load (`enter`'s `cli`, jtab.s:42 V; harmless per 2.3), off from `sei` to `proc_entry`'s `cli`, so no IRQ pushes onto a half-reset stack.

## 4. Interactions

- **Signals.** `sigint_fg`/`kill` can set `p_sig` during the load (proc.s:330-346, 493-511 V). On failure, `sys_return` kills the old image (jtab.s:119 V). On success, the commit's `check_signal` runs `proc_exit` (proc.s:203-208 V) with `p_mpage` already the new run and interrupts on, as `die_stub`'s rule requires (proc.s:307-310 V). After the commit, `@die` takes it at the first user tick (proc.s:289-290 V). SP_IGNINT is kept (login.s:56 V).
- **As a parent.** Children keep `p_pslot = cur` and keep running; the new image can `wait($FF)` for them; zombies stay until reaped or reparented to init at exit (proc.s:391-407 V).
- **Pipes and fds.** Untouched, so pipe reader/writer counts stay exact (no false EOF or EPIPE). The lib does not buffer (`print` -> `SYS_WRITE`, lib.s:58-65 V); cx2's stdout buffer, when it lands, must be flushed by the lib's exec wrapper (cx2-abi2.md §5).
- **Its parent.** The pid is stable, so init's wait on `shpid` (init.s:62-69 V) sees the shell's exit and respawns login, as today.
- **Modules.** They share `cx_load`, `base`, `npages`, `ld_hi` (exec.s:23-35, 688-690 V); no interleaving (not preemptible, no blocking). `exec /lib/km/hello` would run `jmp init` in user mode: no worse than any program without an MMU, but surprising (question 3).

## 5. Bytes and cycles (U, hand counts)

| Piece | Bytes |
|---|---|
| `sys_spawn` `cpy`/`bcs` | 4 |
| `spawn_common` `ldx`/`bit`/`bmi` | 7 |
| `bit`/`bmi` after `copy_args` (+3 if a `jmp` is needed) | 5-8 |
| `exec_commit`: set_name 3, page_free 14, stores 14, con_release 6, p3 8, init_ctx 3, check_signal 3, sei/ldx/txs 4, jmp 3 | 58 |
| `init_ctx` `rts` + the `jsr` from `setup_proc` | 4 |
| **Total** | **78-81** |

This is inside the 100-150 B target. It costs no TPA page if it fits in today's slack below $CF00; otherwise one page, and the net gain is 6 pages instead of 7. Measure with `make size`.

Cycles:

- **Spawn path overhead**: 5 + 9 + 6 ≈ **20 cycles per spawn**.
- **Commit**: the `init_ctx` zero loop costs 62 × (6+2+2+3) ≈ 810 cycles, plus ~60 for the rest of `init_ctx`. `set_name` for "/bin/sh" is ~250. `page_free` of 7 pages is ~25 + 7×11 ≈ 100, and the rest is ~80. Total **≈1.3k cycles (≈1.3 ms)**.
- **What exec skips**: the slot search, `copy_cwd` (48 × ~13 ≈ 620) and the fd setup, so the kernel side of exec is cheaper than spawn's.
- **The load** is the same `cx_load`: bus reads plus ~47.5k cycles of relocation for sh (cx2-abi2.md §1.6).

## 6. Test plan

**Simulator** (py65, `tools/uci_sim.py` style, host). The harness must fake a current process (slot 0: `p_state`, `p_mpage/p_mlen`, `pg_used`, `cur=0`); U: none does today (uci_sim.py:5-10 V: no scheduler).
- (a) missing path -> ENOENT; (b) `/etc/passwd` -> ENOEXEC; (c) full `pg_used` -> ENOMEM. Each: `pg_used`, `free_pages`, `p_mpage/p_mlen`, `p_name`, `p_fd`, ZP $02-$3F byte-identical.
- (d) success, stopped at `jmp (k_entry)`: next PC base:00, SP=$FD, $20/21 into the new run with the right strings, $22 = argc, $02-$1D zero, old run free, `p_name`="echo", pid unchanged.
- (e) `p_sig` preset: zombie, `free_pages` = before + old run (nothing leaked).

**VICE: new `tests.test_system.Exec`**, through an `exec` builtin in `sh` (~30 B; check sh's page count).
1. Nested `sh`, `ps` (pid N), `exec ps`: pid N named `ps`, no second sh, outer prompt back.
2. `exec /etc/passwd` -> "exec format", `exec /bin/nothing` -> "no such file", then `echo alive` in the same shell.
3. ENOMEM: fill `pg_used` as Pool does (test_system.py:440-442 V); `exec sh` errors, shell continues.
4. `sh /home/x.sh | wc` with `exec echo via script`: one line, EOF arrives.
5. login->sh: no `login` in `ps`; idle `free` up by login's pages against a baseline from main.

**Boot.test_15** assumes init+login+sh+9 jobs fill 12 slots (test_system.py:149-159 V): now 10.

**Regression**: test-host, smoke, Boot 05/08/11/12/15/25, Modules, Pool, Cache; since the process entry path changes, the full suite, JiffyDOS disk tests and one hardware login before merge.

## 7. Adversarial review

1. **Half-written pipe**: a write is a syscall; a blocked writer is in `block_on` (file.s:680 V), never in exec. Data and refcounts survive.
2. **Signal pending or arriving mid-load**: checked after `p_mpage` switches; never lost, never hits a half-built process (sim e).
3. **ENOMEM half-replacing**: impossible by construction (no table writes before commit; `cx_load` cleans up). Risk = a future fallible step after the commit: a rule comment at `exec_commit` plus sim (a)-(c).
4. **New frame overflow**: fresh SP=$FF, same depth as spawn; overflow by the program is caught by `sched` (proc.s:104-108 V).
5. **argv in freed pages**: old run freed only after `copy_args`/`set_name`: safe. **Real hole, inherited from spawn**: `measure_args` runs before `cx_load` (exec.s:108-112 V) and `copy_args` copies to NUL unbounded (exec.s:442-446 V). An argv pointer into free memory that `cx_load` then fills makes the copy longer than measured and overruns into a neighbour. Fix in the same change: bound by `argsz`, or EFAULT outside the caller's run (~10 B, U).
6. **IRQ during reset**: none between `sei` and `cli`; after it, `@die` edits a valid user frame (proc.s:311-319 V).
7. **Raw mode by pid**: `con_release`.
8. **Stale `p_save`**: never read for `cur`; next `sched` overwrites (proc.s:109-125 V).

## 8. Open questions

1. Close-on-exec: none, I propose (NFD = 8, no fcntl).
2. Should `SP_EXEC` honour the other Y bits (for example clearing SP_IGNINT)?
3. Should exec refuse modules? Only cx2's `F_LIBRARY` flag, or a class flag, could tell them apart.
4. The vehicle: the `sh` builtin (costs sh bytes) or a test-only program?
5. Login on exec failure: print the error and exit, so that init respawns it? (I propose yes; falling back to spawn+wait needs the same memory.)
6. Free-first as an opt-in bit, only if a program ever needs an image larger than free + old.
