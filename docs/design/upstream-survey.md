# Upstream survey: commits since aa58d27

Survey of the upstream project's `main` since the fork's baseline `aa58d27`. Local branch; nothing pushed. The table is a survey, not a decision: each verdict is a proposal for the owner and the lanes to take.

## Source and method

- Upstream: `https://github.com/kpatr1981/breadbin` (the clone command in the README; MIT licence, `Copyright 2026 Konstantinos Patronas`). Read through a read-only bare mirror; nothing was pushed or written upstream. `aa58d27` is in our history. Commits counted: `aa58d27..HEAD` on upstream `main` (40). The upstream branches `feat/format-v2`, `feat/tab-complete`, `feat/touch`, `fix/edit`, `fix/test-scratch`, `fix/webdemo-cache` and the release branches are **not** in this table; they are unmerged or release-only.
- Each commit was read by a fresh subagent (Sonnet, medium effort, empty context, four batches of ten) with the same tight questions: the end-user effect, the verdict, a one-line reason, a rough kernel-byte cost and the files touched. The rows were then spot-checked against the commits (commit stats, and the kernel diff of `1573734`). Kernel bytes are the subagents' estimates, not measured; `unknown` means not estimated.
- Verdicts: **port** = take the feature into our tree as is, with credit (MIT); **shape-of** = build our own version of the idea; **skip** = not for us. Our rules that drive the verdicts: kernel space is scarce (a kernel byte is user memory); c64fs v1 compatibility is dropped; zero page stays stock-shaped; non-1541 devices are not milestone work.

## The table

