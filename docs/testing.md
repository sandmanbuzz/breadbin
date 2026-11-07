# Testing

Three levels, cheapest first. Run the cheapest one that covers your change, and the full suite at milestones. The policy is in `CLAUDE.md`: targeted tests inside a story, the full regression (stock ROMs, then the disk and bus tests with JiffyDOS ROMs, then the hardware list) at milestones.

| Level | Command | Time (on the runner, in the container) |
|---|---|---|
| Fast gate (host tests) | `tools/ci/run.sh all test-host`, or `make test-host` with cc65 and py65 on the host | about 45 s after `make` (`make test-host` alone skips the tests that need build/): 484 tests, none skipped (image tools, key tables, the Ultimate client against a fake server, the py65 simulators of the real kernel, `as` on the host (`tools/asim.py`), the host compiler `tools/cc.py`, and the shard-list check) |
| Shard list | `bash tools/ci/sharded.sh --check` | seconds, host only: every VICE test is in exactly one shard (105 tests now) |
| Smoke | `tools/ci/run.sh test-smoke` | about 2 to 3 minutes: boot, echo, a three-stage pipe, Ctrl-C |
| Targeted | `tools/ci/run.sh test-only T="<tests>"` | one boot (about 25 s) plus about 10 to 30 s per test |
| Console | `tools/ci/run.sh test-console` | about 2.5 minutes (6 tests, 143 s in the last shard run): screen RAM, colour RAM and VIC registers read back |
| Keyboard | `tools/ci/run.sh test-keyboard` | about 4 minutes (7 tests, 232 s): real keystrokes through VICE's keyboard matrix |
| Full suite, sharded | `tools/ci/sharded.sh` | six containers at once under one `with-lock -x`, about 10 to 13 minutes: 74 tests took 605 s on `27fa473` and 628 s on `bb09283` (stock ROMs); the 80-test layout on `3fd8112` took 778 s (80 of 80, shards 601 to 768 s: the shard list is unbalanced again and the runs now take longer per test than before, so a rebalance by cost is due). Fails on any non-zero shard, any skip, or a total that differs from the discovered count |
| Full suite, JiffyDOS ROMs | `BREADBIN_CI_JIFFY=<dir> tools/ci/sharded.sh` | the same run: 74 of 74 in 562 s on `2048e78`. `BREADBIN_VICE_PRINT_ARGS=1` prints the emulator command line, so `-kernal JiffyDOS-C64.bin -dos1541 JiffyDOS_1541-II.bin` can be seen |
| Full suite, serial (the reference) | `BREADBIN_CI_EXCLUSIVE=1 tools/ci/run.sh test` | Measured when the suite was 63 VICE tests (now 105, not re-timed serially): 2,804 s on the runner, every slot taken (about 47 minutes). The older 55-test figure, 2,511 s on 4778b1a (the Mac), is not comparable |

The commands in the first column are the container ones: the container is the only toolchain (`docs/process.md`). The host recipes further down (`xvfb-run make ...`) are history from the Mac. Run a timing you will quote with every slot (`BREADBIN_CI_EXCLUSIVE=1`, or `tools/with-lock -x` around the sharded driver, which takes them itself).

The keyboard tests inject real X key events with `xdotool` (`apt install xdotool xvfb`). The other system tests type into VICE's key buffer with `keybuf`, which bypasses the matrix scan, so they cannot catch a bug in it. The system tests drive VICE (`x64sc`) through its monitor, so they need the C64 ROMs (`tools/setup-vice-roms.sh`) and, on a machine without a display, a virtual one: `xvfb-run -a make test-smoke`.

## On a real Ultimate

The `Boot` class, `test_keyboard` and `test_console` pick their backend with `make_target`: the VICE emulator by default, a real Ultimate with `BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=host[:port]` (and `BREADBIN_ULTIMATE_PASSWORD` if set). The backend mounts `build/breadbin.d64` in drive A, resets, loads and runs it. `type()` and `keybuf()` write the key buffer by DMA, as VICE's `keybuf` does; `xkey` and friends use real key events (Ultimate 64 only). Tests that need the emulator (`-reu`, extra drives, reboot persistence) stay on VICE. `make test-host` includes the client's 24 tests against a fake server. See `docs/hardware-notes.md` for what has and has not been verified.

## The UCI simulator (py65)

