# Handoff: Agent 2 (hardware), 2026-11-02

## ROLE/LANE
Hardware session: the only session that has driven the C64 Ultimate and the physical 1541 since the start. Peer committer, "not the gate but the expert" on the hardware; everyone may take the `ultimate` lock when free (`tools/with-lock -r ultimate -- cmd`). Lane on the board in `docs/wip.md`: IEC recovery, stall bench, UCI measurements, imaging. breadbin-2b claims nothing on hw-bench (settled).

## OWNS
`hw-bench` (old, pre-rewrite refs only on origin), `experiments/iec-stall/` (all tools), `docs/hardware-notes.md` (append-only log), branch `fix/mcdup-timing` (unmerged, see STATE). Local worktree for it: `.claude/worktrees/hw`.

## STATE (done)
- IEC recovery in the bus driver: bounded `bus_acptr` ready wait (~2 s) + `iec_read` retry 3x with UNTALK under ATN. Commit 3d81693, merged 0afbb8d. +56 B code. Physical 1541: 8/8 boots (was ~1 in 4), 5/5 after the module loader; JiffyDOS-drive state: 6/6 with and 6/6 without it.
- Cache A/B on the physical drive: CACHE=0 vs CACHE=2 cold, 10/10 boots, 52 s each (old tree). Warm boot not measured.
- JiffyDOS-ROM VICE sets (JiffyDOS C64 KERNAL + 1541-II ROM, images kept out of the repo, fetched from the Ultimate's flash by FTP): Boot+Cache+Drives 39 OK (cbm-dos tree), Boot 26 OK (0a4dba1), Boot+Drives 30 OK (07f6dd6), Boot+Drives+Pool+Modules+Persistence 34 OK (d991b1a).
- Real Ultimate: UCI v1 first run works (mount, ls, cat, 35,840-byte read/write round trip identical, rmdir non-empty maps); uci.km load/unload (10 pages, `mod ls` empty after umount); Classic (Command Interface off) answers "no such device" and loads nothing; exec/login path OK (`ps` = init, sh, ps).
- UCI measurements (notes): read 44-62 KB/s polled, write 65 KB/s tight loop, LOAD REU 10-12 MB/s; bit 7 (DMA) of the control byte is harmless/no gain; FILE STAT by name fails on a just-written file (UCI v1 doesn't use it); attribute at offset 11 of FILE INFO; absolute names after CD work; `$02` open doesn't truncate; image write-back from a read/write mounted /Temp image was NOT observed.
- Imaging: Keymaster dual-drive GCR nibbler accepted by the owner as THE path to put a D64 on the physical 1541. `mcdup` (27 min, verifying) is the fallback. Disk-copy time breakdown (60 sectors): source read 40 s, write 101 s, full 141 s.
- Branch `fix/mcdup-timing` = 3 commits on origin/main 71ac25f: 12eafdd (tools: nibsetup/nibtest/nibcopy, ucirun, mcdup --variant/--limit, README "Running a hardware job", untrack uci.bin, ignore experiment build outputs), 44f1157 (notes), 6b77884 (nibcopy takes a local image; c64fs image boots 3/3). Ready to merge; nothing in it touches src/.

## IN FLIGHT
Nothing running. Lock free, config restored (below), physical 1541 on bus 8 holding the main-71ac25f image (the owner's usual disk), drive A on bus 9.

## DECISIONS HELD
- Owner: "ATN retry is go"; "everyone on main... main need only be clean, not green; release tags mark shippable states"; origin is a mirror, local is ground truth, force-push allowed (relayed by Agent 4).
- Owner: "Opus-based advisor Agents, when we're chasing shadows" (hypotheses, not evidence).
- Owner: "consider the new imaging path accepted"; "we adopt it until suspected of failure. Failure will put our own copier dev as a preflight item for milestone-next." Own drive-side copier is shelved, design not started (Agent 4: wait for scope decision).
- Owner: nothing needing their hands queued while away; the lock is how we share the machine; the physical media is theirs to swap.
- Privacy (owner's standing rule): no hosts, addresses, usernames, absolute home paths in anything pushed; the Ultimate's address lives in the environment only.

## OPEN
1. Merge `fix/mcdup-timing` (owner: Agent 4/3 at the coalesce). No blocker.
2. Whole-disk sector compare of the physical disk against its image (needs a small reader like mcdup in reverse). Owner: next hardware session. The boot test (3/3) and file-byte checks cover only what is read.
3. Cache warm-boot A/B on hardware (CACHE=1 second boot, matching build id on disk); needs a counter of bus reads or just boot time.
4. Hardware list on current main (boot time, test_02, 13, 07, 10, test_console with BREADBIN_TARGET=ultimate): needs the physical drive OFF or drive A the only device on 8 (collision), so ask the owner or use drive A and the owner's hands for the physical drive power.
5. Stall root cause: unknown. Gone with JiffyDOS ROM + original cable + ferrite clamp (12/12, weak evidence). Reopen if it returns: tools in `experiments/iec-stall/` and the notes are complete.
6. No block checksum: a stall completing with wrong bytes is only excluded indirectly.

## FACTS NOT IN REPO
- Lock: take `tools/with-lock -r ultimate` for the whole job; killing the wrapper does not free the lock while a child holds the file; the holder file can be stale, test with `flock -n` on the lock file. To hold the machine for the owner, run `with-lock -r ultimate -- sleep 21600` in the background, then kill the `sleep` itself (not only the wrapper) to release.
- Normal config: KERNAL `JiffyDOS-C64.bin`, Software IEC enabled (bus 11), turbo off, REU 2 MB, Command Interface enabled, drive A a 1541 with the JiffyDOS 1541-II ROM on bus 9, physical 1541 on bus 8. Config changes made over the REST API are runtime only until a power cycle. Changing the KERNAL needs `machine:reboot`; a reset does not apply it. A run that dies between pause and resume leaves the machine paused: call resume first.
- Clean-bus runs (boot series, imaging): Software IEC disabled, KERNAL `""` (stock), reboot; restore with a trap and verify drives afterwards.
- The Ultimate has no key injection: type by writing PETSCII into `$0277` and the count into `$C6` (see `bench_basic.py`). Never read the screen with a long DMA during a disk transfer. Loading by DMA does not reset the physical drive.
- Drive numbering: the 1541 keeps its device number in RAM (`$77` listen = `$20+n`, `$78` talk = `$40+n`). `open15,8,15,"m-w"+chr$(119)+chr$(0)+chr$(2)+chr$(41)+chr$(73)` makes it 9 (drive A must be off during this). Back to 8: `machine:reboot`, or `UI` on the command channel; `machine:reset` does NOT. `runners:run_prg` and `load_prg` reset the bus and un-renumber it, so load programs by DMA (`$0801`, set BASIC pointers `$2D/$2F/$31/$AE`, type RUN).
- Nibbler (`utils/disk/keym.d.nibbler.prg` on the SD card, fetched by FTP into scratch, env `NIBBLER`): menu keys c/d/#/e; default copy is drive 8 to drive 9; "copy complete" is on screen row 19 (copying: row 16); copy takes 2-3 min; it needs the PRG run via DMA. Imaging steps: `nibsetup.sh up IMG` (stock KERNAL, SoftIEC off, mounts IMG read-only on A), `nibcopy.py IMG` (renumbers physical to 9, A to bus 8 + image, copies, `UI` back), `nibsetup.sh down` (restore + reboot). Re-imaging from a fresh build then boot series: see `reimage` pattern in the README (`bisect.sh COMMIT N` does the slow mcdup version).
- Boot series: `plainboot.py IMAGE.prg` (needs `IMAGE.lbl` for stall dumps); alternate variants, at least 5 each; one run proves nothing.
- Under VICE on macOS: use the bundle's real `x64sc` binary with scratch HOME/XDG dirs and `-directory` (recipe in `docs/testing.md`); VICE tests need the vice lock; a nibbler copy cannot be verified under VICE (writes don't persist as sectors).
- The shared primary checkout can be switched under you by another session: work in your own worktree.

## LESSONS (verified)
- Confounds cost more than hardware: an idle attached 1581, DMA polling during loads, a wrong-layout memory dump, `OPEN` without a filename (sends nothing) each produced a wrong conclusion that was later retracted.
- Timers inside a bus-heavy routine lie: the jiffy clock stops under SEI; black-box total times of variants were what worked.
- A series of 6 passes is weak evidence when the old rate is 25%; say so.
- A hard-coded timeout lost a 25 min run; make long-run limits explicit and print progress.
- Screen-text completion tests need the real row (dump rows with codes once).

## IMPROVEMENTS
- Hardware session: add a whole-disk reader (compare against the image), a bus-read counter for the cache A/B, and a block checksum in the driver; shorten fixed sleeps in `nibcopy.py`; keep the base image so `mcdup --base` can be diff-only.
- Owner: leave a spare, known-good formatted disk and a note of which media is "usual"; a power switch the API can drive for the physical drive would remove the last hand-needed step; stagger session budgets so the fleet doesn't hit its limit together.
