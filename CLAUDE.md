# Breadbin

A Unix-like OS for the Commodore 64 (6502 assembly, ca65), forked to be developed further. Read `docs/roadmap.md` first: it holds the direction, the decisions below in full, and the story list. `docs/wip.md` says where things stand right now and who is doing what; `docs/hardware-notes.md` is where findings from the real Ultimate and 1541 are recorded. `README.md` describes the system; `docs/testing.md` says which tests to run.

## Build and test

```sh
make                  # build/breadbin.d64 (needs cc65; about 2 seconds)
make test-host        # image tools, key tables, Ultimate client; no emulator, about 12 seconds
make size             # bytes per kernel module and the headroom; quote it in commits
xvfb-run -a make test-smoke       # boot, echo, pipe, Ctrl-C: about 2 minutes
xvfb-run -a make test-only T="tests.test_system.Boot.test_24_editor"
xvfb-run -a -s "-screen 0 1280x1024x24" make test-keyboard   # real keystrokes (xdotool)
xvfb-run -a -s "-screen 0 1280x1024x24" make test-console
```

The VICE tests need C64 and 1541 ROMs, which are not in the repo: run `tools/setup-vice-roms.sh` once. Run targeted tests per change and the full suite (`make test`, about 32 minutes) at milestones. Do not run other VICE instances at the same time as the tests; they are timing-sensitive.

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

M0 (taking over the KERNAL): M0-1 shadow KERNAL and own vectors, M0-2 keyboard (`kbd.s`), M0-3 screen (`con.s`) and M0-4 (own IEC bus and channels in `iec.s`, root from the boot drive) are done under VICE (stock ROMs and JiffyDOS 6.01 ROMs); M0-4 runs on the real Ultimate (boot 75.5 s against 46.5 s for the ROM-bus stage 1, since JiffyDOS fast load is no longer used; physical 1541 and the full test list still to report; see `docs/hardware-notes.md`). M0-5 is unblocked: the KERNAL ROM region is provably unused. M0-5 is done: the kernel's BSS now lives at `$E000–$F771` (the KERNAL ROM region is unused), so there are **6,079 bytes of room for code** below `$CF00` and 2,184 for BSS below `$FFFA` (`make size`). The user pool is still `$0800–$7FFF`; moving its upper edge is one constant (`KSTART` in `k.inc` and `KRAM` in `kernel.cfg`) and is decided last.

## Hardware and external references

- An Ultimate 64 is being set up. A REST client (`tools/ultimate.py`), a fake server for tests (`tools/fake_ultimate.py`) and a test backend with the same interface as `tools/vicetest.py` (`tools/ultimatetest.py`) exist but have never run on hardware. Run tests on the real machine with `BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=host[:port]` (tests built with `make_target`: the `Boot` class, the keyboard and the console tests). Docs: <https://github.com/GideonZ/1541u-documentation> (`uci/`, `api/api_calls.rst`).
- A real 1541 is available for validating the IEC driver. A 1581 is too, but see "non-1541 devices" above.
- `mist64/fastboot1541` (credit Michael Steil if adapted) is the basis for the fast boot and fast read story M0-8.
- The hardware is a C64 Ultimate (firmware 1.1.0, 2 MB REU, UCI enabled) with a JiffyDOS KERNAL and JiffyDOS ROMs in every drive on the bus; it has no REST key injection. See `docs/hardware-notes.md` for what has been verified.

## Working conventions

- Develop on the branch you were given; commit with the test status in the message; open a pull request only when asked.
- Keep ROMs and anything derived from them out of the repo (`keytab.inc` is the standard keyboard layout; `tools/check_keytab.py` compares it with a ROM).
