# Feature priority table (design note, draft)

Status: DRAFT for the owner, 2026-11-04. Drafted by a Sonnet pass over `main`, reviewed by a hostile Sonnet pass (arithmetic held; three BLOCK findings and several FIX findings, triaged in section 6), then edited by the hygiene/broad-view agent. Design only. Every kernel figure from a note is a hand estimate unless built.

Frame: better than upstream on features and on user memory (TPA), Ultimate-first. Budget: **361 B below $CF00, 14 B above BSS+CODEHI** (VERIFIED `docs/size-ledger.tsv` last row 6bb4635; `docs/wip.md:21` and `cp3-spec.md:85` still say 354, the older row 45eacff; I use 361). Source is `main`. Doc lines are as read on `main`.

Upstream triage and backlog: see "Status and triage, 2026-11-04" in `upstream-survey.md`.

Two facts that shape everything:
- **A kernel byte over the room costs TPA by page.** Kernel code starts at KSTART ($A200); 361 B is 1.4 pages. Going over by n bytes lowers KSTART by ceil(n/256) pages (ESTIMATE, from `k.inc` policy, `wip.md:92`). So "does not fit" below means "costs this many pool pages".
- **`$?` needs no new kernel bytes, but it is not free.** `sys_wait` already returns the child's exit status in X (VERIFIED `src/kernel/proc.s:460`, `ldx p_exit,y`), which answers the open question at `shell-operators.md:36`. The shell discards that value today and must keep it; builtins and a failed spawn have no status yet; programs that end with `rts` (`cat`, `ls`, `wc`, `head`) exit 0 through `user_ret`, so `cat nofile && run` would still see success until those programs return a real status; and the test in this note needs a `false` program that does not exist. The cost is shell pool pages and some program edits, not kernel bytes.

Bytes are VERIFIED only where a built number or a cited line says so; every kernel figure from a design note is a hand ESTIMATE (the notes say so themselves). "Pool pages" = idle / while running.

## 1. Table

Score: 5 big daily win, 1 marginal. V/B = score x 100 / kernel bytes (range = high to low bytes).

