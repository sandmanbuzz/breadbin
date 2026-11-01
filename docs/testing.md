# Testing

Three levels, cheapest first. Run the cheapest one that covers your change, and the full suite at milestones. The policy is in `CLAUDE.md`: targeted tests inside a story, the full regression (stock ROMs, then the disk and bus tests with JiffyDOS ROMs, then the hardware list) at milestones.

| Level | Command | Time (measured in a cloud container) |
|---|---|---|
| Host tests | `make test-host` | about 12 seconds; no emulator (includes the Ultimate client against a fake server) |
| Smoke | `make test-smoke` | about 2 to 3 minutes: boot, echo, a three-stage pipe, Ctrl-C |
| Targeted | `make test-only T="<tests>"` | one boot (about 25 s) plus about 10 to 30 s per test |
| Console | `xvfb-run -a make test-console` | about 3 minutes: screen RAM, colour RAM and VIC registers read back |
| Keyboard | `xvfb-run -a -s "-screen 0 1280x1024x24" make test-keyboard` | about 1.5 minutes: real keystrokes through VICE's keyboard matrix |
| Full | `make test` | about 32 minutes for 31 tests |

The keyboard tests inject real X key events with `xdotool` (`apt install xdotool xvfb`). The other system tests type into VICE's key buffer with `keybuf`, which bypasses the matrix scan, so they cannot catch a bug in it. The system tests drive VICE (`x64sc`) through its monitor, so they need the C64 ROMs (`tools/setup-vice-roms.sh`) and, on a machine without a display, a virtual one: `xvfb-run -a make test-smoke`.

## On a real Ultimate

The `Boot` class, `test_keyboard` and `test_console` pick their backend with `make_target`: the VICE emulator by default, a real Ultimate with `BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=host[:port]` (and `BREADBIN_ULTIMATE_PASSWORD` if set). The backend mounts `build/breadbin.d64` in drive A, resets, loads and runs it. `type()` and `keybuf()` write the key buffer by DMA, as VICE's `keybuf` does; `xkey` and friends use real key events (Ultimate 64 only). Tests that need the emulator (`-reu`, extra drives, reboot persistence) stay on VICE. `make test-host` includes the client's 24 tests against a fake server. See `docs/hardware-notes.md` for what has and has not been verified.

## With other ROMs (JiffyDOS)

`BREADBIN_VICE_ARGS` adds emulator options to every VICE the harness starts, so ROM images that must not be in the repository can still be used:

```sh
BREADBIN_VICE_ARGS="-kernal /path/JiffyDOS_6.01-Kernal.bin \
  -dos1541 /path/JiffyDOS_6.01-1541.bin -dos1541II /path/JiffyDOS_6.01-1541.bin" \
  xvfb-run -a make test-only T="tests.test_system.Boot.test_02_echo"
```

This is how the bus driver was checked against the drives the Ultimate has. Stock ROMs hide timing assumptions; run bus changes under both.

## VICE on macOS (the bundled app, from a sandboxed session)

The VICE 3.10 app bundle ships the C64 and drive ROMs, so `tools/setup-vice-roms.sh` is not needed. Two things get in the way when VICE is started from a sandboxed shell, and neither needs a code change:

- Use the real binary inside the bundle, `VICE.app/Contents/Resources/bin/x64sc`; the `bin/x64sc` launcher script loses `argv[0]` and exits.
- VICE cannot write to the home directory there and cannot find its own install: give it a scratch `HOME` with `config/vice`, `state/vice` and `data` already created, and `-directory` pointing at the bundle's `share/vice`.

```sh
R=/Applications/vice-arm64-gtk3-3.10/VICE.app/Contents/Resources
S=/path/to/scratch
mkdir -p $S/vicehome/config/vice $S/vicehome/state/vice $S/vicehome/data
export HOME=$S/vicehome XDG_STATE_HOME=$S/vicehome/state XDG_CONFIG_HOME=$S/vicehome/config \
       XDG_DATA_HOME=$S/vicehome/data TMPDIR=$S
export X64SC=$R/bin/x64sc BREADBIN_VICE_ARGS="-directory $R/share/vice -logfile $S/vice.log"
python3 -m unittest tests.test_system.Boot.test_02_echo
```

This runs the monitor-driven tests (`Boot`, `test_console`) with no X server. `test_keyboard` needs `xdotool` and an X display, which macOS does not have. A VICE window appears on the desktop while a test runs. On 2026-10-31 this ran `test_07`, `test_10`, `test_13`, `test_14`, `test_24` and `test_console` (11 tests, about 7.5 minutes) green on the stage-2 kernel.

## Windowless VICE on macOS

`-console` (VICE's console mode) starts without a window, so a test run no longer steals focus,
and it used about a third less CPU. The monitor-driven tests pass with it:

```sh
BREADBIN_VICE_ARGS="$BREADBIN_VICE_ARGS -console" python3 -m unittest tests.test_system.Cache
```

## Which tests for which change

By test name; refine this as we learn what actually catches what.

| You changed | Run |
|---|---|
| IRQ, scheduler, process table, vectors (`proc.s`, `main.s`) | `test_00`, `test_08`, `test_13`, `test_14`, `test_15`, `test_21` |
| Console, screen (`con.s`) | `make test-console` (wrapping, backspace, clear, scrolling, reverse video, cursor addressing, theme colours), plus `test_20`, `test_22`, `test_24`, `test_25` |
| Keyboard (`kbd.s`) | `make test-keyboard` (matrix scan, decode, modifiers, rollover, repeat, RUN/STOP, jiffy clock), plus `test_13`, `test_24`, `test_25` |
| File layer, pipes, signals (`file.s`) | `test_05`, `test_06`, `test_11`, `test_12`, `test_13` |
| c64fs (`fs.s`) | `test_06`, `test_07`, `test_10`, `test_16`, `Persistence` |
| Block layer, IEC, CBM DOS, `format`, mounts (`blk.s`, `cbm.s`) | `Drives`, `Persistence`, `REU`, `Cache`, plus a boot |
| REU, `/tmp`, the REU block cache | `REU`, `Cache` (about 11 minutes: it boots VICE about 20 times, with a 2 MB REU image kept across boots) |
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
