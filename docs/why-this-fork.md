# Why this fork

Breadbox is a fork of Breadbin, the Unix-like operating system for the Commodore 64 by Konstantinos Patronas (<https://github.com/kpatr1981/breadbin>). The fork point is upstream commit `aa58d27`, when upstream's version string read 0.2 (`docs/design/upstream-survey.md`).

**The name is temporary.** Breadbox is the outward name (banner, README, docs); the Breadbin names stay in the internals (`docs/README.md`). "Breadbox" was chosen so that the fork is not confused with upstream and makes no claim to track it. It can change if a collision or a better idea turns up. The version string restarts at 0.1 for the same reason: upstream's number is upstream's.

Status: a snapshot of 2026-11-18, on main `185c35a`. Work since then (the p-code VM and compiled BASIC, `SYS_LSEEK`, the 80-column console, the `fast.km` write path) is in `docs/roadmap.md`, not here. Every claim below points at a file or commit in this repo, or at an upstream commit. Upstream moves quickly; where this page compares, it says which upstream commit it looked at: `0b3f621` on upstream `main` (2026-11-17; its commit messages say version 0.9) and its release branches up to 0.8. Re-check before relying on a line.

## What it is

A small Unix-like operating system for the C64, in 6502 assembly (ca65): preemptive multitasking, separate programs in `/bin`, pipes and redirection, signals, a filesystem with directories, and an assembler and BASIC that run on the machine itself (`README.md`). All of that is upstream's work and is shared. The disk format is c64fs format 2, which is upstream's (`docs/filesystem.md`); we dropped our own v1 and migrated in one step on 2026-11-16.

## Why it exists

The direction is in `docs/roadmap.md`: make the C64 a place where real software is written on the machine, starting with a small compiler, and treat an Ultimate (UCI file API, a large REU, turbo) as the recommended hardware without ever requiring it. This fork goes a different way from upstream on a few foundations: it takes over the KERNAL completely, it budgets kernel bytes to give programs more memory, and it is developed by a fleet of AI agents with real hardware in the loop (below). The roadmap says the fork is probably too big to send upstream whole; useful pieces may go as pull requests, and we port from upstream with credit.

## Where the fork differs

Upstream has a lot we also have (see the next section). These are the parts that differ, checked against upstream `bb4bba3`.

- **No KERNAL ROM at all.** Our own interrupt entry, keyboard, screen driver and serial bus (IEC) driver. No Commodore ROM is needed at run time. Upstream has its own IEC driver too (`src/kernel/iec.s`), but it keeps the KERNAL ROM for the screen and keyboard and runs under the KERNAL interrupt path (its `CLAUDE.md`, `src/kernel/main.s`).
- **Kernel modules** (`mod` command), with the CBM DOS filesystem, **UCI v1** (`mount uci /u`), the 1581 volume driver (`d81`) and the 1541 block-transfer module (`fast`) as loadable modules, so an Ultimate's own file API is a mounted filesystem and the kernel carries none of that unless it is loaded. Upstream has CBM DOS disks and its 1581 support built into its kernel (`src/kernel/cbm.s`) and no UCI. `mount uci` passes on the real Ultimate (`docs/hardware-notes.md`). `d81` has run on the Ultimate's emulated 1581 and, on 2026-11-19, on a physical 1581 (format, copy, remount, read back; one run, no timings; `docs/hardware-notes.md`).
- **JiffyDOS byte protocol**, written clean-room (`docs/design/jiffydos-cleanroom.md`): the serial driver probes each session and uses it with a JiffyDOS drive, and stays on the standard protocol with any other drive (`make JIFFY=0` builds without). Upstream says JiffyDOS "doesn't help, but doesn't get in the way". Tested under VICE with the JiffyDOS ROMs; I found no hardware run of this protocol in `docs/hardware-notes.md`.
- **Fast reads on a stock 1541** (`fast` module, story M0-8): drive-side block transfer, about 1.65 to 1.7 times the standard protocol under VICE (`docs/design/fast-io.md`, section 17). Upstream has its own drive-side routine too ("about twice as fast", its README); ours is a module, VICE-tested, not yet run on a physical drive. Our physical 1541 is not stock (it has a JiffyDOS ROM), so stock ROM behaviour is covered only by VICE; a run on an unmodified 1541 is the missing test.
- **Single-drive disk swap:** `eject` and `reattach` let a one-drive system change disks while `/` is served from the REU cache (`0c060a4`).
- **REU block cache** for the boot drive: write-through, keyed by a build id and the disk label (`cache` command, `make CACHE=0|1|2`). Upstream also keeps a copy of drive 8's blocks in the REU as they are read (`84f0981`), which the survey treats as an earlier version of the same idea.
- **80-column console as a module.** `mod load /lib/km/con80` gives an 80 by 25 text screen on the hires bitmap, with the 40-column console unchanged underneath and back on `mod unload`; it starts at boot with `/etc/con80`. Upstream has no 80-column console. It needs no REU and no Ultimate, and while loaded it claims 39 pool pages (32 of them fixed at `$20-$3F`). Limits: slower scrolling on a stock 1 MHz C64. It is effectively a boot option: on a standard boot the shell already holds `$20-$3F`, so `mod load` from a running system fails with ENODEV, and the working route is `/etc/con80` at boot.
- **`turbo`.** Upstream has no equivalent.
- **Kernel size is measured.** `make size` reports the bytes per module and the headroom, and `docs/size-ledger.tsv` has a row per landing. Upstream also treats RAM as scarce and has an INIT segment and code under the ROM; it has no measurement tool or ledger that we found. The process save area now lives in the RAM under the I/O area (`feat/psave-io`) and cold code above the BSS, which is how format 2, JiffyDOS and the modules fit.
- **User memory.** The user pool is 155 pages (`$0800-$A2FF`, 39,680 bytes), above a stock C64's 38,911 BASIC bytes. Upstream gives programs 125 pages since 0.7 (`61f006d`, kernel at `$8500`) and keeps its hot variables in zero page; we keep zero page stock-shaped.
- **Test infrastructure.** Upstream has VICE system tests run in parallel on one machine (`tools/ptest.py`, about 40 minutes by its `CLAUDE.md`) and host tests. This fork adds VICE tests sharded across containers (`tools/ci`, `docs/ci.md`; 136 of 136 green in 1,439 s on 2026-11-13, one run), a fail-closed per-shard test count, doc drift guards (`tools/test_docs_drift.py`), a real-keystroke test, a py65-based simulator for UCI and for `as`, a fake Ultimate server, a hardware test backend (`tools/ultimatetest.py`), locks for shared machines (`tools/with-lock`), and a landing script (`tools/land.sh`) that builds and runs `make test-host` on the merged tree before it commits.
- **Shell.** `$?`, `&&` and `||` (own implementation; `2>` is not done), history on the console, TAB completion (adapted from upstream with credit), and `&` for background jobs.
- **Host-side compiler.** `tools/cc.py`, a C-subset compiler that emits `as` source. It is a host-side reference for now (`README.md`).

## How we work

We can say little about how upstream works: its acceptance process is not published, and nothing in its repository shows one beyond the test suite its `CLAUDE.md` names. We do not read anything into that. What we can do is make our own process as visible as we can, so here it is.

- **Heterogeneous agentic development.** Least-cost agents work on slices of the system, and higher-cost models serve as consultants and as co-agents with hands on the code. Lanes are a starting point, not walls: agents are encouraged out of their lanes, and because most of the fleet is small models, the work tends toward the narrow.
- **Collective ownership.** The fleet owns the product jointly. Every agent, whatever its model size or responsibility, can touch whatever it needs to.
- **High autonomy.** Agents decide by consensus, with an escalation path. Anything they can tackle as a group, they tackle; the guiding principle is not to block on the human owner. The owner sets direction and holds the decisions that need a person: release, push, naming and hardware access.
- **Orchestration as a service.** A coordinator and facilitator track progress, cost and activity across workstreams and help prioritize. They serve the product's priorities and are not a manager.
- **Tests are table stakes.** Test results tell us where we stand, but they say nothing about whether the code is correct or the approach is right. Green tests are one gate among many: a fresh reviewer is asked to find a reason to block each change, and a failing test is bisected to its cause, not skipped. For example, the 0.1 candidate's full suite caught a data-corrupting 6502 page-wrap bug (a `jmp (ind)` pointer at `$xxFF`) that had landed with every check that was run green; it was bisected, fixed, and the build now refuses to link that pattern.

## Hardware in the loop

Real hardware is part of the acceptance process, and agents drive it.

- The same system, keyboard and console tests that run under VICE run against a real Ultimate 64 with `BREADBIN_TARGET=ultimate` (`tools/ultimatetest.py`, `tools/ultimate.py`; `docs/testing.md`).
- Hardware is a shared, locked resource (`tools/with-lock -r ultimate`), held by one agent at a time, and findings go to `docs/hardware-notes.md` with the command, date and commit. A hardware agent writes images to a physical 1541 and boots them.
- At a milestone the gate is the full VICE suite, the JiffyDOS-ROM subset, and a hardware run (`CLAUDE.md`). It is a milestone gate, not a per-commit one: hardware answers what only hardware can answer.
- The gate does find things: the physical-1541 stall was found this way. It is closed: the cause was the test harness's own DMA reads halting the CPU mid-transfer (below).

## What upstream has that we have too

Verified in upstream: `exec` (`src/kernel/exec.s`; `login` execs into the shell), BRK in user code kills only that process, shell history with Up/Down, TAB completion, `touch`, `$?`, `&&`, `||`, `2>`, `as` and BASIC on the machine, a drive-side fast block routine, 1581 support, `fsck` and `sync`, MIT licence. Some of these we ported with credit (TAB completion adapted from `4abb291`, `touch`); the rest (`exec`, BRK kill, history, `$?`, `&&`, `||`, the fast block transfer, 1581 support) are our own implementations of features upstream also has, so none of them is a first for this fork.

## What upstream has that we lag on

Tracked in `docs/design/upstream-survey.md`, whose status table is dated 2026-11-04 against upstream `712cc60` and is now far out of date (about 50 more upstream commits). Looking at upstream `0b3f621`:

- **Shell:** `2>` (stderr redirection; it needs a per-process error descriptor in the kernel). `$?`, `&&` and `||` are done here.
- **REU swap:** programs that are not running wait in the REU when memory runs out (`3ad7236`). We do not have it; GeoRAM support is also upstream-only.
- **Userland:** `htop`, `who`, `talk` and `mail` for several terminals, a serial terminal on `/dev/ttyS0`, `fsck` in 18 pages, `sync`, and games (chess, tetris). None is ported or planned yet (`SYS_SEEK` and `tail` reading the last 2 KB now have equivalents here: `SYS_LSEEK`, with SEEK_CUR too, on c64fs and UCI); each would be judged by its kernel and pool cost.
- **Drive robustness:** a drive that was reset or stops answering gives an error and keeps working (`6aca717`, `2374af2`). Our IO release (`9d1b949`) bounds the bus waits and retries failed transfers; the two have not been compared line by line.
- **`edit` fixes:** several (`1cd090b`, `b84924a`, `683a525`, `1224179`). One equivalent of the flicker fix (`0575584`) has landed here; the others have not been compared.

**Upstream userspace that has come in with PR #45** (2026-11-19): the size pass of `chess.s` and `tetris.s` was rebased onto upstream `fec4040`, which is newer than the `0b3f621` above and includes the serial-line work (`/dev/ttyS0`, `O_NONBLOCK`, `EAGAIN`; upstream PR #46). The rebased `tetris.s` therefore carries serial-line input: it asks `SYS_ISATTY` about fd 0 and, on a serial line, opens `/dev/tty` with `O_NONBLOCK`. This fork has no serial terminal, so that path should never run here, and the console path is unchanged (`KBNDX`); but it is upstream userspace code we did not write for our kernel. Do not copy the games into this tree without checking that `SYS_ISATTY`, `O_NONBLOCK` and `EAGAIN` exist and behave as that code assumes (the PR also costs tetris 72 bytes for it). The same rebase fixed `a2a3` in chess (upstream treated any input starting with `a` as the AI command): a deliberate change from upstream.

What was on this list on 2026-11-07 and is now done here: fast 1541 reads (the `fast` module) and the JiffyDOS protocol, the 1581 (`d81` module, format 2), `$?`/`&&`/`||`. Job control, a write-back cache and file times are classed "inspiration only" in the survey.

## Platform tiers

From `docs/roadmap.md`. One disk boots everywhere; features are chosen by probing at boot.

| Tier | Machine | Promise |
|---|---|---|
| Classic | stock C64, 1541, no REU | boots to a shell; maintained and tested under VICE; no new features and no speed promises |
| Expanded | Classic plus an REU | adds the block cache and other REU features |
| Recommended | Ultimate with UCI | everything; new work targets this tier first and degrades downward |

The core never requires an REU or an Ultimate.

## Known limits and open issues

- **Physical 1541 root-mount stall: closed (owner, 2026-11-18).** Cause: the test harness's REST reads halt the 6510 (DMA); the sender cannot know, so a halt inside an IEC byte overruns into a hang. VICE and the Ultimate's emulated drives are not halted by a DMA call, so they never showed it. Causal evidence: with DMA 60 retries in 264 block reads over 8 of 8 boots, without 0 in 594 over 18 (p < 1e-6). The bounded waits and retries (3d81693) and the IO release (`9d1b949`, 2026-11-12) stay as defence: on a physical JiffyDOS 1541 session 5 passed 300 write-and-read-back cycles with the cache off and 50 reset-and-boot cycles with it on, 0 failures (`docs/design/io-trial-protocol.md`). Not tested this way: a stock 1541 ROM, a stock-KERNAL boot load, a machine without an REU. One separate follow-up stays open: a "2x" status from the Ultimate's emulated drive A ends the tries without a retry (`docs/design/io-trial-protocol.md`, "fresh media").
- **Keyboard.** A key drop on hardware has been seen once and not reproduced on demand. The VICE test `test_tab_no_match_does_not_fire` that used to fail in its setUp was a harness problem, fixed by `2c42747` (0 of 5 red since; watch for recurrence; `docs/testing.md`, "Known issues").
- **Scrolling.** The page-boundary scroll bug (`9cab610`) is fixed and checked in VICE and in the py65 simulator. The commit records no hardware run; the owner checked the release candidate by eye on the real machine.
- **Kernel space is scarce.** The current room is in `docs/size-ledger.tsv` (`make size`); it was 1,196 bytes below `$CF00` and 643 below `$FFFA` on `185c35a`. A link-time assert guards the region above the BSS; every kernel byte over the room costs user memory a page at a time. A dedicated size pass (research first) is planned.
- **Not yet gated on hardware:** the JiffyDOS protocol, the `fast` module, format 2 and `eject` have VICE tests but no recorded hardware run; the full suite and the hardware list are still owed for this tip.
- **Modules trust each other:** no file owners, modes or memory protection (`docs/design/next/modules-v1.md`).
- **Non-1541 drives** are nice-to-have. c64fs v1 compatibility is dropped.

## Credit and licence

The base system is by Konstantinos Patronas and is MIT licensed; `LICENSE` keeps his copyright line as it is, and the boot banner says so ("based on breadbin by ..."). The fork's own code follows the same licence. Ported upstream code carries a "Ported from upstream" header naming the commit. GPL/LGPL code is not brought in (`CLAUDE.md`, licence policy). Commodore and drive ROMs are never in the repo.
