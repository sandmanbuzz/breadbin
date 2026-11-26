# Breadbox

A Unix-like OS for the Commodore 64 (6502 assembly, ca65). Naming is a working rule, not final: **breadbox** is this project, the published repo and this body of work; **breadbin** is the upstream it is a variant of. Say breadbox for what is ours and breadbin for unchanged upstream parts and for file names still carrying the old name (`build/breadbin.d64`, `BREADBIN`, `include/breadbin.inc`). Read `docs/process.md` (how sessions work together: branches, the machine lock, kickoff) and `docs/roadmap.md` first: it holds the direction, the decisions below in full, and the story list. `docs/wip.md` says where things stand right now and who is doing what; `docs/hardware-notes.md` is where findings from the real Ultimate and 1541 are recorded. `README.md` describes the system; `docs/testing.md` says which tests to run.

## Build and test

```sh
make                  # build/breadbin.d64 (needs cc65; about 2 seconds)
make test-host        # image tools, key tables, Ultimate client; no emulator, about 12 seconds
tools/ci/run.sh all test-host   # the same in the container, plus the py65 simulator tests that skip without a built image
make size             # bytes per kernel module and the headroom; quote it in commits
tools/ci/run.sh test-smoke      # boot, echo, pipe, Ctrl-C: about 2 minutes
tools/ci/run.sh test-only T="tests.test_system.Boot.test_24_editor"
tools/ci/run.sh test-keyboard   # real keystrokes (xdotool); also test-console; docs/ci.md
tools/ci/sharded.sh             # the whole suite, six containers at once (podman; about 24 minutes; `sharded.sh --check` prints the test count)
# Serial `run.sh test` holds every slot for about two hours and is refused without --serial-because "<why>".
```

The VICE tests need C64 and 1541 ROMs, which are not in the repo: run `tools/setup-vice-roms.sh` once. VICE runs only in the container (`tools/ci/run.sh`; host VICE is being retired). Run targeted tests per change and the full suite at milestones (136 tests in 1,439 s sharded on 6158182, `docs/ci.md`; the serial 63-test run took 2,804 s, so serial is now about two hours). `run.sh` takes a `vice` slot itself (a pool of 12, `docs/process.md`); a work unit should take about six slots (a guideline: be polite about the pool), and a run whose timing you will quote takes every slot (`BREADBIN_CI_EXCLUSIVE=1`, `sharded.sh --exclusive`), saying why in its note. Hardware runs go under `tools/with-lock -r ultimate`.

## Test policy

Targeted tests inside a story, the full regression at milestones. Tests are slow (the full suite is about 24 minutes sharded under VICE in a container, and hardware runs are slower), and a long-lived context is cheaper than a restarted one, so:

- **During a story:** `make test-host`, the targeted tests for what you changed (the table in `docs/testing.md`), and `tools/ci/run.sh test-smoke` before committing. No full suite.
- **At a milestone** (the end of an M group, or any change to the interrupt path, the bus, the memory map or the linker layout): the full suite with stock ROMs, the disk and bus tests again with the JiffyDOS ROMs (`BREADBIN_CI_JIFFY=<dir>`, see `docs/testing.md`; not yet proven in the container), and a hardware run of the list in `docs/hardware-notes.md`.
- **Hardware** is used for what only hardware can answer, not as a per-story gate. Keep one hardware session alive with its context and give it experiments (`docs/wip.md`), not just test runs.
- Say in every commit message what was run and what was not.

## Decisions (details in `docs/roadmap.md`)

