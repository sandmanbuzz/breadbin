# Testing

Three levels, cheapest first. Run the cheapest one that covers your change, and the full suite at milestones. The policy is in `CLAUDE.md`: targeted tests inside a story, the full regression (stock ROMs, then the disk and bus tests with JiffyDOS ROMs, then the hardware list) at milestones.

| Level | Command | Time (on the runner, in the container) |
|---|---|---|
| Fast gate (host tests) | `tools/ci/run.sh all test-host`, or `make test-host` with cc65 and py65 on the host | about 45 s after `make` (`make test-host` alone skips the tests that need build/): none skipped (the run prints the count) (image tools, key tables, the Ultimate client against a fake server, the py65 simulators of the real kernel, `as` on the host (`tools/asim.py`), the host compiler `tools/cc.py`, and the shard-list check) |
| Shard list | `bash tools/ci/sharded.sh --check` | seconds, host only: every VICE test is in exactly one shard |
| Smoke | `tools/ci/run.sh test-smoke` | about 2 to 3 minutes: boot, echo, a three-stage pipe, Ctrl-C |
| Targeted | `tools/ci/run.sh test-only T="<tests>"` | one boot (about 25 s) plus about 10 to 30 s per test |
| Console | `tools/ci/run.sh test-console` | about 2.5 minutes (6 tests, 143 s in the last shard run): screen RAM, colour RAM and VIC registers read back |
| Keyboard | `tools/ci/run.sh test-keyboard` | about 4 minutes (7 tests, 232 s): real keystrokes through VICE's keyboard matrix |
| Full suite, sharded | `tools/ci/sharded.sh` | six containers at once under one `with-lock -x`, about 10 to 25 minutes depending on load (147 tests in 1344 s on `ac46aec`, stock ROMs, the last time it was quoted; the run prints the count and the shard times). Fails on any non-zero shard, any skip, or a total that differs from the discovered count. With `BREADBIN_CI_JIFFY` set the skips whose reason is "this drive speaks JiffyDOS" (the IEC fault tests that need the standard byte protocol, 14 of them) are by design and do not fail it |
| Full suite, JiffyDOS ROMs | `BREADBIN_CI_JIFFY=<dir> tools/ci/sharded.sh` | the same run: 74 of 74 in 562 s on `2048e78`. `BREADBIN_VICE_PRINT_ARGS=1` prints the emulator command line, so `-kernal JiffyDOS-C64.bin -dos1541 JiffyDOS_1541-II.bin` can be seen |
| Full suite, serial (the reference) | `BREADBIN_CI_EXCLUSIVE=1 tools/ci/run.sh --serial-because "<why>" test` (refused without the reason: it holds every slot for about two hours) | Measured when the suite was 63 VICE tests (now 105, not re-timed serially): 2,804 s on the runner, every slot taken (about 47 minutes). The older 55-test figure, 2,511 s on 4778b1a (the Mac), is not comparable |

The commands in the first column are the container ones: the container is the only toolchain (`docs/process.md`). The host recipes further down (`xvfb-run make ...`) are history from the Mac. Run a timing you will quote with every slot (`BREADBIN_CI_EXCLUSIVE=1`, or `tools/with-lock -x` around the sharded driver, which takes them itself).

The keyboard tests inject real X key events with `xdotool` (`apt install xdotool xvfb`). The other system tests type into VICE's key buffer with `keybuf`, which bypasses the matrix scan, so they cannot catch a bug in it. The system tests drive VICE (`x64sc`) through its monitor, so they need the C64 ROMs (`tools/setup-vice-roms.sh`) and, on a machine without a display, a virtual one: `xvfb-run -a make test-smoke`.

## On a real Ultimate

