# CP3 spec: contract tidy (ABI v2 foundation)

Status: DRAFT for the owner, 2026-11-04. Written by a Sonnet drafter from a read-only pass over `main`, reviewed by a hostile Sonnet reviewer (20 cited lines spot-checked, 19 held; findings triaged at the end), then edited by the hygiene/broad-view agent. No code. Every byte count is a hand estimate. The CP3 row of `docs/design/next/checkpoints.md` is the source of scope; `cx2-abi2.md` is the source of the contract.

Base: `main` (45eacff size ledger). V = read at the cited line on main; U = unverified or inferred. Byte counts are hand counts, not built. Paths are `src/kernel/` unless noted.

## 1. Scope and non-goals

In: SYS_CTL (slot 23) absorbing ISATTY, CONMODE, CACHE, DISKIO; SYS_SYSINFO (slot 20) absorbing MEMINFO; user BRK-opcode and RESTORE kill. The CX version byte is NOT bumped in CP3 (see below).
Not in: CX v2 trailer/delta relocs (CP4), tagged allocator / `brk` / `memtop` (CP5), the descriptor byte and EFAULT (cx2 commit 3), `LSEEK`, `O_NONBLOCK/NREAD`, SIGINT catch, buffered stdout, spawn r2 stderr, shared library.
Couplings in cx2-abi2.md:
- It ties `KABI` to the CX v2 trailer (`abi` byte, §1.2). CP3 does not need that. A stale v1 binary does not need a version bump to be refused: the syscalls it uses are removed from `breadbin.inc` and the table (a program calling slot 24 gets ENOSYS). The version bump is left to CP4 with the CX v2 trailer (the hater found that bumping the header byte to 2 now would collide with cx2's trailer ending `"CX",2`, and would turn five host tests red: `asim.py:45`, `uci_sim.py:569`, `test_as.py:32`, `test_mkimage.py:123`, `test_modules.py:35`). The version check is at `exec.s:183-185` (`cmp #1`); `exec.s:139-147` is the `dev_type` test.
- It says "EXEC" takes a freed slot (§0.4, §2.3). Already done: exec is `SP_EXEC` in SPAWN (`include/breadbin.inc:62`, V). No EXEC slot needed.
- Its `BRK` slot 30 is the memory `brk` syscall; the checkpoint row's "user BRK" is the 6502 BRK opcode. Different things, same word. Spec uses "BRK opcode" and "sys brk".
- CTL op 3 NREAD, 5 SIGINT, and EFAULT checks depend on later commits: CP3 reserves the op numbers, returns ENOSYS.
Also in the CP3 row but not specified here: "sched skips save/restore when it picks the same process" (independent, split off).

## 2. Current state (VERIFIED)

| Call | Slot | Conv | Handler | Callers | Bytes (U) |
|---|---|---|---|---|---|
| ISATTY | 23 | A=fd. C clear = console; else C set A=EINVAL (EBADF from `fd_get`) | `file.s:335-347` | `basic.s:59`(A=0), `ls.s:20`(A=1); both read only carry (`rol a`) | ~18 |
| CONMODE | 24 | A bit0 = raw (`and #1`), fd ignored; resets line buffer; owner = `raw_pid` | `con.s:392-405` | `edit.s:59,110`, `login.s:87,124`, `passwd.s:216,243` | ~26 |
| DISKIO | 30 | A=drive 9-11, X=op 0 cmd(r0 string)/1 write(r0, blk r1)/2 read; EBUSY on boot drive/mounted | `cbm.s:268-337` (resident part of the CBM fs) | `format.s:147,290,301` | ~100 |
| CACHE | 31 | A=op: 0 stat 7 B at r0, 1 off, 2 on, 3 flush; **4 load module r0->A slot, 5 unload slot X, 6 list 12 B at r0** (4,5 root-only via `su_check`); ENODEV no REU | `blk.s:1006-1066` | `cache.s:48` (A=op var), `mod.s:40,56,69` | ~105 |
| MEMINFO | 20 | r0=buf: free, total, reu_banks, procs, maxprocs (5 B) | `mem.s:136-162` | `free.s:9`, `uptime.s:42` (reads `mi+3`) | ~50 (allocator.md says ~65) |

- No kernel code calls these handlers: grep of `jsr sys_`/`jmp sys_` finds only `file.s:787 sys_close` (V). Handlers can be re-fronted freely. `con_release` is called at `proc.s:350` and `exec.s:699` (V).
- Slot table `jtab.s:46-110`, `NSYS=32` (`jtab.s:13`), imports at `jtab.s:11`. Records are 3 bytes, third byte `.byte 0` (spare). Page `$CF00-$CFF1`, 14 B free (D-console-cooler.md, V).
- `breadbin.inc` has no ENOTTY, EFAULT or ENOSYS (lines 72-95, V). New errnos: ENOTTY=25, ENOSYS=38 (EFAULT=14 reserved, unused in CP3). They also need lines in `rootfs/etc/errors` and an entry in `tools/uci_sim.py` `ERRNO` (`tools/test_errors.py` ties `breadbin.inc` to `etc/errors`), or `perr` prints no message for them.
- `as.s:1355-1369` exposes only `sys_*` up to `sys_isatty` (V): `sys_meminfo`, `sys_isatty` must be renamed. No test or rootfs source uses either name (grep, V).
- Hosts parse `include/breadbin.inc` with `SYS_(\w+) = SYS_BASE + 3*(\d+)` (`tools/uci_sim.py:362`, `tools/asim.py:26`, V): keep that line format. Nothing hard-codes `$CF00+n`; `tests/test_system.py:42` only checks vectors.
- `src/mod/*.s` and `src/mod/kapi.txt` call/export no syscall (grep, V). The KAPI hash covers `NAME=ADDR`, so kernel growth shifts it; a normal `make` rebuilds the modules.
- BRK today: `irq_entry` tests the B flag on the stacked P (`main.s:223-233`), `brk_handler` falls into `panic`: "kernel panic: brk", border flashing forever (`main.s:244-262`, V). NMI: `nmi_handler: rti` (`main.s:218-219`), vector set at `main.s:84-86`. RUN/STOP sets `p_sig=SIGINT` on every ready/blocked process without BG|IGNINT (`proc.s:319-335`); the IRQ's `@die` redirects the RTI to `die_stub` (`proc.s:296-317`). init spawns sh/login with `SP_IGNINT` (`init.s:17,52`, V). pid 1 exit panics (`proc.s:343-347`).

## 3. New contract

**SYS_CTL** (slot 23): A = fd or target, X = op, Y = small arg, r0/r1 buffers. C clear ok; C set A=errno. Dispatcher `cpx #NOPS; bcs @enosys; lda hi,x; pha; lda lo,x; pha; rts` clobbers A, and A carries the fd or drive: the dispatcher must save A first and restore it before the `rts` into the handler (a ZP temp, or reload from `k_a`, which `enter` already keeps: `jtab.s` ~35), about +4 to +6 bytes. Built without that, ISATTY would test the table's high byte as the fd and DISKIO would see a wrong drive.

| Op | Name | In | Out / errors |
|---|---|---|---|
| 0 | ISATTY | A=fd | C clear = console; ENOTTY (was EINVAL), EBADF |
| 1,2,3 | GETFL, SETFL, NREAD | reserved | ENOSYS |
| 4 | CONMODE | A=fd (ignored, as today), Y=0 cooked / 1 raw | none (the console owner rules, `raw_pid`) |
| 5 | SIGINT | reserved | ENOSYS |
| 6 | CACHE | Y=0 stat (7 B at r0), 1 off, 2 on, 3 flush | as `blk.s:1026-1066`; ENODEV |
| 7 | DISKIO | A=drive, Y=0 cmd / 1 write / 2 read, r0, r1 | as `cbm.s:268-337` (op moves X to Y) |
| 8 | MODULE | Y=0 load (r0 path -> A slot), 1 unload (A=slot), 2 list (r0, 12 B) | root-only for 0,1 (EPERM) |
| 9-$3F | | | ENOSYS |
| >= $40 | module range | | ENOSYS until a module registers (cx2 §2.4) |

Gaps and inconsistencies in cx2-abi2.md:
1. CACHE op 6 in §2.4 is stat/off/on/flush only. It omits the existing module ops 4,5,6 (`blk.s:1006-1008`), which `mod` uses. Hence op 8 above; unload moves the slot to A because X is the op.
2. Its line refs `cbm.s:814-830`, `blk.s:965-1000` are stale (now 268-337, 1006-1066).
3. CONMODE "A=fd must be the console" is a behavior change: today the fd is ignored (`con.s:395`) and raw mode is console state, not fd state. With the check, `echo x | edit` (stdin a pipe, stdout the console) would stay cooked. Decision: keep ignoring the fd (also saves about 10 bytes). Only ISATTY changes its error (ENOTTY for EINVAL; callers read the carry).
4. SYSINFO key 0 lists `lib_loaded, libid(2)` which do not exist until the shared library (CP6), and `buf[16]` is written unchecked (no EFAULT in CP3). Spec: key 0 returns 8 bytes now.
5. `r1 = length` return: optional, costs ~8 B; not needed, callers know sizes.
6. §0.4 and §2.3 reserve EXEC slot 24; that slot is free for another use (see 4).

**SYS_SYSINFO** (slot 20): A=key, r0=buf. Unknown key: ENOSYS.
- Key 0 (8 B): `abi` (=2), `kver_hi`, `kver_lo`, `nsys` (32), `nctl` (9), `tier` (bit0 REU, bit1 UCI present, bit2 turbo), `reu_banks`, reserved 0. Needs a `KVER` constant and a UCI-present label (U: none known).
- Key 1 (5 B): exactly old MEMINFO bytes (`mem.s:136-162`). Pool-edge fields wait for CP5.
- Key 2: build id (4 B); skip if no cheap label (U: `blk.s` has a boot build id; label name not checked).

## 4. Slot rearrangement

Moves: 20 MEMINFO->SYSINFO, 23 ISATTY->CTL. Slots 24, 30, 31 point at `sys_nosys` (`lda #ENOSYS; sec; rts`, ~4 B, shared with CTL's tail) and stay reserved for sys `brk`, LSEEK and later calls. Compacting would renumber 25-29 for 15 B of page room; not worth the churn. Delete `SYS_MEMINFO/ISATTY/CONMODE/DISKIO/CACHE` from `breadbin.inc` so stale `.s` fails to assemble. Change list: `jtab.s` (import line 11, records), `breadbin.inc`, `as.s` SYM (rename two, add `sys_ctl`, `sys_sysinfo`), the 8 programs above plus `free`/`uptime`, `k.inc` export line 104 (`sys_meminfo`), new `KVER`. `tools/kexports.py`, `gen_as_ops.py` need no change.
Migration (each buildable): (a) add errnos (and their `rootfs/etc/errors` lines and the `uci_sim` ERRNO entries), KVER, `sys_nosys`; (b) SYSINFO in slot 20 + `free`/`uptime`/`as.s`; (c) CTL in slot 23 with op 0 + `basic`/`ls`, and rename `sys_isatty` to `sys_ctl` in `as.s`'s SYM table only now (renaming it before `SYS_CTL` exists breaks the build); old 24/30/31 stay live; (d) op 4 + `edit login passwd`; (e) ops 6, 8 + `cache mod`; (f) op 7 + `format`; (g) remove old names/slots (24, 30, 31 -> nosys). Slots 24, 30, 31 are the only free ones: of the five slots the redesign frees, CTL and SYSINFO take two (the draft said 'the page gains 5 slots').

## 5. User BRK and RESTORE kill

BRK opcode: in `brk_handler`, `lda in_kernel; bne panic; ldx cur; cpx #$FF; beq panic`; else `p_sig,x = SIGKILL`, jump to the IRQ `@die` redirect (`proc.s:300-308`), which makes the RTI land in `die_stub`; exit status `$89`. Cost ~16 B. Kernel BRK (in a syscall, boot) still panics, so a kernel bug stays loud. BRK sets the signal directly, so it also kills a process that ignores SIGINT (IGNINT) or runs in the background: a BRK in the shell kills the shell, which is arguably right; the exit status `$89` is the same as `kill -9`. `brk_handler` is in `main.s` while `@die` is a local label in `proc.s`: the redirect needs a global label (+~3 B).
RESTORE: NMI handler becomes `inc nmi_req; rti` (4 B, no register saved). The IRQ tail (next to the RUN/STOP code, `proc.s:251-267`) sees `nmi_req`, clears it, and runs `sigint_fg` with SIGKILL instead of SIGINT. It does not touch process state in NMI context, since an NMI inside `block_on` between `sta p_chan` and `sta p_state` would lose a wakeup. `sigint_fg` hard-codes `lda #SIGINT` (`proc.s:329`): it needs the signal as a parameter (+~3 B). The deferred design is not safer than RUN/STOP against the IRQ window in `block_on` (an IRQ between `check_signal` and `sta p_state` still leaves the kill pending until the channel fires): same behavior as today, not a regression. A second press can be lost between `inc nmi_req` and the tail's clear: harmless. Cost ~20 B + 1 B BSS; latency <= 1 tick.
Failure modes:
- RESTORE: same target set as RUN/STOP: non-BG, non-IGNINT. (BRK differs: see above.) The shell (IGNINT) survives; an idle shell at its prompt makes RESTORE a no-op; a `&` job needs `kill`.
- A foreground process that ignores signals cannot exist (no catch; SIGINT catch comes later and RESTORE stays uncatchable on purpose).
- A process stuck inside a kernel wait that never reaches `check_signal` (formerly the physical-1541 stall, closed 2026-11-18: it was harness DMA; the case is still real for any wedged bus) is not freed: same as RUN/STOP today.
- Pipeline: every non-BG member dies; `proc_exit` closes the pipe ends, so no orphan. Raw console: `con_release` (`proc.s:350`) restores cooked; screen is not repainted.
- init (pid 1) BRK or RESTORE-kill: `proc_exit` panics "init" (V), as today for any pid-1 death. Ultimate freeze button is an NMI too (U): it would kill the foreground; flag in docs.

## 6. Resident byte estimate (U)

Today's handler bytes (est): isatty 18 + conmode 26 + diskio 100 + cache 105 + meminfo 50 = ~300. All of that stays (ops reuse the bodies).
Added: CTL dispatcher 13 + 5 (save and restore A) + 9 ops x 2 = 36, nosys 4 -> 40; CACHE/MODULE split 20; diskio X<-Y shim 6; SYSINFO dispatch 10 + key 0 ~55 + key 2 ~12 -> 77; BRK 16 + 3 (global label); RESTORE 21 + 3 (`sigint_fg` parameter). The conmode fd check (10 B in the draft) is dropped. Sum ~186 B in full; a minimal build (key 0 = `abi, nsys, nctl`, 3 B; no key 2, no tier) is about 186 - 52 - 12 = ~122 B. Saving: 0 B; the jump page still has the same free bytes.
Room: 354 B below `$CF00` -> ~168 after in full, ~232 after minimal (ledger 45eacff, `docs/size-ledger.tsv`). 14 B above BSS/CODEHI: untouched if new code goes in CODE, not CODEHI. This conflicts with CP1's "room >= 300" target (CP1 comes first); CP3 should land after CP1 and may need to trim key 0. Measure with `make size` before and after; quote it in the commit.

## 7. Tests

Today: ISATTY `Boot.test_03_ls_bin`, `test_17/18` (basic); CONMODE `test_24_editor`, `test_25_login_password`; CACHE `Cache.test_off_and_flush`, `test_warm_boot_hits` (`cache` command), MODULE `Modules.*`; DISKIO `Drives.test_format`; MEMINFO `test_22_easy_commands`; RUN/STOP `test_13/14`, `Keyboard.test_run_stop_key`. No host test covers any of them.
New, host first (py65 harness `tools/uci_sim.py` `Sim.sys(name, a, x, y, r0, r1)` runs the real jump table; it looks up names from `breadbin.inc`; no VICE):
1. `tools/test_uci_sim.py`: CTL op 0 on console and file fd (C clear / ENOTTY), bad fd EBADF; op 4 on console ok, on a file ENOTTY; ops 1-3, 5, 9, `$40` give ENOSYS; sysinfo key 0 bytes (`abi=2`, `nsys=32`), key 1 equals the old 5 bytes, key 9 ENOSYS; slots 24/30/31 return ENOSYS; CACHE stat (state 0 with no REU); MODULE list; DISKIO on the boot drive gives EBUSY.
2. Static host test (new, in `tools/test_modules.py` or similar): no `SYS_MEMINFO|ISATTY|CONMODE|DISKIO|CACHE` anywhere in `src/` and `rootfs/`; `NSYS` matches the count in `breadbin.inc`.
3. A stale-binary case instead of the version bump: a program calling a removed slot (24, 30, 31) gets ENOSYS (host test).
VICE: `Boot.test_03,17,22,24,25`, `Cache.test_off_and_flush`, `Modules`, `Drives.test_format`, smoke. New VICE: BRK opcode (tiny program `brk`) kills the program, shell prompt returns, `echo $?`-equivalent shows the status; RESTORE: the py65 sim raises no interrupts (`tools/uci_sim.py` runs a JSR trampoline), so the IRQ tail cannot be run there. It may be injectable in a VICE keyboard test if xdotool can press the key VICE maps to RESTORE (U, to be tried); otherwise the gap stays and the check is manual on the hardware.

## 8. Rollout (each: `make test-host` green)

1. Errnos, KVER, `sys_nosys`, host test scaffolding (red tests for ENOSYS). Gate: smoke.
2. SYSINFO + free/uptime/as.s. Gate: `test_22`, host test.
3. CTL op 0 + basic/ls. Gate: `test_03`, `test_17`.
4. CTL op 4 + edit/login/passwd. Gate: `test_24`, `test_25`, `Keyboard`.
5. CTL ops 6, 8 + cache/mod. Gate: `Cache` (all), `Modules`.
6. CTL op 7 + format. Gate: `Drives.test_format`.
7. Remove old names/slots (no version bump); all programs rebuilt. Gate: full suite (syscall path), host test that a removed slot returns ENOSYS.
8. BRK-opcode and RESTORE kill. Gate: `test_13/14`, new BRK test, smoke. Milestone: full suite + JiffyDOS subset after step 8 (interrupt path changes).

## 9. Decisions for the owner

1. **CP1 target vs CP3 cost.** CP1 says room >= 300; CP3 in full leaves about 168, a minimal build about 232. Which gives: the target, the probe's key 0, or the order (CP3 after more space is found, for instance after the space pass)?
2. **Op numbering.** CTL op numbers are permanent ABI. This spec deviates from cx2 §2.4 by adding op 8 MODULE (the existing cache module ops 4, 5, 6 that `mod` uses are missing from §2.4) and keeping CACHE at op 6 with stat/off/on/flush only. Accept?
3. **CX version.** Not bumped here; fold the bump into CP4 with the CX v2 trailer (a version "2" now would collide with cx2's trailer). Accept?
4. **"sched skips save/restore"** is in the CP3 row of checkpoints.md but not specified here (it is independent). Keep it in CP3's exit criteria, or move it to its own checkpoint?
5. **RESTORE** kills the foreground set RUN/STOP does (the shell survives). Accept? (The alternative, killing the shell, logs the user out.)
6. **"user BRK"** means the 6502 BRK opcode here (a user-mode BRK kills the process); the memory `brk` syscall is CP5. Accept the reading?
7. **SYSINFO key 0:** minimal now (3 bytes: `abi`, `nsys`, `nctl`) and extended later, or with `tier` and `kver` now?

Decided in this draft, not asked: slots 24, 30, 31 stay as ENOSYS holes (later calls fill them); CONMODE keeps ignoring the fd; the Ultimate's freeze-button NMI kills the foreground too and is documented, not distinguished.

## 10. Review triage (hostile reviewer, 11 findings)

| # | Finding | Result |
|---|---|---|
| 1 | CTL dispatcher clobbers A (BLOCK) | Fixed in section 3: save and restore A; +5 B in section 6 |
| 2 | Wrong cite for the version check; step 7 would turn five host tests red (BLOCK) | Fixed: cite is `exec.s:183-185`; the version bump is dropped from CP3, so no host test changes |
| 3 | Version "2" collides with the CX v2 trailer | Fixed with 2; owner decision 3 |
| 4 | Errnos 25 and 38 need `etc/errors` and `uci_sim` entries | Fixed: step (a) |
| 5 | RESTORE cannot be tested in the py65 sim | Accepted as a gap: section 7 says so and names the options |
| 6 | `sigint_fg` hard-codes SIGINT; `@die` is local | Fixed: costed (+6 B) |
| 7 | "Page gains 5 slots"; 145 B figure does not reconcile | Fixed: 3 free slots; minimal build recomputed (~122 B) |
| 8 | CONMODE ENOTTY on non-console fd is a gratuitous break | Fixed: keep ignoring the fd |
| 9 | Lost-wakeup window already exists for RUN/STOP | Rebutted as a new risk, documented as the same window |
| 10 | `as.s` SYM rename order | Fixed: step (c) |
| 11 | BRK also kills IGNINT/BG processes; `$89` equals `kill -9` | Documented in section 5 |
| - | Missing owner decisions: sched-skip, CP1 conflict, op numbering, CX version | Added (decisions 1-4) |