- **Platform tiers:** Classic (stock C64, 1541, no REU) must keep booting; Expanded adds an REU; Recommended is an Ultimate with UCI. The core never requires an REU or an Ultimate. Features are chosen by probing at run time.
- **c64fs v1 compatibility is dropped.** Non-1541 devices (1581 and others) are nice-to-have, not milestone work: leave a clean campsite, do not design around them.
- **Zero page stays stock-shaped.** A stock address keeps its stock meaning wherever we still provide the service; poach only what we have retired, and document it. Do not turn zero page into foreign territory.
- **Kernel space is scarce.** Measure with `make size`; a deliberate space pass (M0-7) comes after all KERNAL replacements.
- **Contract drift:** internal behavior may improve if the call looks the same and does not violate least surprise. The user-facing contract matters more than the vintage one.
- **Licence policy:** the repo is MIT and our own code is informal/public domain. Do not bring in GPL/LGPL code (open-roms, sd2iec): a PR upstream must be acceptable. Adoptable: original work; MIT-licensed code, literal or derived (owner, 2026-11-18: e.g. Microsoft's BASIC-M6502, PLASMA), keeping its copyright notice and linking the source; and demoscene code under community norms (stated intent or evident reuse; credit the author in the source and give greetings). Apache-2.0 is the outer limit: avoid it unless backed into a corner, and do not ask authors to re-license for us. Record the source, the author and the evidence in the file header and in `docs/design/fast-io.md`. Proprietary ROMs are never copied; clean-room from public descriptions and bus traces.
- Never buy the next milestone's problems.

## Status

M0 (taking over the KERNAL) is done under VICE (stock and JiffyDOS ROMs) and runs on the real Ultimate: own interrupt entry, keyboard, screen, serial bus and channels; the KERNAL ROM is not used. Since then (2026-10/11): the **REU block cache** for the boot drive (`cache` command, `make CACHE=0|1|2`, keyed by a build id the first write of each boot changes, plus the disk label); a **footprint pass** (boot-only `INIT` code released to the pool, cold code above the BSS in `CODEHI`, the syscall entry in the `$CF00` page, a split user library); **kernel modules** (a CX image loaded top-down in the pool, `mod` command, root-only syscall ops) with the **CBM DOS filesystem** (`/lib/km/cbm`) and **UCI v1** for the Ultimate's file API (`/lib/km/uci`, `mount uci /u`) as modules; **`exec`** (`SP_EXEC`; `login` execs into `sh`); `turbo`. The user pool is **155 pages (`$0800-$A2FF`, 39,680 bytes)**, above a stock C64's 38,911 BASIC bytes; `KSTART` (`k.inc`) and `KRAM` (`kernel.cfg`) move together, a page at a time. Room below `$CF00` and above the BSS and `CODEHI` is tiny (a link-time assert guards the latter): the current figures per commit are in `docs/size-ledger.tsv` (`tools/size_ledger.py`); see also `docs/wip.md`.

Physical 1541: the root-mount stall is **closed** (owner, 2026-11-18). The cause was the test harness: every REST memory read halts the 6510 (a DMA), a sender cannot know the machine paused, and a halt inside an IEC byte overruns into a hang. It never shows on VICE or the Ultimate's emulated drives because nothing there is halted mid-transfer. The bounded waits and retries stay as defence (the IO release, 9d1b949: session 5, 0 failures in 300 write-verify, 300 read-back and 50 reboot cycles on a physical JiffyDOS 1541). Treat a new IO failure as new evidence against a passed gate, and check the harness's DMA gate first (`docs/design/io-attack-log.md`, closing entry). The JiffyDOS-drive series and the JiffyDOS-ROM test subset on the final tip are the open milestone gates.

## Hardware and external references

- The Ultimate 64 runs Breadbox (see `docs/hardware-notes.md`). A REST client (`tools/ultimate.py`), a fake server for tests (`tools/fake_ultimate.py`) and a test backend with the same interface as `tools/vicetest.py` (`tools/ultimatetest.py`) exist; hardware runs go through the `ultimate` lock. Run tests on the real machine with `BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=host[:port]` (tests built with `make_target`: the `Boot` class, the keyboard and the console tests). Docs: <https://github.com/GideonZ/1541u-documentation> (`uci/`, `api/api_calls.rst`).
- A real 1541 is available for validating the IEC driver. A 1581 is too, but see "non-1541 devices" above.
- `mist64/fastboot1541` (credit Michael Steil if adapted) is the basis for the fast boot and fast read story M0-8.
- The hardware is a C64 Ultimate (firmware 1.1.0, 2 MB REU, UCI enabled) with a JiffyDOS KERNAL and JiffyDOS ROMs in every drive on the bus; it has no REST key injection. See `docs/hardware-notes.md` for what has been verified.

## Working conventions

- Develop on the branch you were given; commit with the test status in the message; open a pull request only when asked.
- Each session works in its own git worktree. Local `main` is the shared truth and is checked out in the primary clone, where nobody else works; origin is a stale mirror, so start from `main`, not `origin/main`. Landing on main is a merge in the primary under a lock (`docs/process.md`).
- Commits are signed. If signing fails (no cached passphrase), stop and ask the human; never disable signing.
- Keep ROMs and anything derived from them out of the repo (`keytab.inc` is the standard keyboard layout; `tools/check_keytab.py` compares it with a ROM).

<!-- caveman-blocks:start -->
@.blocks/INDEX.md
<!-- caveman-blocks:end -->