The `Boot` class, `test_keyboard` and `test_console` pick their backend with `make_target`: the VICE emulator by default, a real Ultimate with `BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE=host[:port]` (and `BREADBIN_ULTIMATE_PASSWORD` if set). The backend mounts `build/breadbin.d64` in drive A, resets, loads and runs it. `type()` and `keybuf()` write the key buffer by DMA, but unlike VICE's `keybuf` only into an empty buffer (no `machine:pause`), so keys typed ahead of a program that never reads the keyboard time out after 30 s; `xkey` and friends use real key events (Ultimate 64 only).

Every REST memory access halts the 6510 (a DMA), and a halt inside a serial transfer can corrupt or stall it (`docs/design/io-attack-log.md`). So the backend makes no request at all while the machine's own `load` runs (it waits `BREADBIN_ULTIMATE_LOAD_QUIET` seconds, default 20, then checks once and reads the loaded file back), and afterwards reads the screen and writes keys only when three 1-byte samples of `$DD00` say the bus is idle. That gate cannot see a transfer that starts just after its last sample. A gated screen read whose idle verdict came within 1 s of a busy sample and whose next verdict, within 1 s of it, is busy again is reported on stderr as a `gate race` line; a key write in the same spot as a `gate key-write candidate` (the busy verdict may be the command it typed); a failed request counts too when the caller polls on; and timeout messages carry the recent gate events and those around the last races; but some races are not seen (a transfer starting after a long quiet stretch, one that starts and ends between two verdicts, a DMA that ends a transfer at once), and the 1-byte `$DD00` probes go on through Breadbin's own transfers, so a clean output does not prove the harness disturbed nothing (the list is in `tools/ultimatetest.py`). `BREADBIN_ULTIMATE_GATELOG=1` logs every sample and access. `BREADBIN_ULTIMATE_BUS` names the bus of drive A (default 8; 9 when a physical drive is on 8). Tests that need the emulator (`-reu`, extra drives, reboot persistence) stay on VICE. `make test-host` includes the client's and the backend's tests against a fake server (alone: `cd tools && python3 -m unittest test_ultimate`). See `docs/hardware-notes.md` for what has and has not been verified.

## The UCI simulator (py65)