| candidate | user gets | kernel bytes | pool pages | depends | evidence | score, reason | V/B |
|---|---|---|---|---|---|---|---|
| Shell `$?` `&&` `\|\|` | `make && run`, `echo $?`; scripts that branch | 0 (shell, ~40 lines, 0.2-0.25 KB pool; `shell-operators.md:26`) | +0-1 / 0 | none for the register (proc.s:460); the shell must keep it; programs ending in `rts` must return a status; a `false` program | designed | 4: scripting, upstream parity at zero kernel cost | 1.6 priced as pages (4 x 100 / 256 B), free in kernel bytes |
| Shell `2>` `2>&1` | errors to a file | 400-600 (`shell-operators.md:27`; survey says "about 100", a line count, so I use the note) | +1 / 0 | per-process stderr fd; cp3 leaves spawn r2 stderr out (`cp3-spec.md:10`) | designed | 2: nice, not daily | 0.3-0.5 |
| Shell line editor, TAB first | TAB completes commands and files; DEL, CTRL-D | 0 (shell). ~0.5 KB code (`line-editor.md:25`; TAB's `complete` is 159 of the 298 lines, so ~0.25 KB ESTIMATE) | TAB only +1-2; TAB + 4-slot history (256 B) +3; full 8 x 64 history (512 B) +4 (`line-editor.md:25-27`) / 0 | none | designed | 4: upstream top-5 #3, no kernel cost | 0.5-1.0 priced as pages (TAB only +1-2 pages: about 1.0; TAB + 4 slots +3 pages: about 0.5); free in kernel bytes |
| Job control, full (Ctrl-Z, fg, bg, groups) | stop and resume whole pipelines | 1,100-1,700 (`job-control.md:25`) | +1 / 0 | proc/con rework | designed | 4: real multitasking, survey #5 | 0.24-0.36 |
| Job control, smallest kernel (stop flag + SIGSTOP on Ctrl-Z) | Ctrl-Z, fg, bg on single jobs | 300-500 (`job-control.md:32`) | +1 / 0 | none | designed | 3: no pipeline groups | 0.6-1.0 |
| Write-back cache | writes 10x faster on real 1541 | 500-700 (`write-back-cache.md:29`) | 0 (dirty blocks live in REU) | CACHE op 3 flush exists (`cp3-spec.md:25`) | designed | 3: loss on power cut; Ultimate UCI path gains nothing | 0.43-0.6 |
| `sync` program alone | `sync` command | 0 (~0.1 KB program, 1 page; `write-back-cache.md:31`) | +1 while running | none | designed | 1: does nothing until something is dirty | free |
| Fast read M0-8 (upstream #1) | Classic 1541 reads ~1.8x | host 160 + 170 RODATA = 330; writes +250 (`fast-io.md:87`) | 0 | M0-4 done, ROM check per drive | idea (POC for Krill only) | 3: Classic only; the Ultimate-first frame does not need it (`roadmap.md:229`) | 0.9 |
| CP3 full | one control call, probe, BRK/RESTORE kill | 186 (`cp3-spec.md:84`) | 0 | CP1 for room | designed | 3: ABI foundation plus crash survival | 1.6 |
| CP3 minimal | same, key 0 = 3 B | 122 (`cp3-spec.md:84`) | 0 | same | designed | 3 | 2.5 |
| BRK-opcode kill alone | a runaway program dies, not the machine (today: panic, border flash, `main.s:244-262`) | 19 (16 + 3, `cp3-spec.md:72,84`) | 0 | none | designed | 4: only way a crash costs a reboot today | 21 |
| RESTORE kill alone | RESTORE kills the foreground | 24 (21 + 3, `cp3-spec.md:84`) | 0 | none | designed | 2: RUN/STOP already does the same set | 8 |
| S12b `brk` | programs grow at run time | 80-100 (`s12-brk.md:49`; `allocator.md:166` says handler ~45, I use the note's total) | 0 / program grows | free slot 24/30/31 (`cp3-spec.md:67`) | designed | 2: TPA use, helps `as` and compiler | 2-2.5 |
| S8 REU-resident /bin | command loads in ms | 100-300 (ESTIMATE: `k.inc` already has device 1 = REU, NDEV 5) | 0 | S5 | idea | 3: Classic+REU dev loop | 1-3 |
| S11b LOAD_REU | program loads land in REU | 60-120 (ESTIMATE: UCI call lives in `uci.km`; a hook in `exec`) | 0 | S5, S11 done | idea (LOAD REU measured, `wip.md:23`) | 3: Ultimate-first, faster loads | 2.5-5 |
| M0-6 stream primitive | `exec` loads faster | 50-70 (F3) to about 120 (M5), reviewer-found numbers in the notes; the draft's 60-100 was a guess | 0 | M0-4 done | idea | 2 | 2-3.3 |
| S5 block driver table | enabler (REU > 8 MB, device types) | +-0 to 100 (ESTIMATE, replaces `cmp #1`) | 0 | S1 | idea | 1: no direct user value | 1-3 |
| Compiler, host slices (params, char, arrays) | compiler grows | 0 (`tools/cc.py`, `s14-compiler.md:3`) | 0 | none | built (slice 1 tested) | 2: scale example, owner says not the goal | free |
| Compiler on device | edit-compile-run | 0 kernel; user program, ESTIMATE 6-8 KB by analogy with `as` 6.4 KB (`roadmap.md:224`) = 25-32 pages | 0 / 25-32 | S12b or S12a (done), S13 | idea | 2 | free |
| Jiffy clock fix (`d2e3423`) | clock stops losing 6-13 % | ~25 (`upstream-survey.md:21`) | 0 | none | idea | 2 | 8 |
| Cheap ports: tee, tail, sort, touch, edit fixes | pipeline tools, edit safety | 0 | 4-6 pages each while running: tee 909 B, tail 1,473, sort 1,182 (VERIFIED `line-editor.md:30`) | none | built (tee/tail/sort), designed (touch, edit) | 3: free, finish them | free |

## 2. Ranking: build next

The metric is value per kernel byte, but the room is two budgets: kernel bytes (361, and the policy keeps about a page of headroom, so about 105 usable: `wip.md:92`) and pool pages (each 256 B over the room lowers KSTART by a page; each shell page is a page at every idle prompt). Priced in byte-equivalents (256 per pool page), the order by value per cost is: BRK kill 21, RESTORE kill 8, S11b 2.5-5 and S12b 2-2.5 (the S11b figure is a guess), shell `$?` about 1.6, TAB-only about 1.0, TAB plus 4 slots about 0.5. The table's 'free' rows are free in kernel bytes only. The cheap ports (tee, tail, sort, touch) score 3 and cost no kernel bytes: touch is already on main and the others are built, so they are finished work and not a choice. The three below are chosen by value per cost with evidence level as the tiebreak (designed over idea), and the second and third because they cost nothing in the scarce kernel room, which is what the owner is rationing.

1. **BRK-opcode kill (19 B), then RESTORE-kill (24 B) if wanted, standalone or inside CP3.** Best value per cost by 2.5x (21 vs 8). Crash survival is the one thing a user cannot get from the shell.
2. **Shell `$?` `&&` `||`.** 0 kernel bytes, about 1 page of shell (0.2-0.25 KB of program), answers the survey's #4 minus `2>`. Needs the exit-status plumbing described above (programs that end in `rts`, builtins, a `false` program); the gate is a `Boot` test of `false || echo ok` once `false` exists.
3. **Shell line editor, TAB first.** 0 kernel bytes; TAB only costs 1-2 pages of shell, TAB plus a 4-slot history 3 (value per cost halves). After CP3 the editor calls CTL op 4 for raw mode, not `SYS_CONMODE`, so build it after CP3's op numbers are decided or against the current call and migrate with it. Honest TPA note: `line-editor.md:18` says upstream's shell takes 20 pages and ours ~18; a full editor (+4) puts us at ~22, behind upstream on that one number. TAB plus 4 slots (+3) keeps ~21. Measure first (`line-editor.md:32-35`).

Budget arithmetic (ESTIMATE, from the figures above; 14 B above BSS untouched in all cases, all new code goes in CODE):
- **Headroom policy:** `wip.md:92` keeps about a page of headroom so the next small change does not break the build: usable room is about 105 B, not 361. CP3 in full (186 B) therefore costs a pool page in practice, and CP1's own target was room >= 300 B, which only the not-taken case meets (318).
- **Dependencies the draft missed:** CP3 deletes `SYS_CONMODE`, which the shell line editor would call; full job control needs `sys_wait` to report a stopped child, which changes the status encoding `$?` relies on; the $CF00 page holds 2 more slots (14 B free at 6 B per entry: `jsr enter` plus a 3-byte record), not 4.
- **CP3 not taken:** 0 + 0 + 43 (BRK + RESTORE) = 43 B. Left: 361 - 43 = **318 B**. Next spend, one of: fast read 330 (over by 12, one page), job control smallest 300-500 (fits at the low end only), S12b 80-100 (fits, leaves ~218-238).
- **CP3 full taken:** 0 + 0 + 186 (includes the 43) = 186 B. Left: 361 - 186 = **175 B** (the spec's 168 is on the 354 base). Only S12b (80-100) or the small items fit; job control, write-back, fast read all cost pool pages.
- **CP3 minimal taken:** 361 - 122 = **239 B**. Same list, S12b leaves 139-159.
- **The 14 B above BSS** fund nothing here. The real lever is NBUF: 6 to 3 frees 768 B of BSS (`tpa-recovery.md:21`), 6 to 2 frees 1,024 (4 x 256, ESTIMATE; `allocator.md:142` says 1,536 for the pool-backed version). That opens 782-1,038 B above the BSS for cold code to move up (CODEHI, as `cbm.s` did), which lets KSTART rise. It buys more than any feature row, with two caveats found in review: no movable cold code has been sized (the 782-1,038 B above the BSS are room for code that has not been identified), and the slowdown of the Classic disk path with fewer cache buffers is not costed (`allocator.md:142-143` puts about 2 pool pages back for the pool-backed version). Treat NBUF as a measured experiment, not a plan; the BRK-kill checklist's 'NBUF: no change needed' is correct for that item.

## 3. NOT worth it yet

- **Full job control (1.1-1.7 KB):** at least 3 pool pages over the room today. Revisit after NBUF and the CP2 shell-BSS branch (`feat/cp2-sh-bss`, held, `wip.md:37`).
- **Write-back (500-700 B):** needs a decision on data-loss policy; on an Ultimate UCI mount the cache does not apply. `wip.md:25` shows even write-through to a mounted image is not confirmed on the U2 path.
- **Fast read (330 B), fast boot:** a Classic-tier win; the owner's Ultimate-first frame deprioritises it. Not proven on the JiffyDOS drive; the physical-1541 stall is mitigated, not root-caused (`CLAUDE.md`).
- **S5, M0-6:** no user value alone. Kernel line editor (~1,000 B) duplicates the shell version.
- **Compiler on device:** 25-32 pages while running (against 154) for an example of scale; wait for S12b.

## 4. Owner decisions (checklists)

**Shell `$?` `&&` `||`**
- [ ] `$?` value for a killed program: use p_exit as is ($89 for kill, `cp3-spec.md:72`)?
- [ ] `2>` deferred (needs 400-600 kernel bytes)?
- [ ] Kernel bytes: 0.

**Shell line editor**
- [ ] TAB only, TAB + 4 slots (+3 pages) or full 8 x 64 (+4 pages)?
- [ ] Accept the shell moving from ~18 to 19-22 pages (upstream 20)?
- [ ] Kernel placement (CP7) stays closed unless `edit` must share history.
- [ ] Kernel bytes: 0.

**BRK-kill / RESTORE-kill (standalone or in CP3)**
- [ ] Spend 19 B (BRK) and 24 B (RESTORE) now, in CODE, not waiting for the space pass?
- [ ] BRK kills IGNINT and background processes, including the shell (`cp3-spec.md:72`). Accept?
- [ ] RESTORE kills the same set as RUN/STOP, shell survives (`cp3-spec.md:113`). Accept?
- [ ] Ultimate freeze button is an NMI and would kill the foreground (`cp3-spec.md:79`). Accept, documented?
- [ ] NBUF: no change needed.

**CP3**
- [ ] Full (186 B) or minimal (122 B)? What does it displace? Leaves 175 or 239 B.
- [ ] Order: CP3 before or after the NBUF/CP2 room work, given CP1's "room >= 300" target?
- [ ] **Op numbers (permanent ABI):** 0 ISATTY, 1-3 GETFL/SETFL/NREAD reserved, 4 CONMODE, 5 SIGINT reserved, 6 CACHE, 7 DISKIO, 8 MODULE (new, not in cx2 s2.4), >= $40 module range. Accept op 8 and CACHE at 6 with four ops only (`cp3-spec.md:40-50`)?
- [ ] CX version byte not bumped in CP3 (the spec) against bumped (`checkpoints.md:10` row says bumped). I used the spec; it is later and cites the hater finding.
- [ ] SYSINFO key 0: 3 B minimal, or with `tier` and `kver`?
- [ ] "sched skips save/restore" stays in CP3's exit criteria or moves out?
- [ ] Slots 24, 30, 31 stay ENOSYS holes for `brk`, LSEEK, `sync`. (LSEEK landed at slot 32 before CP3, 2026-11-23: `sys_return` left the page to make room. CP3 can renumber it or leave it there.)
- [ ] Page room at $CF00: 14 B free, 3-byte records (`cp3-spec.md:30,46`) against "about 29 B, 6-byte entry" (`s12-brk.md:18,48`). I used the spec (newer, cites jtab.s lines); both say about 4 more calls.

## 5. Compared with upstream

**Ahead (VERIFIED unless marked):** pool of **154 pages** (`CLAUDE.md`, `wip.md:21`), up from 120 at the fork (`checkpoints.md:8`). Upstream's pool is smaller on the numbers in the survey: the kernel at $7800 is 112 pages and at $7F00 is 119 (ESTIMATE: ($7800-$0800)/256 = 112, ($7F00-$0800)/256 = 119; `upstream-survey.md:19,39`), so we are 35-42 pages (29-38 %) ahead. The comparison is weak: 112 is the older figure and 119 the later one, and upstream's later commit moves the library into its kernel, so raw pool pages are not like for like. Kernel modules (CBM DOS, UCI), the REU read cache, Ultimate UCI v1 with LOAD REU measured on hardware, JiffyDOS-tolerant bus, `exec` and `turbo` have no upstream counterpart. Upstream went the other way on the library: `70b9870` moved it into the kernel (`upstream-survey.md:26`); ours is a split user library.

**Still missing from the survey:** Ctrl-Z and process-group job control (`acec2b5`, `64d5f31`); `$?`, `&&`, `||`, `2>`, history (`b64fd2d`); TAB completion (`4abb291`); write-back cache and `sync` (`6d45c40`); 1.8x fast read (`7bc197a`); RESTORE and BRK kill; jiffy clock fix (`d2e3423`); file times and `date` (`0451759`). The three cheapest wins (`$?` and friends, TAB, BRK-kill) cost 19-43 kernel bytes in total, which is why they come first. We lead on the room-neutral side and trail on the big kernel features; those are priced in pool pages above, not hidden.

## 6. Review triage (hostile reviewer, 10 findings)

| Finding | Result |
|---|---|
| BLOCK: `$?` at 0 kernel bytes is true only for the register (shell discards status; `rts` programs exit 0; no `false` program) | Fixed: reworded; the plumbing is listed as the cost |
| BLOCK: ranking contradicts its own metric (shell rows 'free' but cost pool pages; the cheap ports are scored but absent from the ranking) | Fixed: pages priced at 256 B each, re-ranked, ports explained as finished work |
| BLOCK: the 'about a page of headroom' policy is ignored (usable room about 105 B; CP1 target 300 B unmentioned) | Fixed: added to section 2 |
| FIX: NBUF claim (no movable cold code sized, Classic slowdown, allocator.md says 2 pages) | Fixed: caveats added; NBUF is an experiment |
| FIX: missed dependencies (CP3 removes SYS_CONMODE; job control vs `$?` encoding; 2 slots not 4) | Fixed: added |
| FIX: M0-6 'no doc number' was wrong (F3 50-70 B, M5 about 120 B) | Fixed in the table |
| FIX: upstream pool comparison is weak | Fixed: caveat added |
| Arithmetic, 361, the 43/186/122 sums and the V/B scores | Held (checked) |
