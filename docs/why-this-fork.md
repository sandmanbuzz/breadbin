# Why this fork

**Name pending.** The fork is still called Breadbin in this tree. Candidate names are under owner review; this page will be updated when one is chosen.

Status: draft for the owner, 2026-11-06. Every claim below points at a file or commit in this repo. Anything without a source was left out.

## What it is

Breadbin is a small Unix-like operating system for the Commodore 64, written in 6502 assembly (ca65): preemptive multitasking, separate programs in `/bin`, pipes and redirection, signals, a filesystem with directories, and an assembler and BASIC that run on the machine itself (`README.md`). This is a fork of the upstream Breadbin by Konstantinos Patronas (<https://github.com/kpatr1981/breadbin>). The fork point is upstream commit `aa58d27` (`docs/design/upstream-survey.md`).

## Why it exists

The direction is in `docs/roadmap.md`: make the C64 a place where real software is written on the machine, starting with a small compiler, and to treat an Ultimate (UCI file API, a large REU, turbo) as the recommended hardware without ever requiring it. That needed work upstream did not do: replacing the C64 KERNAL, a kernel-space budget, and test infrastructure that does not take 25 minutes per run. The roadmap says the fork is probably too big to send upstream whole; useful pieces may go as pull requests.

## What this fork has that upstream does not

All items below are on local `main`; sources are `CLAUDE.md`, `docs/roadmap.md`, `docs/wip.md` and the commits named.

- **No KERNAL ROM.** Our own interrupt entry, keyboard, screen driver and serial bus (IEC) driver replace the ROM. We therefore need no Commodore ROM at run time.
- **REU block cache** for the boot drive, write-through, keyed by a build id (`cache` command, `make CACHE=0|1|2`). The survey classes upstream's REU disk copy (`84f0981`) as an older version of the same idea.
- **Kernel modules** (`mod` command) with the CBM DOS filesystem and **UCI v1** (`mount uci /u`) as modules, so an Ultimate's own file API is a mounted filesystem. `mount uci` passes on the real Ultimate (`docs/hardware-notes.md`).
- **`exec`** (`SP_EXEC`): `login` execs into `sh`. Also `turbo`, and BRK in user code kills the process (`1e78c68`).
- **Footprint work.** Boot-only code released to the pool, cold code above the BSS, a split user library, and the L1 pass (`c64fe3a`). The user pool is 154 pages (`$0800-$A1FF`) in the CLAUDE.md status; `docs/size-ledger.tsv` has one row per landing and is the number to quote. `make size` measures it.
- **Test infrastructure.** Host tests (`make test-host`), VICE system tests sharded across containers (`tools/ci`, `docs/ci.md`), a real-keystroke test, a py65-based simulator for UCI and for `as`, a fake Ultimate server, hardware test backend for the Ultimate (`tools/ultimatetest.py`), locks for shared machines (`tools/with-lock`), and a landing script (`tools/land.sh`) that builds and runs `make test-host` on the merged tree before committing.
- **Toolchain.** `as` runs on the C64; `tools/cc.py` is a host-side C-subset compiler that emits `as` source. It is a host-side reference for now (`README.md`). A table-driven check of the `as` opcode table exists (`7627968`).
- **Shell.** Command history with Up/Down recall (`5c299d0`) and TAB completion adapted from upstream `4abb291` (`9b5e93e`). `touch` is ported from upstream with credit (`338674b`).

## What upstream has that we lag on

Tracked in `docs/design/upstream-survey.md` (40 upstream commits since the fork point, each with a verdict, and the status table dated 2026-11-04 against upstream `712cc60`). That table predates some landings above (TAB, history, `touch`), so re-check it before relying on a line. Items it lists as missing and wanted: shell `$?`, `&&`, `||` and `2>`; fast 1541 reads (upstream `7bc197a`, about 1.8 times faster; ours is story M0-8); the CLK pulse at talk turnaround (`ff69a25`, an experiment tied to the stall below); the jiffy clock keeping time during disk I/O (`d2e3423`). Job control, a write-back cache and file times are classed "inspiration only". Several `edit` fixes from upstream's `fix/edit` branch were the next cheap ports; at least one equivalent (`0575584`, redraw only what changed) has landed.

## Platform tiers

From `docs/roadmap.md`. One disk boots everywhere; features are chosen by probing at boot.

| Tier | Machine | Promise |
|---|---|---|
| Classic | stock C64, 1541, no REU | boots to a shell; maintained and tested under VICE; no new features and no speed promises |
| Expanded | Classic plus an REU | adds the block cache and other REU features |
| Recommended | Ultimate with UCI | everything; new work targets this tier first and degrades downward |

The core never requires an REU or an Ultimate.

## Known limits and open issues

- **Physical 1541 root-mount stall: mitigated, not root-caused.** A bounded wait in `bus_acptr` and three retries with UNTALK took about 1 boot in 4 to 13 of 13; 5 of 5 on a later build (`docs/hardware-notes.md`). A sector-by-sector read-back of the physical disk stalled at sector 0 and was closed by the owner as-is.
- **Keyboard.** A key drop reported on hardware is unreproduced (a bounded VICE repro lost 0 keys in 6 runs). Separately, the VICE test `test_tab_no_match_does_not_fire` fails in its setUp; cause not identified (`docs/testing.md`, "Known issues").
- **Kernel space is scarce.** 14 bytes above the BSS and `CODEHI`, guarded by a link-time assert; every kernel byte over the room costs user memory a page at a time.
- **Modules trust each other:** no file owners, modes or memory protection (`docs/design/next/modules-v1.md`).
- **Non-1541 drives** are nice-to-have, not milestone work. c64fs v1 compatibility is dropped.

## Credit and licence

The base system is by Konstantinos Patronas and is MIT licensed; `LICENSE` and the README's licence line are kept as they are. The fork's own code follows the same licence. Ported upstream code carries a "Ported from upstream" header naming the commit. GPL/LGPL code is not brought in (`CLAUDE.md`, licence policy). Commodore and drive ROMs are never in the repo.

## Tag readiness (for the owner)

State of local `main` at `3dd2264`, 2026-11-06. SHAs are on `main` (checked as ancestors).

| DONE | OWNER-HELD / OPEN |
|---|---|
| Scroll fix: `9cab610` (scr_scroll doubled rows at page boundaries) | **Owner-held:** the tag itself |
| Create probe: `7a34403` (creates probe before allocating; +21 kernel bytes) | **Owner-held:** banner identity line. The upstream author's email is in the banner at `src/kernel/main.s:111` and `src/bin/version.s:9`, and in `README.md` (lines 5 and 159) and `LICENSE` |
| Footprint L1: `c64fe3a` | **Owner-held:** push decision, and the commit-trailer question. `docs/design/push-readiness.md`: 208 commits unpushed, 30 with a Co-Authored-By trailer; 181 already on origin carry one; 33 on origin are authored as "Claude" |
| NBUF build constant: `01ebe9a` (default 6 unchanged) | **Owner-held:** fork name, and the trademark/existing-project check |
| sh readline and TAB: `9b5e93e` | **Owner-held:** host for the web demo bundle (`docs/webdemo.md`) |
| Shell history: `2a27321` (merge; code `5c299d0`) | **Open technical:** hardware key drop, unreproduced |
| mount / `mod ls` polish: `e0694d1` | **Open technical:** VICE keyboard test `test_tab_no_match_does_not_fire` failing (`docs/testing.md`) |
| Size ledger: `9353b44` (tool) and `docs/size-ledger.tsv` | **Open technical:** full suite not run on the tag candidate. Unverified: no run is recorded for `3dd2264`; `docs/process.md` requires one frozen tip per milestone |
| Land tooling: `86187ad` (`tools/land.sh`), `fb4653e` (names dirty files and owners) | **Open technical:** image write to the physical 1541 for the candidate. Partly unverified: the docs record an image written and 5 of 5 boots on 2026-11-02, and a closed read-back on 2026-11-06 (image from `4ec614f`); nothing is recorded for `3dd2264` |
| Branch-state docs: `c9a4a15` (`docs/wip.md`) | |
