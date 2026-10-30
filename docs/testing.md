# Testing

Three levels, cheapest first. Run the cheapest one that covers your change, and the full suite at milestones.

| Level | Command | Time (measured in a cloud container) |
|---|---|---|
| Host tests | `make test-host` | under a second; no emulator |
| Smoke | `make test-smoke` | about 2 to 3 minutes: boot, echo, a three-stage pipe, Ctrl-C |
| Targeted | `make test-only T="<tests>"` | one boot (about 25 s) plus about 10 to 30 s per test |
| Keyboard | `xvfb-run -a -s "-screen 0 1280x1024x24" make test-keyboard` | about 1.5 minutes: real keystrokes through VICE's keyboard matrix |
| Full | `make test` | about 32 minutes for 31 tests |

The keyboard tests inject real X key events with `xdotool` (`apt install xdotool xvfb`). The other system tests type into VICE's key buffer with `keybuf`, which bypasses the matrix scan, so they cannot catch a bug in it. The system tests drive VICE (`x64sc`) through its monitor, so they need the C64 ROMs (`tools/setup-vice-roms.sh`) and, on a machine without a display, a virtual one: `xvfb-run -a make test-smoke`.

## Which tests for which change

By test name; refine this as we learn what actually catches what.

| You changed | Run |
|---|---|
| IRQ, scheduler, process table, vectors (`proc.s`, `main.s`) | `test_00`, `test_08`, `test_13`, `test_14`, `test_15`, `test_21` |
| Console, screen (`con.s`) | `test_20`, `test_22`, `test_24`, `test_25`, `test_13` |
| Keyboard (`kbd.s`) | `make test-keyboard` (matrix scan, decode, modifiers, rollover, repeat, RUN/STOP, jiffy clock), plus `test_13`, `test_24`, `test_25` |
| File layer, pipes, signals (`file.s`) | `test_05`, `test_06`, `test_11`, `test_12`, `test_13` |
| c64fs (`fs.s`) | `test_06`, `test_07`, `test_10`, `test_16`, `Persistence` |
| Block layer, IEC, CBM DOS, `format`, mounts (`blk.s`, `cbm.s`) | `Drives`, `Persistence`, `REU`, plus a boot |
| REU, `/tmp` | `REU` |
| Loader, `as`, `basic` (`exec.s`, `as.s`, `basic.s`) | `test_17`, `test_18`, `test_19` |
| A single command in `src/bin/` | the test that uses it (`grep -n <name> tests/test_system.py`) |
| Image tools, key tables (`tools/`) | `make test-host` |
| Anything that adds or removes kernel code | `make size`, and quote the numbers in the commit message |

Examples:

```sh
xvfb-run -a make test-smoke
xvfb-run -a make test-only T="tests.test_system.Boot.test_24_editor tests.test_system.Boot.test_25_login_password"
xvfb-run -a make test-only T="tests.test_system.REU"
```

## Full suite at milestones

Run the full suite when a milestone story lands (the M0 stories, a filesystem or block-layer change, anything touching the IRQ path), and record the result in the commit message. Between milestones, smoke plus the targeted tests above are enough.

CI runs the build and host tests on every push. It does not run the VICE tests, because they need ROMs that are not in the repo.
