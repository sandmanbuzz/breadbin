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

## Decisions (details in `docs/roadmap.md`)

- **Platform tiers:** Classic (stock C64, 1541, no REU) must keep booting; Expanded adds an REU; Recommended is an Ultimate with UCI. The core never requires an REU or an Ultimate. Features are chosen by probing at run time.
- **c64fs v1 compatibility is dropped.** Non-1541 devices (1581 and others) are nice-to-have, not milestone work: leave a clean campsite, do not design around them.
- **Zero page stays stock-shaped.** A stock address keeps its stock meaning wherever we still provide the service; poach only what we have retired, and document it. Do not turn zero page into foreign territory.
- **Kernel space is scarce.** Measure with `make size`; a deliberate space pass (M0-7) comes after all KERNAL replacements.
- **Contract drift:** internal behavior may improve if the call looks the same and does not violate least surprise. The user-facing contract matters more than the vintage one.
- Never buy the next milestone's problems.

## Status

M0 (taking over the KERNAL): M0-1 shadow KERNAL and own vectors, M0-2 keyboard (`kbd.s`), M0-3 screen (`con.s`) and M0-4 (own IEC bus and channels in `iec.s`, root from the boot drive) are done under VICE; M0-4 has not yet run on real drives (see `docs/hardware-notes.md`). **Kernel headroom is 5 bytes** below the syscall table at `$CF00`: the second code region at `$E000–$E3FF` or the space pass (M0-7) must come before any more kernel code. The full suite was last run after M0-1.

## Hardware and external references

- An Ultimate 64 is being set up. A REST client (`tools/ultimate.py`), a fake server for tests (`tools/fake_ultimate.py`) and a test backend with the same interface as `tools/vicetest.py` (`tools/ultimatetest.py`) exist but have never run on hardware. Run tests on the real machine with `BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=host[:port]` (tests built with `make_target`: the `Boot` class, the keyboard and the console tests). Docs: <https://github.com/GideonZ/1541u-documentation> (`uci/`, `api/api_calls.rst`).
- A real 1541 is available for validating the IEC driver. A 1581 is too, but see "non-1541 devices" above.
- `mist64/fastboot1541` (credit Michael Steil if adapted) is the basis for the fast boot and fast read story M0-8.
- The hardware is a C64 Ultimate (firmware 1.1.0, 2 MB REU, UCI enabled) with a JiffyDOS KERNAL and JiffyDOS ROMs in every drive on the bus; it has no REST key injection. See `docs/hardware-notes.md` for what has been verified.

## Working conventions

- Develop on the branch you were given; commit with the test status in the message; open a pull request only when asked.
- Keep ROMs and anything derived from them out of the repo (`keytab.inc` is the standard keyboard layout; `tools/check_keytab.py` compares it with a ROM).
