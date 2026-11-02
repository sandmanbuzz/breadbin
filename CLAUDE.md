# Breadbin

A Unix-like OS for the Commodore 64 (6502 assembly, ca65), forked to be developed further. Read `docs/process.md` (how sessions work together: branches, the machine lock, kickoff) and `docs/roadmap.md` first: it holds the direction, the decisions below in full, and the story list. `docs/wip.md` says where things stand right now and who is doing what; `docs/hardware-notes.md` is where findings from the real Ultimate and 1541 are recorded. `README.md` describes the system; `docs/testing.md` says which tests to run.

## Build and test

```sh
make                  # build/breadbin.d64 (needs cc65; about 2 seconds)
make test-host        # image tools, key tables, Ultimate client; no emulator, about 12 seconds
make size             # bytes per kernel module and the headroom; quote it in commits
xvfb-run -a make test-smoke       # boot, echo, pipe, Ctrl-C: about 2 minutes
xvfb-run -a make test-only T="tests.test_system.Boot.test_24_editor"
xvfb-run -a -s "-screen 0 1280x1024x24" make test-keyboard   # real keystrokes (xdotool)
xvfb-run -a -s "-screen 0 1280x1024x24" make test-console
tools/ci/run.sh test            # the whole suite in a container (podman; works on a Mac; ~45 minutes)
tools/ci/run.sh test-keyboard   # or test-smoke, test-console, test-only T="..."; docs/ci.md
```

The VICE tests need C64 and 1541 ROMs, which are not in the repo: run `tools/setup-vice-roms.sh` once. Run targeted tests per change and the full suite (`make test`, about 32 minutes) at milestones. Do not run other VICE instances at the same time as the tests; they are timing-sensitive. Wrap VICE and hardware runs in `tools/with-lock` (see `docs/process.md`).

## Test policy

Targeted tests inside a story, the full regression at milestones. Tests are slow (the full suite is about 40 minutes under VICE, and hardware runs are slower), and a long-lived context is cheaper than a restarted one, so:

- **During a story:** `make test-host`, the targeted tests for what you changed (the table in `docs/testing.md`), and `make test-smoke` before committing. No full suite.
- **At a milestone** (the end of an M group, or any change to the interrupt path, the bus, the memory map or the linker layout): the full suite with stock ROMs, the disk and bus tests again with the JiffyDOS ROMs (`BREADBIN_VICE_ARGS`, see `docs/testing.md`), and a hardware run of the list in `docs/hardware-notes.md`.
- **Hardware** is used for what only hardware can answer, not as a per-story gate. Keep one hardware session alive with its context and give it experiments (`docs/wip.md`), not just test runs.
- Say in every commit message what was run and what was not.

## Decisions (details in `docs/roadmap.md`)

- **Platform tiers:** Classic (stock C64, 1541, no REU) must keep booting; Expanded adds an REU; Recommended is an Ultimate with UCI. The core never requires an REU or an Ultimate. Features are chosen by probing at run time.
- **c64fs v1 compatibility is dropped.** Non-1541 devices (1581 and others) are nice-to-have, not milestone work: leave a clean campsite, do not design around them.
- **Zero page stays stock-shaped.** A stock address keeps its stock meaning wherever we still provide the service; poach only what we have retired, and document it. Do not turn zero page into foreign territory.
- **Kernel space is scarce.** Measure with `make size`; a deliberate space pass (M0-7) comes after all KERNAL replacements.
- **Contract drift:** internal behavior may improve if the call looks the same and does not violate least surprise. The user-facing contract matters more than the vintage one.
- **Licence policy:** the repo is MIT and our own code is informal/public domain. Do not bring in GPL/LGPL code (open-roms, sd2iec): a PR upstream must be acceptable. Adoptable: original work, and demoscene code under community norms (stated intent or evident reuse; credit the author in the source and give greetings). Record the source, the author and the evidence in the file header and in `docs/design/fast-io.md`. Proprietary ROMs are never copied; clean-room from public descriptions and bus traces.
- Never buy the next milestone's problems.

## Status

M0 (taking over the KERNAL) is done under VICE (stock and JiffyDOS ROMs) and runs on the real Ultimate: own interrupt entry, keyboard, screen, serial bus and channels; the KERNAL ROM is not used. Since then (2026-10/11): the **REU block cache** for the boot drive (`cache` command, `make CACHE=0|1|2`, keyed by a build id the first write of each boot changes, plus the disk label); a **footprint pass** (boot-only `INIT` code released to the pool, cold code above the BSS in `CODEHI`, the syscall entry in the `$CF00` page, a split user library); **kernel modules** (a CX image loaded top-down in the pool, `mod` command, root-only syscall ops) with the **CBM DOS filesystem** (`/lib/km/cbm`) and **UCI v1** for the Ultimate's file API (`/lib/km/uci`, `mount uci /u`) as modules; **`exec`** (`SP_EXEC`; `login` execs into `sh`); `turbo`. The user pool is **154 pages (`$0800-$A1FF`, 39,424 bytes)**, above a stock C64's 38,911 BASIC bytes; `KSTART` (`k.inc`) and `KRAM` (`kernel.cfg`) move together, a page at a time. Room: 354 bytes below `$CF00`, only **14 bytes above the BSS and `CODEHI`** (a link-time assert guards it; see `docs/wip.md`).

Physical 1541: the root-mount stall that predates all of this is **mitigated, not root-caused**: a bounded wait in `bus_acptr` and three retries with UNTALK in `iec_read` took it from about 1 boot in 4 to 13 of 13 (`docs/hardware-notes.md`). The JiffyDOS-drive series and the JiffyDOS-ROM test subset on the final tip are the open milestone gates.

## Hardware and external references

- An Ultimate 64 is being set up. A REST client (`tools/ultimate.py`), a fake server for tests (`tools/fake_ultimate.py`) and a test backend with the same interface as `tools/vicetest.py` (`tools/ultimatetest.py`) exist but have never run on hardware. Run tests on the real machine with `BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=host[:port]` (tests built with `make_target`: the `Boot` class, the keyboard and the console tests). Docs: <https://github.com/GideonZ/1541u-documentation> (`uci/`, `api/api_calls.rst`).
- A real 1541 is available for validating the IEC driver. A 1581 is too, but see "non-1541 devices" above.
- `mist64/fastboot1541` (credit Michael Steil if adapted) is the basis for the fast boot and fast read story M0-8.
- The hardware is a C64 Ultimate (firmware 1.1.0, 2 MB REU, UCI enabled) with a JiffyDOS KERNAL and JiffyDOS ROMs in every drive on the bus; it has no REST key injection. See `docs/hardware-notes.md` for what has been verified.

## Working conventions

- Develop on the branch you were given; commit with the test status in the message; open a pull request only when asked.
- Keep ROMs and anything derived from them out of the repo (`keytab.inc` is the standard keyboard layout; `tools/check_keytab.py` compares it with a ROM).