| commit | upstream subject | size (files, +, -) | what a user sees | verdict | one-line reason | kernel bytes (est.) | files |
|---|---|---|---|---|---|---|---|
| `acec2b5` | feat: Breadbin 0.3 kernel and programs | 20, +1239, -0 | Own IEC bus driver, GeoRAM /tmp, job control (Ctrl-Z, fg, bg, jobs), software clock, kernel fixes | shape-of | a bundle; our bus and REU already differ; take job control and unlink-open ideas, not the commit | unknown (about 1200 lines across blk, iec, proc, file, con) | src/kernel/iec.s, proc.s, blk.s, file.s |
| `aa2f787` | build: test image, Open ROMs tests, browser demo, demo video, proof tool | 5, +540, -0 | none (docs/tests/build) | skip | test image, web demo, video and proof tools only | 0 | Makefile, tools/webdemo.py, tools/demovideo.py, tools/proof.py |
| `d34097a` | test: job control, GeoRAM, REU boot and kernel regression tests | 7, +394, -0 | none (docs/tests/build) | skip | regression tests and helper programs only | 0 | tests/* |
| `90082d8` | docs: programming guide, real hardware, FAQ, related projects | 4, +459, -0 | none (docs/tests/build) | skip | README, programming guide and examples only | 0 | README.md, docs/programming.md |
| `64d5f31` | fix: jobs as process groups, review bugs, kernel at $7800 | 15, +664, -0 | jobs are process groups; fg and bg act on whole pipelines; leak and errno fixes | shape-of | the process-group design and fixes are useful; proc, file and blk have diverged | unknown (about +300 net lines across proc, file, blk, exec) | src/kernel/proc.s, file.s, blk.s, src/bin/sh.s |
| `6d45c40` | feat: write-back block cache, sync; parallel test runner in make test | 13, +302, -0 | disk writes much faster (write-back cache); new sync command | shape-of | a big win on the 1541; we have our own REU block cache, so adapt the write-back only if bytes allow | unknown (about +100 lines in blk.s, plus a syscall) | src/kernel/blk.s, file.s, fs.s, src/bin/sync.s |
| `d2e3423` | fix: jiffy clock keeps time during disk I/O | 3, +57, -0 | system clock no longer loses 6 to 13 percent of time during disk access | shape-of | a small good idea (count jiffies in the bus waits); our bus code and IRQ differ | about 25 | src/kernel/iec.s, proc.s |
| `b64fd2d` | feat: shell $? && // 2> history, RESTORE kills, fsck | 13, +1532, -0 | shell gets $?, &&, ||, 2> redirection and line history; RESTORE kills a program; new fsck | shape-of | the shell and fsck are userland (c64fs v1 fsck dropped); RESTORE-kill and the stderr flag are kernel ideas worth redoing | about 100 (main, proc, exec, cbm; shell and fsck are userland) | src/bin/sh.s, fsck.s, src/kernel/main.s, proc.s |
| `2ff35e5` | feat: multi-block bitmap; the REU RAM disk uses the whole REU | 3, +251, -0 | multi-block c64fs bitmap; the REU RAM disk uses the whole REU | skip | c64fs v1 dropped; our REU serves the block cache, not a RAM disk | 0 | src/kernel/fs.s, src/bin/fsck.s |
| `84f0981` | feat: drive 8's disk is copied into the REU as it is read | 4, +187, -0 | drive 8's disk is cached in REU, so repeat reads are near-instant | skip | we already have an REU block cache for the boot drive; this is its older version | 0 | src/kernel/blk.s, fs.s |
| `7bc197a` | feat: fast reads from drive 8 with code in the 1541; review fixes | 12, +446, -0 | drive 8 reads about 1.8 times faster, via code uploaded into the 1541 | shape-of | a big win for the Classic tier, but it needs our own fast read (M0-8) on our bus code; kernel-heavy | unknown | src/kernel/blk.s, drive.s, exec.s, src/bin/passwd.s |
| `70b9870` | feat: process save areas under the KERNAL ROM; the user library in the kernel | 13, +612, -0 | programs use far less RAM (3 to 5 pages each): the shared library moved into the kernel | shape-of | moves the library into the kernel, costing kernel space; our split-library design differs; weigh against the pool | unknown | src/kernel/ulib.s, jtab.s, proc.s, src/lib/lib.s |
| `37a0ce8` | feat: exec(), more tables under the ROM, as streams its output; 0.4 | 22, +322, -0 | exec replaces a process in place; login becomes the shell; as and edit use less RAM | shape-of | we already have SP_EXEC; the streaming as output and the ENOTDIR and passwd fixes are worth reimplementing | unknown | src/kernel/exec.s, file.s, src/bin/as.s, passwd.s |
| `04f3a47` | feat: tee, tail and sort | 6, +554, -0 | new tee, tail and sort commands for pipelines | port | self-contained user programs on the library; no kernel cost | 0 | src/bin/tee.s, tail.s, sort.s, rootfs/etc/help |
| `77a8c88` | build: ptest --logdir, so suites can run side by side | 1, +4, -0 | none (docs/tests/build) | skip | test-runner log directory option only | 0 | tools/ptest.py |
| `8f6a5ee` | test: the RAM-disk tests copy enough of the smaller as to fill /tmp | 2, +6, -0 | none (docs/tests/build) | skip | test adjustments for their RAM-disk size | 0 | tests/test_bugs.py, test_features.py |
| `1573734` | fix: the console takes the underscore graphic ($a4) as '_'; VICE keyboard notes | 4, +15, -0 | the console takes VICE's underscore graphic as '_', so underscore can be typed | port | a two-line console key mapping fix; helps VICE users; check our keytab still matches | 2 | src/kernel/con.s, rootfs/etc/help, README.md |
| `4cc3c7e` | feat: touch | 5, +103, -0 | new touch command creates missing files and leaves existing ones unchanged | port | a one-page user program; adapt to our open semantics (c64fs v1 is dropped) | 0 | src/bin/touch.s, rootfs/etc/help, tests/test_features.py |
| `0637443` | docs: CLAUDE.md for contributors' Claude sessions; timestamps and .d81 design | 2, +204, -0 | none (docs/tests/build) | skip | contributor CLAUDE.md and the timestamps and .d81 design | 0 | CLAUDE.md, docs/design-timestamps-d81.md |
| `f99857e` | build: ignore personal Claude settings | 1, +1, -0 | none (docs/tests/build) | skip | a .gitignore line for personal Claude settings | 0 | .gitignore |
| `ffa6cac` | build: a shared Claude hook pulls before every prompt and passes on a changed CLAUDE.md | 3, +85, -0 | none (docs/tests/build) | skip | a Claude sync hook for their collaborators; dev tooling only | 0 | .claude/settings.json, CLAUDE.md, tools/claude-sync.sh |
| `78bcda3` | build: the Claude sync hook is opt-in, in each collaborator's own settings | 3, +17, -0 | none (docs/tests/build) | skip | makes that sync hook opt-in; dev tooling only | 0 | .claude/settings.json, CLAUDE.md |
| `1d60901` | docs: CLAUDE.md format changes include the RAM disk and a new magic | 1, +3, -0 | none (docs/tests/build) | skip | CLAUDE.md notes on format changes; a process doc | 0 | CLAUDE.md |
| `c6fdd31` | docs: timestamps and .d81 design covers the RAM disk, a new magic and the superblock at 376 | 1, +15, -0 | none (docs/tests/build) | skip | design doc for timestamps, .d81, a new magic, the superblock at 376; design reference only | 0 | docs/design-timestamps-d81.md |
| `a9a1b27` | docs: the kernel starts at $7F00 in the README and the programming guide | 2, +2, -0 | none (docs/tests/build) | skip | docs say the kernel starts at $7F00; our memory map differs | 0 | README.md, docs/programming.md |
| `6eb945c` | docs: format v2 design settles the magic (C64F2), last_time's place, the ls -l date and the reserved inode bytes | 1, +7, -0 | none (docs/tests/build) | skip | design doc settles the C64F2 magic, last_time, the ls -l date and reserved inode bytes | 0 | docs/design-timestamps-d81.md |
| `c7547cd` | fix: help's keyboard line fits 40 columns | 1, +1, -0 | help text keyboard line shortened to fit 40 columns | skip | a one-line cosmetic text change; our help text differs | 0 | rootfs/etc/help |
| `0482f6f` | test: system tests name their scratch images per run, so suites can run side by side | 1, +12, -0 | none (docs/tests/build) | skip | system tests name scratch images per run so suites run in parallel | 0 | tests/test_system.py |
| `4b8ae22` | build: one definition of the c64fs magic | 7, +30, -0 | none directly (build refactor); saves 5 bytes of kernel RAM by sharing one magic copy | shape-of | one C64FS_MAGIC define; our fork dropped c64fs v1, so the magic will differ | -5 | include/breadbin.inc, src/kernel/fs.s, cbm.s, src/bin/fsck.s |
| `9478ed0` | feat: mkimage builds format 2 images (--format 2) and upgrades format 1 images | 2, +377, -0 | none yet: the host tool builds format 2 images (64-byte inodes, mtime and ctime, magic C64F2) | shape-of | the image-tool side of timestamps; the kernel does not read format 2 yet; c64fs-bound | 0 | tools/mkimage.py, tools/test_mkimage.py |
| `94ef287` | docs: CLAUDE.md lessons: tight polling for bus pulses, warp time in tests, BB_HANGDUMP | 1, +8, -0 | none (docs/tests/build) | skip | CLAUDE.md lessons about polling and test tooling | 0 | CLAUDE.md |
| `2beac0a` | test: tests delete their disk image copies and stop their VICE when they exit | 5, +26, -0 | none (docs/tests/build) | skip | test harness cleanup of image copies and stray VICE processes | 0 | tools/vicetest.py, tests/* |
| `4abb291` | feat: CTRL-I (TAB) in the shell completes command and file names | 6, +229, -0 | press TAB in the shell to complete command and file names, listing ambiguous matches | port | a user-space shell feature with no kernel cost; our shell footprint must be rechecked | 0 | src/bin/sh.s, include/breadbin.inc, rootfs/etc/help, tests/test_features.py |
| `5f2a9ec` | feat: c64fs format 2: 64-byte inodes with room for times, magic C64F2 | 14, +162, -0 | none directly; disks become c64fs format 2 (64-byte inodes, magic C64F2); old disks refused | skip | breaks our c64fs line; we use the CBM DOS module filesystem; the timestamp idea is covered by 0451759 | 11 | src/kernel/fs.s, cbm.s, src/bin/format.s, fsck.s |
| `0451759` | feat: file times: the kernel keeps a clock, files get mtime and ctime; date, touch, ls -l and stat use them | 21, +938, -0 | the system clock keeps time; date sets it; ls -l and stat show file times; touch works | shape-of | the clock and date are useful; file times are tied to c64fs inodes, and CBM DOS has none | unknown | src/kernel/proc.s, fs.s, src/lib/date.s, src/bin/date.s |
| `5eb72f0` | fix: fsck counts block 0 as in use on disks without a boot file | 2, +5, -0 | fsck no longer reports block 0 as used on fresh disks | skip | fixes c64fs fsck only; we dropped c64fs v1 and its tooling | 0 | src/bin/fsck.s, tests/test_system.py |
| `ff69a25` | fix: the serial bus catches a fast drive's short CLK pulse at the talk turnaround | 1, +10, -0 | fixes a freeze when booting from a fast 1581 drive on the serial bus | shape-of | polling CLK every 11 cycles at talk turnaround may help our 1541 root-mount stall; adapt to our bus code | 3 | src/kernel/iec.s |
| `bf712c2` | feat: 1581 drives and .d81 images: boot from them, mount, format and fsck them | 13, +684, -0 | boot from, mount, format and fsck 1581 drives and .d81 images | skip | non-1541 devices are not milestone work for us; built on c64fs and blk layers we lack | unknown | src/kernel/blk.s, cbm.s, file.s, src/bin/format.s |
| `1095f03` | test: BB_HANGDUMP=file dumps the C64 and drive CPUs when a test times out | 1, +53, -0 | none (docs/tests/build) | skip | a test-harness hang dump for VICE | 0 | tools/vicetest.py |
| `712cc60` | build: version 0.5 (format 2 disks, file times, 1581, tab completion) | 4, +5, -0 | version strings now report 0.5 | skip | a version bump; our versioning is our own | 0 | src/kernel/main.s, src/bin/uname.s, version.s, tests/test_system.py |

## Top five by user value

Ranked by what a user of the OS gains, with our constraints taken into account. Cheap ports (no kernel cost) are listed after these, because they are the fastest wins, not the most valuable.

1. **`7bc197a` drive 8 reads about 1.8 times faster** (shape-of). The largest everyday gain for the Classic tier. It belongs to M0-8 (fast read), which needs our own bus code; the kernel cost is unknown and likely large.
2. **`6d45c40` write-back cache and `sync`** (shape-of). Disk writes are much faster. Our REU block cache covers reads only, so the write-back is the part to adapt, if the bytes allow.
3. **`4abb291` TAB completion in the shell** (port). Command and file name completion, no kernel cost. Recheck our shell footprint (the shell is a pool-page user) before taking it.
4. **`b64fd2d` shell `$?`, `&&`, `||`, `2>`, history; `RESTORE` kills a program** (shape-of). Scripting and error-handling for users. The shell and the RESTORE-kill idea are ours to redo; the kernel part is about 100 bytes.
5. **`acec2b5` job control** (Ctrl-Z, `fg`, `bg`, `jobs`) (shape-of). Real multitasking for the user. Take the design (the process-group idea in `64d5f31` is the core of it), not the commit; the bundle touches our diverged bus and process code.

Cheap ports, zero kernel cost: `04f3a47` (tee, tail, sort; port), `4cc3c7e` (touch; port), `1573734` (underscore on VICE; port, two kernel bytes).

## Not in this survey

- The unmerged upstream branches (listed above). Their features need the same reading before any call.
- Upstream's documentation and test changes, which are skip by rule above (they cost nothing and teach nothing new about the OS).

## Unmerged upstream branches

Upstream branches with commits that are not on upstream `main`: `feat/format-v2` (6), `fix/edit` (5), `feat/tab-complete` (1), `fix/test-scratch` (1), `fix/webdemo-cache` (1). `feat/touch`, `release-0.3` and `release-0.4` add nothing beyond `main`. Same method as the table above (empty-context Sonnet subagents, two batches of seven, spot-checked against the commits; the subagents noted where the same change is already on main). Kernel bytes are estimates.

| branch | commit | size (files, +, -) | what a user sees | verdict | one-line reason | kernel bytes (est.) | files |
|---|---|---|---|---|---|---|---|
| feat/format-v2 | `b422525` | 14 files, +162, -0 | c64fs disks switch to 64-byte inodes with time fields; old kernels refuse them | skip | fork dropped c64fs v1 and replaced the filesystem; already on main as c64fs format 2 (5f2a9ec) | 11 | src/kernel/fs.s, cbm.s, src/bin/format.s, fsck.s |
| feat/format-v2 | `7564994` | 21 files, +938, -0 | kernel keeps a clock; files get mtime and ctime; date, touch, ls -l and stat show them | shape-of | useful idea, but tied to c64fs inodes; already on main as file times (0451759) | unknown | src/kernel/proc.s, fs.s, src/lib/date.s, src/bin/date.s |
| feat/format-v2 | `3c9b3ef` | 2 files, +5, -0 | fsck no longer reports block 0 on freshly formatted disks | skip | fixes c64fs fsck, which the fork dropped; already on main (5eb72f0) | 0 | src/bin/fsck.s, tests/test_system.py |
| feat/format-v2 | `00fc737` | 1 files, +10, -0 | a freeze booting from a 1581 is fixed (CLK polled every 11 cycles at talk turnaround) | shape-of | our bus code differs and is patched for stalls; already on main (ff69a25) | unknown | src/kernel/iec.s |
| feat/format-v2 | `165e02c` | 13 files, +684, -0 | boot from, mount, format and fsck 1581 drives and .d81 images | skip | non-1541 devices are not milestone work for us; built on the c64fs layout; already on main (bf712c2) | unknown | src/kernel/blk.s, cbm.s, file.s, tools/mkimage.py |
| feat/format-v2 | `14d756b` | 1 files, +53, -0 | none (docs/tests/build) | skip | VICE hang dump only; already on main (1095f03) | 0 | tools/vicetest.py |
| feat/tab-complete | `ecabba9` | 6 files, +229, -0 | press TAB in the shell to complete command and file names | shape-of | the same feature is on main as 4abb291; the branch is a variant; take main's version | 0 | src/bin/sh.s, include/breadbin.inc, rootfs/etc/help, tests/test_features.py |
| fix/edit | `6b66acc` | 1 files, +8, -0 | edit no longer draws memory past the text when a file ends past a page boundary | port | fixes an at_end borrow bug; our edit.s has the same code; not on upstream main | 0 | src/bin/edit.s |
| fix/edit | `c27f6c5` | 1 files, +38, -0 | edit stops flickering: cursor keys redraw only the cursor; status line only on change | shape-of | user-program UX fix; 38 added lines may collide with our edit.s, so rework the idea against our tree | 0 | src/bin/edit.s |
| fix/edit | `62cb12f` | 1 files, +23, -0 | edit refuses a file over 8 KB instead of silently truncating it on save | port | prevents data loss on save; small self-contained load() change; user program only | 0 | src/bin/edit.s |
| fix/edit | `1a3843b` | 1 files, +56, -0 | edit's ^K (kill line) is much faster: one block move instead of one per character | port | replaces a per-character delete loop with one block move; user program; check against our edit.s | 0 | src/bin/edit.s |
| fix/edit | `a73842c` | 1 files, +103, -0 | none (docs/tests/build) | skip | tests only (103 lines in test_features.py); a reference if the edit fixes are ported | 0 | tests/test_features.py |
| fix/test-scratch | `0eb29c1` | 5 files, +26, -0 | none (docs/tests/build) | skip | test-harness cleanup (deletes image copies, kills stray VICE); we have our own tooling | 0 | tests/test_bugs.py, test_features.py, test_system.py, tools/vicetest.py |
| fix/webdemo-cache | `9210ff2` | 1 files, +12, -0 | none (docs/tests/build) | skip | browser demo cache-busting name; our tree has no tools/webdemo.py | 0 | tools/webdemo.py |

The `fix/edit` port candidates (`6b66acc`, `62cb12f`, `1a3843b`) are user-program fixes with no kernel cost; they are the next cheap ports after the three in the plan.


## Status and triage, 2026-11-04 (upstream 712cc60)

Fork point: `aa58d27` (merge-base of our main and upstream main). Upstream has 40 commits on main since then, plus 14 on unmerged branches. This section adds our local status (HAVE, PARTIAL, MISSING, checked by grep against main, not built) and a verdict and priority per group. The verdicts above still describe each commit; this table groups them and ranks them.

Upstream's kernel lives under the KERNAL ROM. Ours replaces the KERNAL, so upstream kernel diffs never apply raw. Every port is reworked against our tree and carries the "Ported from upstream" header. Kernel byte figures are estimates.

Verdicts: ACCEPT (port it), SHAPE-OF (take the idea, write our own), INSPO (read for ideas, no work planned), REJECT.

| group | upstream SHAs | local status | verdict | priority | note |
|---|---|---|---|---|---|
| edit fixes (branch fix/edit) | `c27f6c5` `62cb12f` `1a3843b`, tests `a73842c` | MISSING (the at_end fix `6b66acc` is HAVE) | ACCEPT | P1 | Refusing a file over 8 KB prevents data loss; also no flicker, fast ^K. Port into our `edit.s`, which may have diverged. |
| console underscore | `1573734` | MISSING | ACCEPT | P2 | 2 kernel bytes. Check `keytab.inc` for `$a4`. |
| TAB completion | `4abb291` `ecabba9` | MISSING | ACCEPT | P2 | 0 kernel bytes. Check the `sh` pool footprint first. |
| bus CLK pulse at talk turnaround | `ff69a25` | MISSING | ACCEPT AS EXPERIMENT | P1 | About 3 bytes. Hardware question: does it bear on the 1541 root-mount stall? The 1581 benefit is incidental. |
| shell `$?` `&&` `\|\|`, history | `b64fd2d` | MISSING | SHAPE-OF | P2 | Already on our feature priority list, 0 kernel bytes. RESTORE kill is covered by our CP3 spec. `2>` needs a kernel flag: weigh the bytes. The fsck part is REJECT (c64fs only). |
| jiffy clock during disk I/O | `d2e3423` | MISSING (unverified) | SHAPE-OF | P3 | Our `iec.s` and IRQ entry differ. Measure the drift first. |
| fast 1541 reads | `7bc197a` | MISSING | SHAPE-OF under M0-8 | P3 | Read the file headers for licence and origin before any reuse. |
| exec in place, streaming `as` | `37a0ce8` | PARTIAL (`SP_EXEC`, ENOTDIR exist) | INSPO | - | Verify the ENOTDIR and passwd fixes apply to us. |
| write-back cache, sync | `6d45c40` | MISSING | INSPO | - | Reset can lose data. Our cache is write-through by design. |
| job control, process groups | `acec2b5` `64d5f31` | MISSING | INSPO | - | Design only. Costs kernel space. |
| file times, format 2 | `0451759` `5f2a9ec` `4b8ae22` `9478ed0` | MISSING | INSPO | - | Idea only. c64fs v1 is dropped and CBM DOS has no times. |
| test hooks | `1095f03` (BB_HANGDUMP), `0482f6f` (per-run scratch names) | MISSING | INSPO | - | For our test infrastructure. |
| save areas under ROM, library in kernel | `70b9870` | MISSING by choice | REJECT | - | Kernel space; our layout differs (split user library, pool). |
| 1581 | `bf712c2` | MISSING | REJECT | - | Non-1541 devices are not milestone work. |
| c64fs-only | `2ff35e5` `84f0981` `5eb72f0` | n/a | REJECT | - | c64fs v1 is dropped. |
| GeoRAM, fsck | - | MISSING | REJECT | - | The core never requires an REU; fsck is c64fs only. |
| tee, tail, sort, touch | `04f3a47` `4cc3c7e` | HAVE | done | - | Already ported. |

Docs, tests, build and version commits are skipped by the rule above.

### Backlog

Ordered by usefulness to us, then great idea, then parity.

P1:
- edit fixes: 8 KB refuse first (data loss), then the flicker fix, then ^K block move; port the tests `a73842c` with them.
- CLK pulse at talk turnaround: run as a hardware experiment on the 1541 root-mount stall.

P2:
- Shell `$?` `&&` `||` and history (0 kernel bytes; follow the feature priority table).
- TAB completion (measure `sh` pool pages first).
- Console underscore (2 kernel bytes).

P3:
- Jiffy clock across disk I/O (measure drift first).
- Fast 1541 reads under M0-8 (check licence and origin first).