`tools/test_uci_sim.py` tests UCI v1 (the module `src/mod/uci.s` and its resident stubs in `src/kernel/uci.s`, `docs/design/next/uci-v1.md`) without an Ultimate: it loads the **real kernel image** (`build/breadbin.prg`) into [py65](https://github.com/mnaberez/py65) (a 6502 emulator in Python, BSD licence), runs the boot stub and `kmain` up to the point where `/bin/init` would start, then calls syscalls through the jump table at `$CF00` as one process. `tools/uci_sim.py` has the harness and `FakeUCI`, a model of the Command Interface registers at `$DF1B-$DF1F` built from the measurements in `docs/hardware-notes.md` ("UCI as measured", on `hw-bench`) and the firmware's DOS target (`software/filemanager/dos.cc` in 1541ultimate), on a temporary host directory.

py65 is a test dependency only, not vendored. Install it into a virtualenv of your own (not globally), then run `make test-host` or the file alone with that interpreter. Without py65, or before `make`, the 35 tests skip and `make test-host` stays green. The CI image (`tools/ci/Containerfile`) has it pinned in `/opt/venv` (on `PATH`), so `tools/ci/run.sh all test-host` runs them: on the runner, 127 run, OK, 1 skipped (the skip is not py65; its reason is not yet identified). A gate run of `tools/ci/run.sh test` on an image built before the py65 line showed 35 skipped; rebuild the image to pick it up (`test-host` alone does not build the kernel image, and those tests skip without it).

```sh
python3 -m venv /path/to/venv && /path/to/venv/bin/pip install py65
make && /path/to/venv/bin/python -m unittest tools.test_uci_sim -v
```

`tools/test_exec_sim.py` uses the same harness for `exec` (`SPAWN` with `SP_EXEC`, `docs/design/next/exec.md` section 6): a missing file (`ENOENT`), a text file (`ENOEXEC`) and a full pool (`ENOMEM`) must leave the caller's page table, free count, name, fds and user zero page identical; a success stops on `jmp (k_entry)` of the new image with `SP = $FD`, the relocated image and `argv` in place, pid, fds and uid unchanged and the old image back in the pool; a signal pending at the end of the load kills the new image and leaks nothing. Run: `/path/to/venv/bin/python -m unittest tools.test_exec_sim -v`. Checked by mutation: a build where `exec_commit` does not free the old image fails two of the five.

`tools/test_psave_sim.py` guards p_save (the save areas under the I/O registers, `proc.s`): the real `sched` and `setup_proc` run in py65 with a memory guard that fails on an access to `$D000-$DFFF` outside p_save while `$01` shows RAM, on any p_save access while I/O shows, on I clear while RAM shows, and on `$01` not `$35` or the caller's I flag not restored at return. Mutation tests (a nopped `inc $01`, `dec $01` or `sei`) must trip it. It does not model the real banking or raise interrupts. Run: `python3 -m unittest tools.test_psave_sim -v`.

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

Classes: `tests/test_system.py` has `Boot` (28 tests, split in two halves for the shards), `Persistence`, `REU`, `REURoot` (the REU as root device, no drive: `mkimage.py reu`, `make run-reu-root`), `Cache` (9: warm boot, new disk or label discards, write-through, pristine image after writes), `Pool`, `Modules`, `Exec`, `Drives` (mount and format CBM disks, the module-is-not-a-program case), `Pipes` (tee, tail, sort), `Touch`; `tests/test_console.py`, `tests/test_keyboard.py`, and `tests/test_compiled.py` (`Compiled`: programs written in C, compiled on the host by `tools/cc.py`, assembled and run on the machine), and `tests/test_pvm_machine.py` (`PCode`: bytecode programs linked against the p-code VM's shared library on the host and run on the machine; `SharedVM`: one `/lib/pvm` for every p-code process, freed with the last, wrong library refused; `CompiledC`: C compiled to p-code by `tools/cc.py --pcode`, run on the machine; `Basic`: `/bin/bas`, the compiled BASIC, typed at the shell).

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
| A failed send to a drive (`iec.s` `iec_out_end`/`io_flush`, `blk.s` `iec_open`, `cmd_send`, `iec_write`, `cbm_write`) | `tests.test_iec_fault` (faults injected through the VICE monitor; `FAULT_K=0,1,2,3,last` for the whole matrix, about 45 s a case; `IecRestart`: a half command left in drive 8, and in a drive 9 mounted later, across a C64-only restart; the boot flush faulted once, twice and three times, on its last byte and on its first (three failures: the mount fails loudly, nothing scratched); a real U2 cut off by a C64 reset after `FAULT_K` bytes, default 9; about 120 s; `IecOpenFault`: the "i0" or "#" of the mount's OPEN lost once (a retry), three times (EIO, never the REU root), and at mount 9; `IecRestart.test_flush_listen_missed`, `test_listen_missed_twice`: a LISTEN not taken; `IecFault.test_u2_status_timeout`, `test_u2_unlisten_lost`, `test_epoch_after_failed_first_write`; the spurious-EOI and EOI-then-lost kinds `test_*_eoi`, `test_*_eoi_lost`; `IecDosError`: a write-protected drive 9 and one with read errors, the drive's own error is not retried, about 100 s) |
| The timed bus code (`iec.s`, segment `IECBUS`) | the link: `tb`/`tx` assert the page-crossing of the branches in the bit loops and handshake waits (`dly`, `io_atn_begin`, `io_tx`, `bus_acptr`'s waits and bit loop, `bus_tksa`'s turnaround wait); a change that breaks one fails `make`. Not wrapped, because they are taken only once the bus has failed or timed out, or between bytes while the listener waits on our CLK: `bus_acptr`'s three `beq @tmo` exits, the status and carry checks in `io_cmd`, `io_first`, `bus_second`, `bus_ciout`, `bus_unlsn`, `io_last` and `bus_tksa` (before its wait). A change to those is not caught by the link |
| REU, `/tmp`, the REU block cache, the REU root device, `eject` and `reattach` | `REU`, `REURoot`, `Cache`, `Eject` (about 11 minutes: it boots VICE about 20 times, with a 2 MB REU image kept across boots) |
| Loader, `as`, `basic` (`exec.s`, `as.s`, `basic.s`) | `test_17`, `test_18`, `test_19`, `test_28` (the deepest legal expression across context switches; the stack cap) |
| Context-switch stack (`proc.s`, `STKSAVE`) or anything that deepens a program's stack | measure: `make STKWATCH=1` (rebuild from clean: `rm -rf build`), then `tools/with-lock -r vice -- xvfb-run -a python3 -m unittest tests.stkwatch` (not in the suite; writes `build/stkwatch.txt`: high-water mark per workload and kills). The limit is `STKSAVE` (128) minus 1; keep the worst case at least 17 bytes under it |
| A single command in `src/bin/` | the test that uses it (`grep -n <name> tests/test_system.py`): `tee`, `tail` and `sort` have `Pipes`, `touch` has `Touch` |
| The assembler (`as.s`) | `tools/test_as.py` (host: `as` runs under py65 via `tools/asim.py`, 0.1 s per program), then `Boot.test_19` and `test_27` |
| The compiler (`tools/cc.py`, through slice 3) | `tools/test_cc.py`, `tools/test_cc_run.py` (host; programs run on a 6502 simulator), then `tests.test_compiled.Compiled` on the machine |
| The p-code back end (`tools/cc_pcode.py`, `cc.py --pcode`) | `tools/test_cc_pcode.py` (host, py65, run from `tools/`; runs `test_cc_run`'s programs again as p-code), then `tests.test_pvm_machine.CompiledC` on the machine |
| The compiled BASIC (`src/pc/bas.c`, `/bin/bas`) | `tools/test_bas.py` (host, py65, run from `tools/`), then `tests.test_pvm_machine.Basic` on the machine |
| The p-code VM (`src/pvm/`) | `tools/test_pvm.py` (host, py65, run from `tools/`), `python3 tools/pvm_bench.py` for speed against `cc.py` and cc65, then `tests.test_pvm_machine` (`PCode`, `SharedVM`) on the machine; the CX loader (`src/kernel/exec.s`) also wants `Modules` and `Exec` |
| Image tools, key tables (`tools/`) | `make test-host` |
| `SYS_LSEEK` (`sys_lseek` in `file.s`, `uci_size` in `src/mod/uci.s`) | `tools/test_lseek_sim.py` (py65, c64fs and UCI), `Pipes` (`tail` seeks) |
| UCI v1 (`src/mod/uci.s` = `/lib/km/uci`, the stubs in `src/kernel/uci.s`, the `bmi` sites in `file.s`, `fs.s`, `exec.s`, `cbm.s`) | `make test-host` with py65 (`tools/test_uci_sim.py`), plus `Drives`, `REU`, `Pool`, `Modules` and a smoke run in VICE |
| 1581 volumes (`src/mod/d81.s` = `/lib/km/d81`, the hook labels `ts_rd_io`, `ts_wr_io` in `blk.s` and `open_mnt_io`, `open_dio_io` in `cbm.s`, `tools/mkimage.py d81`) | `make test-host` (`tools/test_mkimage.py`, and `tools/test_d81_sim.py` with py65: fake drives at the DOS-command level), plus `tools/ci/run.sh test-only T="tests.test_d81_vice"` (its 1581 test skips without a `dos1581*` ROM, which `tools/setup-vice-roms.sh` does not fetch) and `Drives` |
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

## Comparing builds byte for byte

The disk carries its source revision (a locked `DEL` directory entry `BUILD <rev>` after the boot file, and `/etc/build`; `+` marks uncommitted changes to tracked files), so every commit changes `build/breadbin.d64`. To show that two trees build the same disk (a comment-only change, a build switch that should be a no-op), build both with the same fixed stamp, `make BUILDREV=0`, and compare those images. The kernel `.prg` does not carry the stamp. `tools/ci/run.sh` passes the host's revision into the container, which has no `.git`; set `BUILDREV` to override it.

## Known issues

- **Known flaky: `tools/test_shards.py` `test_ctrl_c_stops_every_shard` (host test, fixed, watch for recurrence).** It failed once inside `tools/land.sh`, then passed alone (twice) and on retry. The fix `fix/shards-ctrlc-race` landed afterwards (merge `9d4edb7`: the test now polls for the stopped count, since the stub's TERM trap can finish after the driver's wait returns). If it recurs, rerun it alone and report.

- **Keyboard key loss: two classes, neither root-caused (open; owner's call).** (1) Key-buffer boundary loss (keybuf / Ultimate DMA): a keybuf write of 8 bytes lost its last chunk once in 5 VICE trials (the Return), and on the Ultimate the first character of a second 8-byte chunk was dropped once ('cat /nop' | 'e'). The rate is low and the mechanism is unknown. The capacity hypothesis (the 10-key buffer overflowing when a write lands on pending keys) was tested by counting pending keys before each write: the largest count seen was 8, and no loss occurred in 8 trials. That hypothesis is not supported. The count went through the VICE monitor, which pauses the machine, so it is a lower bound. (2) The X-press path in VICE: a key sent by xdotool right after TAB completion was not counted by the matrix scan, and the scan itself was clean (no unstable reads, counts steady). Delivery of xdotool events into VICE is not confirmed, and a real fast TAB-Return on hardware is untested. The hardware drop is reproduced once (Ultimate, Boot test_09_errors); it is not yet reproduced on demand. No kernel change is made for either class. Both classes are injection paths (keybuf and Ultimate DMA writes; xdotool into VICE). No loss from a physical key press on a real keyboard has been shown; if the demo's drops were human typing, they remain unexplained.

- **`test_tab_no_match_does_not_fire` failed in its setUp (VICE test; harness, fixed by `2c42747`, watch for recurrence).** Repro: `tools/ci/run.sh test-only T="tests.test_keyboard.Keyboard.test_shifted_symbol tests.test_keyboard.Keyboard.test_tab_completes_a_real_key tests.test_keyboard.Keyboard.test_tab_no_match_does_not_fire"` ended on screen `/ $ echo clear`: the RETURN after TAB completion was lost, `echo` stayed pending, and the next setUp's `clear` was appended. Evidence (2026-11-13, container): the `test_keyboard.py` of `2c42747^` fails the repro 2 of 2 with that screen; the current file passes 3 of 3 (screen at each tearDown: `/ $ echo` then `/ $`, so RETURN ran). `2c42747` added `submit` (a second RETURN if the first got no result in 8 s) and `clear_line` in setUp and tearDown. Which of the two does the work was not bisected. The lost RETURN itself (a key sent right after TAB reaching VICE, or the bus code running with interrupts off) is not root-caused; it is the second class in the key-loss note above. If this recurs, record the screen at setUp and tearDown first.

## Profiling (vprof)

`python3 tools/vprof.py build/breadbin.d64 "wc /bin/as" --setup "mod load /lib/km/fast" --anchor fast:ft_read --points iec_read fast:ft_start fast:ft_good` (under `xvfb-run`; also the `vice-profile` block) sets VICE tracepoints on kernel or module labels and prints the emulated time between consecutive events, per anchor hit. Real speed only (warp changes the cycle count); never trace a byte-loop label. `tests/test_vprof.py` checks the event count against the counter `fast.km` keeps; `tools/test_vprof.py` covers the parsing and arithmetic offline.