`tools/test_uci_sim.py` tests UCI v1 (the module `src/mod/uci.s` and its resident stubs in `src/kernel/uci.s`, `docs/design/next/uci-v1.md`) without an Ultimate: it loads the **real kernel image** (`build/breadbin.prg`) into [py65](https://github.com/mnaberez/py65) (a 6502 emulator in Python, BSD licence), runs the boot stub and `kmain` up to the point where `/bin/init` would start, then calls syscalls through the jump table at `$CF00` as one process. `tools/uci_sim.py` has the harness and `FakeUCI`, a model of the Command Interface registers at `$DF1B-$DF1F` built from the measurements in `docs/hardware-notes.md` ("UCI as measured", on `hw-bench`) and the firmware's DOS target (`software/filemanager/dos.cc` in 1541ultimate), on a temporary host directory.

py65 is a test dependency only, not vendored. Install it into a virtualenv of your own (not globally), then run `make test-host` or the file alone with that interpreter. Without py65, or before `make`, the 35 tests skip and `make test-host` stays green. The CI image (`tools/ci/Containerfile`) has it pinned in `/opt/venv` (on `PATH`), so `tools/ci/run.sh all test-host` runs them: on the runner, 127 run, OK, 1 skipped (the skip is not py65; its reason is not yet identified). A gate run of `tools/ci/run.sh test` on an image built before the py65 line showed 35 skipped; rebuild the image to pick it up (`test-host` alone does not build the kernel image, and those tests skip without it).

```sh
python3 -m venv /path/to/venv && /path/to/venv/bin/pip install py65
make && /path/to/venv/bin/python -m unittest tools.test_uci_sim -v
```

`tools/test_exec_sim.py` uses the same harness for `exec` (`SPAWN` with `SP_EXEC`, `docs/design/next/exec.md` section 6): a missing file (`ENOENT`), a text file (`ENOEXEC`) and a full pool (`ENOMEM`) must leave the caller's page table, free count, name, fds and user zero page identical; a success stops on `jmp (k_entry)` of the new image with `SP = $FD`, the relocated image and `argv` in place, pid, fds and uid unchanged and the old image back in the pool; a signal pending at the end of the load kills the new image and leaks nothing. Run: `/path/to/venv/bin/python -m unittest tools.test_exec_sim -v`. Checked by mutation: a build where `exec_commit` does not free the old image fails two of the five.

Faked, so not covered: the IEC bus (`iec_open`/`iec_read`/`iec_write` are trapped and served from `build/breadbin.d64` in memory), the REU (reported absent), interrupts (none are raised: the scheduler, the keyboard and the clock never run, so a spawned program is loaded and checked byte for byte but not started), and the Ultimate itself (the fake shares the documentation's gaps: timing, FAT case-insensitivity, the exact status of untried error cases). Running the whole system in py65 (init, the shell) would need the CIA timer interrupt, the keyboard matrix and a 1541 on the IEC bus; not attempted. The hardware check list is in the spec, section 7.

Covered: Classic untouched (no access to `$DF1B-$DF1F` at boot or in file operations; `mount uci` with no interface reads `$DF1D` once and says "no such device"; open bus showing `$C9` fails the IDENTIFY), mount and `mount` listing, `ls` (including names over 14 characters), `cat`, `stat`, write and read back, `O_TRUNC`, `O_APPEND`, a 100 KB write, relative paths and the working directory, `..` out of the mount, `unlink`/`mkdir`/`rmdir`/`rename` and their errors, three open files on two host handles (eviction, reopen, seek), `EMFILE`, `umount` (busy, the page given back, remount), running a program from `/u` (absolute and relative, `ENOEXEC`, `ENOENT`), c64fs unchanged while `/u` is mounted, and `uci.km` itself: `mount uci` loads `/lib/km/uci` from the disk image through the kernel's own `mod_load` (nothing is faked for it), umount and a failed mount unload it, the pages come back, a Classic run never loads it, a hash mismatch is `ENOEXEC`, `mod load`/`mod unload` by hand are refused. Every test also checks that the kernel never opened a file on a DOS target that still had one open, and never wrote command bytes while the interface was busy.

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

## In a container (the default way)

`tools/ci/run.sh` runs the tests in a disposable container with its own VICE (3.9), Xvfb and `xdotool`, so parallel runs do not collide (`docs/ci.md`: the image, the slots, the sharded suite). It copies the repo at start, so edit freely while it runs, and it takes one `vice` slot (six at once on the runner; `BREADBIN_CI_EXCLUSIVE=1` takes them all).

```sh
tools/ci/run.sh all test-host                  # the fast gate, about 45 s
tools/ci/sharded.sh                            # the whole VICE suite, six containers, about 10 minutes
BREADBIN_CI_JIFFY=<dir> tools/ci/sharded.sh    # the same with the JiffyDOS ROMs (dir holds JiffyDOS-C64.bin, JiffyDOS_1541-II.bin)
tools/ci/run.sh test-only T="tests.test_system.Exec tests.test_system.Modules"
```

When you add a test, put it in a shard (`tools/ci/shards.txt`, by cost) and run `bash tools/ci/sharded.sh --check` and the fast gate before you land: a test in no shard or in two fails both.

Classes: `tests/test_system.py` has `Boot` (28 tests, split in two halves for the shards), `Persistence`, `REU`, `REURoot` (the REU as root device, no drive: `mkimage.py reu`, `make run-reu-root`), `Cache` (9: warm boot, new disk or label discards, write-through, pristine image after writes), `Pool`, `Modules`, `Exec`, `Drives` (mount and format CBM disks, the module-is-not-a-program case), `Pipes` (tee, tail, sort), `Touch`; `tests/test_console.py`, `tests/test_keyboard.py`, and `tests/test_compiled.py` (`Compiled`: programs written in C, compiled on the host by `tools/cc.py`, assembled and run on the machine).

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
| REU, `/tmp`, the REU block cache, the REU root device | `REU`, `REURoot`, `Cache` (about 11 minutes: it boots VICE about 20 times, with a 2 MB REU image kept across boots) |
| Loader, `as`, `basic` (`exec.s`, `as.s`, `basic.s`) | `test_17`, `test_18`, `test_19`, `test_28` (the deepest legal expression across context switches; the stack cap) |
| Context-switch stack (`proc.s`, `STKSAVE`) or anything that deepens a program's stack | measure: `make STKWATCH=1` (rebuild from clean: `rm -rf build`), then `tools/with-lock -r vice -- xvfb-run -a python3 -m unittest tests.stkwatch` (not in the suite; writes `build/stkwatch.txt`: high-water mark per workload and kills). The limit is `STKSAVE` (128) minus 1; keep the worst case at least 17 bytes under it |
| A single command in `src/bin/` | the test that uses it (`grep -n <name> tests/test_system.py`): `tee`, `tail` and `sort` have `Pipes`, `touch` has `Touch` |
| The assembler (`as.s`) | `tools/test_as.py` (host: `as` runs under py65 via `tools/asim.py`, 0.1 s per program), then `Boot.test_19` and `test_27` |
| The compiler (`tools/cc.py`, through slice 3) | `tools/test_cc.py`, `tools/test_cc_run.py` (host; programs run on a 6502 simulator), then `tests.test_compiled.Compiled` on the machine |
| Image tools, key tables (`tools/`) | `make test-host` |
| UCI v1 (`src/mod/uci.s` = `/lib/km/uci`, the stubs in `src/kernel/uci.s`, the `bmi` sites in `file.s`, `fs.s`, `exec.s`, `cbm.s`) | `make test-host` with py65 (`tools/test_uci_sim.py`), plus `Drives`, `REU`, `Pool`, `Modules` and a smoke run in VICE |
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

## Known issues

- **Known flaky: `tools/test_shards.py` `test_ctrl_c_stops_every_shard` (host test, fixed, watch for recurrence).** It failed once inside `tools/land.sh`, then passed alone (twice) and on retry. The fix `fix/shards-ctrlc-race` landed afterwards (merge `9d4edb7`: the test now polls for the stopped count, since the stub's TERM trap can finish after the driver's wait returns). If it recurs, rerun it alone and report.

- **Keyboard key loss: two classes, neither root-caused (open; owner's call).** (1) Key-buffer boundary loss (keybuf / Ultimate DMA): a keybuf write of 8 bytes lost its last chunk once in 5 VICE trials (the Return), and on the Ultimate the first character of a second 8-byte chunk was dropped once ('cat /nop' | 'e'). The rate is low and the mechanism is unknown. The capacity hypothesis (the 10-key buffer overflowing when a write lands on pending keys) was tested by counting pending keys before each write: the largest count seen was 8, and no loss occurred in 8 trials. That hypothesis is not supported. The count went through the VICE monitor, which pauses the machine, so it is a lower bound. (2) The X-press path in VICE: a key sent by xdotool right after TAB completion was not counted by the matrix scan, and the scan itself was clean (no unstable reads, counts steady). Delivery of xdotool events into VICE is not confirmed, and a real fast TAB-Return on hardware is untested. The hardware drop is reproduced once (Ultimate, Boot test_09_errors); it is not yet reproduced on demand. No kernel change is made for either class. Both classes are injection paths (keybuf and Ultimate DMA writes; xdotool into VICE). No loss from a physical key press on a real keyboard has been shown; if the demo's drops were human typing, they remain unexplained.

- **`test_tab_no_match_does_not_fire` fails in its setUp (VICE test, open; cause not identified).** It fails in the full VICE suite and in targeted runs. Repro: `make test-only T="tests.test_keyboard.Keyboard.test_shifted_symbol tests.test_keyboard.Keyboard.test_tab_completes_a_real_key tests.test_keyboard.Keyboard.test_tab_no_match_does_not_fire"` fails 2 of 2 runs with the screen `/ $ echo clear`. Each test alone passes, and so does each pair tried. The positive control (`test_tab_completes_a_real_key`) is weak: it passes once `echo` is on the screen, so it does not show that Return ran. What the evidence shows: keys sent right after TAB completion, and the first input after a shell line, are not reliably reaching the shell in the harness. In the matrix counter, the Return sent immediately after TAB was not counted as a new press (2 runs), and a probe key sent 1 s after TAB was not counted either. Neither keybuf step (the `clear` line, the Ctrl-C in tearDown) is the cause: sending each through X keys still fails 2 of 2. No fault found in the product key path (matrix scan, debounce, edge logic, and the IEC or disk code deferring the scan) on these counters. Not found: the state that the next setUp inherits. Keys sent through `keybuf` do reach the shell (a Return via `keybuf` after the completion runs the line). Delivery by xdotool into VICE is not confirmed, and a real fast TAB-Return on hardware is untested. Open: (1) find the input state that the harness leaves behind; (2) make the positive control wait for the run, not for the echo to appear; (3) bisect not run. The hardware key drop is reproduced once and stays open; this note covers the VICE harness and the one hardware observation.
