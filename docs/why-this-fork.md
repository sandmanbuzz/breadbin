# Why this fork

Breadbox is a fork of Breadbin, the Unix-like operating system for the Commodore 64 by Konstantinos Patronas (<https://github.com/kpatr1981/breadbin>). The fork point is upstream commit `aa58d27`, when upstream's version string read 0.2 (`docs/design/upstream-survey.md`).

**The name is temporary.** "Breadbox" was chosen so that the fork is not confused with upstream and makes no claim to track it. It can change if a collision or a better idea turns up. The version string restarts at 0.1 for the same reason: upstream's number is upstream's.

Status: 2026-11-07. Every claim below points at a file or commit in this repo, or at an upstream commit. Upstream moves quickly; where this page compares, it says which upstream commit it looked at: `bb4bba3` on upstream `main` (2026-11-06, upstream version 0.6) and `f896ed2` on its `release-0.6` branch. Re-check before relying on a line.

## What it is

A small Unix-like operating system for the C64, in 6502 assembly (ca65): preemptive multitasking, separate programs in `/bin`, pipes and redirection, signals, a filesystem with directories, and an assembler and BASIC that run on the machine itself (`README.md`). All of that is upstream's work and is shared.

## Why it exists

The direction is in `docs/roadmap.md`: make the C64 a place where real software is written on the machine, starting with a small compiler, and treat an Ultimate (UCI file API, a large REU, turbo) as the recommended hardware without ever requiring it. This fork goes a different way from upstream on a few foundations: it takes over the KERNAL completely, it budgets kernel bytes to give programs more memory, and it is developed by a fleet of AI agents with real hardware in the loop (below). The roadmap says the fork is probably too big to send upstream whole; useful pieces may go as pull requests, and we port from upstream with credit.

## Where the fork differs

Upstream has a lot we also have (see the next section). These are the parts that differ, checked against upstream `bb4bba3`.

- **No KERNAL ROM at all.** Our own interrupt entry, keyboard, screen driver and serial bus (IEC) driver. No Commodore ROM is needed at run time. Upstream has its own IEC driver too (`src/kernel/iec.s`), but it keeps the KERNAL ROM for the screen and keyboard and runs under the KERNAL interrupt path (its `CLAUDE.md`, `src/kernel/main.s`).
- **Kernel modules** (`mod` command), with the CBM DOS filesystem and **UCI v1** (`mount uci /u`) as loadable modules, so an Ultimate's own file API is a mounted filesystem. Upstream has CBM DOS disks built into its kernel (`src/kernel/cbm.s`) and no UCI. `mount uci` passes on the real Ultimate (`docs/hardware-notes.md`).
- **REU block cache** for the boot drive: write-through, keyed by a build id and the disk label (`cache` command, `make CACHE=0|1|2`). Upstream also keeps a copy of drive 8's blocks in the REU as they are read (`84f0981`), which the survey treats as an earlier version of the same idea.
- **`turbo`.** Upstream has no equivalent.
- **Kernel size is measured.** `make size` reports the bytes per module and the headroom, and `docs/size-ledger.tsv` has a row per landing. Upstream also treats RAM as scarce and has an INIT segment and code under the ROM; it has no measurement tool or ledger that we found.
- **User memory.** The user pool is 155 pages (`$0800-$A2FF`, 39,680 bytes), above a stock C64's 38,911 BASIC bytes. Upstream's `release-0.6` gives programs 125 pages (`61f006d`, kernel at `$8500`).
- **Test infrastructure.** Upstream has VICE system tests run in parallel on one machine (`tools/ptest.py`, about 40 minutes by its `CLAUDE.md`) and host tests. This fork adds VICE tests sharded across containers (`tools/ci`, `docs/ci.md`), a real-keystroke test, a py65-based simulator for UCI and for `as`, a fake Ultimate server, a hardware test backend (`tools/ultimatetest.py`), locks for shared machines (`tools/with-lock`), and a landing script (`tools/land.sh`) that builds and runs `make test-host` on the merged tree before it commits.
- **Host-side compiler.** `tools/cc.py`, a C-subset compiler that emits `as` source. It is a host-side reference for now (`README.md`).

## Hardware in the loop

Real hardware is part of the acceptance process, and agents drive it.

- The same system, keyboard and console tests that run under VICE run against a real Ultimate 64 with `BREADBIN_TARGET=ultimate` (`tools/ultimatetest.py`, `tools/ultimate.py`; `docs/testing.md`).
- Hardware is a shared, locked resource (`tools/with-lock -r ultimate`), held by one agent at a time, and findings go to `docs/hardware-notes.md` with the command, date and commit. A hardware agent writes images to a physical 1541 and boots them.
- At a milestone the gate is the full VICE suite, the JiffyDOS-ROM subset, and a hardware run (`CLAUDE.md`). It is a milestone gate, not a per-commit one: hardware answers what only hardware can answer.
- The gate does find things: the physical-1541 stall was found this way and is still open (below).

## What upstream has that we have too

Verified in upstream `bb4bba3`: `exec` (`src/kernel/exec.s`; `login` execs into the shell), BRK in user code kills only that process, shell history with Up/Down, TAB completion, `touch`, `as` and BASIC on the machine, MIT licence. Some of these we ported with credit (TAB completion adapted from `4abb291`, `touch`); the rest (`exec`, BRK kill, history) are our own implementations of features upstream also has, so none of them is a first for this fork.

## What upstream has that we lag on

Tracked in `docs/design/upstream-survey.md`, whose status table is dated 2026-11-04 against upstream `712cc60` and is now 15 upstream commits stale. From the upstream log:

- **Shell:** `$?`, `&&`, `||` and `2>`. We have none of these yet (backlog; not needed for 0.1).
- **Disk:** fast 1541 reads (`7bc197a`, about 1.8 times faster; ours is story M0-8), the CLK pulse at talk turnaround (`ff69a25`, tied to the stall below), the jiffy clock keeping time during disk I/O (`d2e3423`).
- **REU swap:** programs that are not running wait in the REU when memory runs out (`3ad7236`).
- **1581:** a `breadbin.d81` target and `mount` of a 1581, tested in VICE only. Non-1541 drives are nice-to-have for us, not milestone work.
- **`edit` fixes:** several (`1cd090b`, `b84924a`, `683a525`, `1224179`). One equivalent of the flicker fix (`0575584`) has landed here; the others have not been compared.
- **On `release-0.6` only:** `SYS_SEEK`, `fsck` in 18 pages, `tail` reading the last 2 KB, hot kernel variables in zero page.

Job control, a write-back cache and file times are classed "inspiration only" in the survey.

## Platform tiers

From `docs/roadmap.md`. One disk boots everywhere; features are chosen by probing at boot.

| Tier | Machine | Promise |
|---|---|---|
| Classic | stock C64, 1541, no REU | boots to a shell; maintained and tested under VICE; no new features and no speed promises |
| Expanded | Classic plus an REU | adds the block cache and other REU features |
| Recommended | Ultimate with UCI | everything; new work targets this tier first and degrades downward |

The core never requires an REU or an Ultimate.

## Known limits and open issues

- **Physical 1541 root-mount stall: mitigated, not root-caused.** A bounded wait in `bus_acptr` and three retries with UNTALK took about 1 boot in 4 to 13 of 13, and 5 of 5 on a later build (`docs/hardware-notes.md`). On 2026-11-07 a single boot attempt of the candidate build stalled at LOAD, in the known stall path; it was not chased. The 0.1 release does not claim a verified physical-1541 boot. The Ultimate boot is the evidence for the Recommended tier.
- **Keyboard.** A key drop on hardware has been seen once and not reproduced on demand. The VICE test `test_tab_no_match_does_not_fire` fails in its setUp; cause not identified (`docs/testing.md`, "Known issues").
- **Scrolling.** The page-boundary scroll bug (`9cab610`) is fixed and checked in VICE and in the py65 simulator. The commit records no hardware run; the owner checked the release candidate by eye on the real machine.
- **Kernel space is scarce.** 14 bytes above the BSS and `CODEHI`, guarded by a link-time assert; every kernel byte over the room costs user memory a page at a time.
- **Modules trust each other:** no file owners, modes or memory protection (`docs/design/next/modules-v1.md`).
- **Non-1541 drives** are nice-to-have. c64fs v1 compatibility is dropped.

## Credit and licence

The base system is by Konstantinos Patronas and is MIT licensed; `LICENSE` keeps his copyright line as it is, and the boot banner says so ("based on breadbin by ..."). The fork's own code follows the same licence. Ported upstream code carries a "Ported from upstream" header naming the commit. GPL/LGPL code is not brought in (`CLAUDE.md`, licence policy). Commodore and drive ROMs are never in the repo.
