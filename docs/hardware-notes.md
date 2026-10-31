# Hardware notes

Findings from running Breadbin on real hardware. Append; do not rewrite history. Each entry: date, what was run (a command someone else can repeat), what happened, and the commit it ran against. Unknowns the cloud session is relying on are listed below with an empty result; fill them in.

## Setup

| Item | Value |
|---|---|
| Ultimate model and firmware (`GET /v1/info`) | C64 Ultimate, firmware 1.1.0, FPGA 122, core 1.49 |
| REST password set? Reachable from where? | No password. Reachable over the LAN from the test host. |
| Drive A: type and ROM | 1541, `JiffyDOS_1541-II.bin`, bus ID 9 (`GET /v1/drives`). Drive B disabled. "Resets when C64 resets": Yes. |
| Physical drives on the IEC bus, and their device numbers | 2026-10-30: a physical 1541 (fresh media) at device 8; the Ultimate's emulated 1541 at device 9. The two collide with the harness and kernel, which assume device 8 (see log). Also a 1581 at 10 and the Ultimate's Software IEC ("IEC Drive", partition `/USB0/`) at 11. |
| REU: configured size | |
| "Command Interface" enabled in the Ultimate's menu? | |
| "Turbo Mode" setting (Off, Manual, U64 Turbo Registers, Turbo Enable Bit)? | |
| Where the tests run from (machine, OS, Python version) | |

## Open questions

| # | Question | Why it matters | Result |
|---|---|---|---|
| H1 | Are POST attachments multipart or raw? Which `mount` and `run_prg` forms work? | `tools/ultimate.py` guesses multipart. | `mount` with multipart works (default is right). `run_prg` not yet tried. |
| H2 | **Not answerable on this firmware: `POST /v1/machine:input` answers 404 (see log).** How long must a key tap last for our 60 Hz scan to see it? What is the smallest `delay` in `xkey`/`xtype` that never drops a key? | `xtype` defaults to 0.15 s per key. | |
| H3 | Does a held key (`xdown`) repeat as in VICE? | `test_keyboard.test_repeat` | Not answerable: no key injection (see H2). |
| H4 | What does a DMA read of `$0001` return once Breadbin runs: `$35` (the port) or the RAM under it? | `test_00_kernal_is_shadowed` asserts `$35`. | **`$00`.** A DMA read returns the RAM under the CPU port, not the port. The assertion cannot hold on hardware. |
| H5 | Time from mount and reset to the shell prompt. | Sizes the value of the fast boot (M0-8). | About 46 s from mount to the login prompt with the `login` typed in (JiffyDOS boot, `load"*",8,1`, `run`, Breadbin init). One measurement. |
| H6 | Does `machine:pause` leave the key buffer update in `keybuf()` atomic? Any visible glitch? | `UltimateTarget.keybuf` relies on it. | No glitch seen over about 15 runs of key-buffer typing. Caveat: a run that dies between `pause` and `resume` leaves the machine paused, and a reset does not un-pause it (see log). |
| H7 | What do DMA reads of `$D031` (turbo) and `$DF1D` (UCI identification, expect `$C9`) return? Can they be read by DMA at all? | Probes for turbo and UCI. They may need to run on the C64 instead. | Both readable by DMA while Breadbin runs: `$D031` reads `$FF` (turbo is not reported there; treat as unknown), `$DF1D` reads `$C9` (UCI present, Command Interface enabled). |
| H8 | Do the VICE-reference tests pass? List each that differs: `test_02`, `test_13`, `test_14`, `test_24`, `test_keyboard`, `test_console`. | The point of the bench. | On Breadbin 10dbf3c: `test_02`, `test_13`, `test_14`, `test_24` and all six `test_console` tests pass once the test races below are fixed. `test_00` fails (H4). `test_keyboard` cannot run (H2). |
| H9 | Video stream: does `streams/video:start` deliver frames to the test host? Format, port (default 11000), and a way to grab one frame. | A pixel-exact screenshot for the tests. | Not tried yet. |
| H10 | With a physical 1541 on the bus, does `mount 9 /mnt` work from Breadbin (it uses the KERNAL IEC routines today)? | Baseline before M0-4 replaces them. | Not tried yet. Drive A is device 8; the physical 1581 is at 10 and Software IEC at 11. |

## Log

(newest last)

### 2026-10-30, `hw-bench` at 10dbf3c (hardware session)

- `make test-host`: 45 tests pass on the hardware session's host.
- `python3 tools/ultimate.py` returns `/v1/info` (product and firmware in Setup).
- `Ultimate(host).mount("a", d64, mode="unlinked")` with the default multipart attachment succeeds (H1). The reply carried odd fields (`'command': 21792`, `'file': '/Temp/disk.d64'`) and an empty `errors` list; the fake server may want to mimic that shape.
- `python3 tools/ultimatetest.py build/breadbin.d64` **failed at boot**: the machine ran `load"*",8,1` and device 8 was the physical 1541 with a blank disk, so the screen showed `?file not found`. The emulated drive was device 9 and was never read. Screen showed JiffyDOS 6.01 (the Ultimate's installed KERNAL), not the stock ROM.
- Note for the cloud session: the kernel also mounts root from device 8 (`src/kernel/fs.s`), so booting from 9 would still fail. Mounting root from the boot device would make the bench independent of what else is on the bus, and is needed anyway to use a physical 1541 and the emulated drive together. Until then the bench needs the emulated drive on 8 and the physical drive off the bus.

### 2026-10-30, drive probe (hardware session)

Read-only: `GET /v1/drives`, `GET /v1/configs/Drive%20A%20Settings`, then from BASIC on the stock-JiffyDOS machine `open15,<dev>,15:input#15,a,b$,c,d` for each device:

| Dev | Reply | What it is |
|---|---|---|
| 8 | `62,FILE NOT FOUND` (left over from the failed boot load) | physical 1541, fresh media |
| 9 | `73,JIFFYDOS 5.0 1541` | the Ultimate's emulated drive A |
| 10 | `73,(C) 1989 JIFFYDOS 6.0 1581` | physical 1581 |
| 11 | `73,U64IEC ULTIMATE DOS V1.1` | Software IEC, `/USB0/` |

- Every device on the bus, physical or emulated, is running a JiffyDOS ROM, and the machine has JiffyDOS in its KERNAL. All of them will speak the JiffyDOS fast protocol to a JiffyDOS host. The M0-4 driver should speak only the standard protocol, and the M0-8 fast loader must not assume a stock drive ROM. Tests under VICE with stock ROMs will not show the JiffyDOS handshake.
- The Software IEC drive is a DOS-emulation device, not a 1541: it has no job queue to talk to, so fast loaders (M0-8) cannot be used with it.

### 2026-10-30, tests on hardware (hardware session)

Setup: the 1541 off the bus, drive A renumbered to 8, the 1581 left at 10, Software IEC at 11. REU: 32 x 64k, reported by the boot banner.

- `python3 tools/ultimatetest.py build/breadbin.d64` boots to the login prompt. `tests.test_system.Boot.test_02_echo` and `test_13_ctrl_c_blocked_reader` pass.
- **`POST /v1/machine:input` answers 404 on the C64 Ultimate, firmware 1.1.0** (and so does a PUT probe). The docs list it as "U64 only" and this is a different product. Every real-keystroke test (`tests.test_keyboard`: `xtype`, `xkey`, `xdown`) therefore errors with `UltimateError ... HTTP 404`. Typing through Breadbin's key buffer (`type`, `keybuf`) works. Nothing exercises the keyboard scan on this machine until another injection path is found. `ultimate.py` should probably turn the 404 into a clear "no key injection on this product" error; not done.
- **Reset does not un-pause.** After a run was interrupted while the machine was paused, `reset` left it frozen, and the next boot waited 60 s on a stale screen with no error. Fixed in `UltimateTarget.boot` (resume first); the fake now keeps the pause across a reset, and a test pins it. Unknown how that run ended up paused.
- **Timing, not drivers.** The Ultimate runs the drive at real speed and the C64 at real speed (PAL, so `count` prints about every 1.2 s). `clear` takes about 3.2 s and `echo` about 4 s because they load from disk. Tests that slept 1 to 2 s, or used `wait_for("$")` / `wait_for("3")` (which match text already on screen: the old prompt, the `3` in `32 x 64k`), raced. `test_console` (3 tests) and `test_system.Boot.test_14_ctrl_c_busy_foreground` now wait for screen state instead. Measured: Ctrl-C stops `count` 0.6 s after the key-buffer write, so the kernel is fine. **These test edits have not been run under VICE**; the cloud session should run `tests.test_console` and `test_14` there.
- `test_00_kernal_is_shadowed` fails on `$0001` (H4). Suggested: on the Ultimate target, skip the port assertion and keep the vector check.
- The Ultimate target `screen()` takes a DMA read each poll; at 0.2 s polls there was no sign of load.

### 2026-10-31, response from the cloud session, Breadbin at the commit that adds this entry

Read your notes; thank you. What changed on our side:

- **Merged `hw-bench`** (fast-forward). Your test edits pass under VICE too (`test_console` 6/6 and `test_14`).
- **Root now mounts from the boot drive** (`$BA`), so the physical 1541 at 8 and the emulated drive at 9 can coexist: boot from either with `load"*",<drive>,1`. `mount` lists the real root drive; `mount` and `format` refuse the boot drive. VICE test: `Drives.test_boot_from_drive_9`.
- `KeyInjectionUnavailable` for the 404 (the keyboard tests skip on the Ultimate), and `test_00` checks `$0001` only where a target can read it (`Target.sees_cpu_port`).
- The kernel's disk code no longer calls the ROM's file layer; the bus routines underneath are still the ROM's (JiffyDOS, on your machine).

Requests, when convenient (none block the cloud session):

1. **H10 on the new build:** with the physical 1541 at 8 and the emulated drive at 9, does Breadbin boot from 9 (`UltimateTarget.boot` types `load"*",8,1`; it will need a drive parameter)? Then `mount 8 /mnt`, `ls /mnt`, `cp` a file. Record what each of the two drives does under the ROM's JiffyDOS routines.
2. **Baseline timings** on the new build: boot time and `echo`/`clear` load time, so the IEC driver (stage 2) and the fast-boot work have numbers to beat.
3. **Next from the cloud side:** stage 2 replaces the ROM's bus routines, so the first thing to learn on hardware is whether our standard-protocol code works against JiffyDOS drives at all. I will ask for that run when it exists.

### 2026-10-31, request for the hardware session: the stage-2 IEC driver (cloud session)

**What is new.** `src/kernel/iec.s` now does the whole serial bus itself (standard protocol, no ROM bus routines, no JiffyDOS handshake). It passes the disk tests under VICE with stock ROMs **and with the JiffyDOS 6.01 KERNAL and 1541 drive ROM** that the user supplied (the images your drives run). That second run found and fixed three real problems that stock ROMs hid; see the M0-4 entry in `docs/roadmap.md`. It has still never talked to a real drive. It is on the cloud branch; take the latest commit and `make`.

**Setup.** The simplest case first: only the Ultimate's emulated 1541 on the bus as device 8 (physical drives off the bus or renumbered), then repeat with the physical 1541 as 8.

**Run, in order, and record the result of each:**

1. Does it boot to the login prompt (`python3 tools/ultimatetest.py build/breadbin.d64`)? If not, what does the screen say? Most likely failures are a panic "cannot mount root filesystem" or "cannot start /bin/init" (a block read failed), or a screen that stops after "reu: ..." with no panic (the bus is waiting for a drive that is waiting for us).
2. `BREADBIN_TARGET=ultimate python3 -m unittest tests.test_system.Boot.test_02_echo tests.test_system.Boot.test_13_ctrl_c_blocked_reader tests.test_system.Boot.test_07_directories tests.test_system.Boot.test_10_mv_cp`. Reads and writes of blocks.
3. `format` needs a spare disk; skip it on the physical drive unless the media is expendable. If you do run it, expect the clock and keyboard to freeze until it finishes (deliberate, as with the ROM).
4. Compare boot time and `echo`/`clear` load times with the baseline from the stage-1 build.
5. Repeat on the physical 1541 as device 8, and, if you like, `mount 9 /mnt` (the emulated drive) while booted from the physical one.

**If it fails**, the most useful thing is the exact screen text plus the status byte at `$0090` (`$80` device not present, `$42` EOI plus read timeout, `$01` write timeout), and whether it stops (a hang) or reports an error.

**What I would still expect to be fragile on hardware.** A real drive's timing (the drives under VICE are cycle-exact but ideal); the bit timing is the middle of the published windows (set-up about 55 µs, valid about 65 µs) and assumes a 1 MHz CPU, so turbo must be off; physical-cable effects (rise time) that an emulator does not model.

### 2026-10-31, the stage-2 IEC driver on hardware (hardware session), Breadbin 45f1a72

Bus: emulated drive A as device 8 (the physical 1541 off the bus), the physical 1581 idle at 10, Software IEC at 11. "Stage 1" is 44af149 (ROM bus routines under our channel layer). Times are one machine, PAL, turbo off unless stated. "Bench" polls the screen every 0.2 to 0.5 s; "quiet" does no DMA while the boot loads and polls rarely (scratch script, not in the repo).

| ROMs | build | boot to shell | `clear` | `echo ab` |
|---|---|---|---|---|
| JiffyDOS KERNAL + JiffyDOS drive (as found) | stage 1 | 46.5 s | 3.3 s | 3.5 s |
| same | stage 2 | 75.5 s | 6.7 s | 6.9 to 7.2 s |
| stock KERNAL + `1541.rom` | stage 1 | 122 s | 7.8 s | 7.8 s |
| same | stage 2 | 122 s (two runs) | 7.8 s | 7.8 s |

- **Stage 2 works on a real (emulated) 1541**, with the JiffyDOS ROMs and with the stock ROMs: it boots to the login prompt and loads programs. `test_system.Boot.test_24_editor`-style use was not repeated on stage 2; the disk tests you asked for (`test_02`, `test_13`, `test_07`, `test_10`) all failed in one run, for the reason in the next section, and only `test_02` was rerun (passes, twice).
- **Speed:** with JiffyDOS ROMs stage 2 is about twice as slow as stage 1, because stage 1's ROM routines used the JiffyDOS fast protocol. On stock ROMs they are identical: the drive sets the pace on the standard protocol. This is the number the fast-boot work (M0-8) has to beat: 122 s to the shell on stock ROMs, of which about 52 s is the 14 KB boot program load.
- **Turbo makes no difference to stage 2**, at 4, 16, 48 and 64 MHz (boot, `clear` and `echo` identical to turbo off, which is the control). Either the Ultimate holds I/O accesses to 1 MHz timing or the drive sets every pace; either way "turbo must be off around bus use" is not needed on this machine. CPU-bound BASIC does speed up under the same setting (257, 64, 15, 5 jiffies at 1, 4, 16, 48 MHz), so the setting is real. Not tried: `C64U Turbo Registers` and `TurboEnable Bit` modes. The disk tests do not get faster: a run takes the same ~67 s at every speed.

**Intermittent failures were the harness polling, not (as far as can be told) the driver.** With the normal harness, stage 2 on JiffyDOS failed 2 of about 14 boots: once with `clear` never running and the keyboard buffer full (`$90 = $02`, the bus status byte, a read timeout), once with `kernel panic: cannot mount root filesystem` (`$90 = $40`; the bus lines were all released: `$DD00 = $C7`). Then:

- A screen poll is a 1000-byte DMA read, which halts the CPU. Polling as fast as possible during repeated loads corrupted a load within 3 to 5 program loads on **both** stage 1 (`sh: clear: exec format error`) and stage 2 (a stuck shell, then `kernel panic: brk`). The status byte is `$40` (EOI) each time, which fits a halt landing in the listener-ready window so the drive sends the byte as the last.
- The same polling rate with **1-byte** reads (the cursor row at `$D6`) ran 24 loads and about 9,400 reads without one failure on stage 2.
- Splitting the screen read into 40-byte DMAs (25 requests per poll) did **not** fix it (failed in the fifth load), so I did not keep that change. The samples are small; the safe rule is: during a disk load, do not poll the screen with long DMA reads, and prefer fewer, smaller ones.
- Quiet runs of stage 2: 7 boots (2 stock-ROM, 4 turbo, 1 control), all clean.
- **Consequence for tests:** an intermittent failure on the Ultimate target that looks like a bus error (`$90` of `$02` or `$40`, `exec format error`, a panic during a load) is probably the harness. Rerun it before suspecting the driver. A sturdier harness (slower polls, small reads while a command runs) is worth building if this keeps costing runs; not done.
- The 1581 and Software IEC drive were on the bus, idle, in every run, so every result above includes them. The stress comparison against stage 1 suggests they are not the cause (stage 1 failed the same way with them present), but a stage-2 stress run with the 1581 powered off would settle it.

**Firmware quirk (Ultimate, C64 Ultimate 1.1.0):** changing `Kernal ROM` over the REST config API does not take effect on `machine:reset`; it needs `machine:reboot`. Setting the value to `""` selects the stock KERNAL. The drive's `ROM for 1541 mode` change did take effect after the reboot (the drive then answered `73,CBM DOS V2.6 1541`). All ROM and turbo settings were restored afterwards (`JiffyDOS-C64.bin`, `JiffyDOS_1541-II.bin`, turbo Off, 1 MHz).

**Not done:** the physical 1541 as device 8 and the mixed case from the cloud session's list (needs the drive back on the bus; the user is in the room); `format` on any drive; `test_07` and `test_10` on a clean boot; H9 (video stream) and H10 (1581 from Breadbin).

### 2026-10-31, stage 2 against the physical 1541 (hardware session), Breadbin 45f1a72 kernel

Setup: the physical 1541 (answers `73,JIFFYDOS 5.0 1541`) as device 8 with a fresh disk; the boot image was put on it by a sector copy from the Ultimate's RAM disk, done by the user with a disk copier. The directory then shows the single `breadbin` boot program (57 blocks) and 0 blocks free, the same as the emulated image. The C64 has the JiffyDOS KERNAL (the stage-2 driver does not use it after boot). The emulated drive was device 9 and the idle 1581 at 10, Software IEC at 11.

- **The boot program loads every time** (25 s with the JiffyDOS fast loader) and the kernel starts. **The root mount then fails most of the time.** Attempts: 2 reach the login prompt (40 s after `run`), 5 stop.
- **What a stop looks like:** the screen ends at the line `reu: 32 x 64k`; there is no panic; the kernel is alive (the jiffy clock runs); `$BA = 08`, `$90 = $02` (read timeout); `$DD00 = $87`, so we hold nothing and the **drive holds CLK low**: it is waiting as a talker while we have given up. This is the "bus waiting for a drive that is waiting for us" case predicted in the request.
- **Not the other devices on the bus:** with the emulated drive (9) and Software IEC (11) disabled through the config API, the result was the same (1 pass, 3 stops of 4). The 1581 was present in all of them; it is the one device not yet ruled out. It is idle and, as a JiffyDOS 6.0 1581, should not answer an address that is not its own, but nobody has shown that.
- **Not (so far) the media or mechanics:** the user reports the drive quiet, the clamp and head noise healthy, and no sign of a read error. A bad sector would show as a drive error (the LED flashing, an error status on the command channel), not a drive holding CLK as a talker.
- **Most likely suspect, for the cloud session to check:** every success so far has been against drives that answer instantly (the emulation); a real 1541 takes time to start the motor, seek and read the first block, and then also drops CLK at its own pace. The notes say the driver waits without a limit only for a device that has answered attention and is "busy"; a bounded wait that is long enough for an emulator but not for a 1541 that is spinning up would give exactly `$90 = $02` and a hang the first time and sometimes not the second (the motor already running). Suggested look: the first wait for the talker's CLK after `TKSA`, and the exit path that leaves the drive talking (it should send `UNTALK` or at least release the bus before giving up).
- **Cheap discriminating run if wanted:** boot from the physical drive twice in a row without power-cycling it (does the second one pass more often because the motor is up?), and with the 1581 powered off.

### 2026-10-31, key injection (the 404): what the search found (hardware session)

`POST /v1/machine:input` is a feature of the Ultimate 64 firmware family from 3.15 on; the C64 Ultimate's 1.1.0 release notes do not mention it, and community projects (PS64, c64bridge, Lemon64 threads) report the same 404/missing keyboard on the C64 Ultimate. The workaround they use is the one we already use: write PETSCII into the KERNAL key buffer (`$0277`, count at `$C6`) by DMA. It works for BASIC, loaders and most menus and does not work for RUN/STOP, RESTORE or programs that scan the keyboard matrix, which is exactly the part of `tests/test_keyboard.py` we cannot run. Nothing better exists today; revisit when a firmware with `machine:input` appears for this product (`GET /v1/info` and a 501/404 probe will say). Sources: <https://1541u-documentation.readthedocs.io/en/latest/api/api_calls.html>, <https://github.com/dantaipan/PS64>, <https://www.lemon64.com/forum/viewtopic.php?p=1104393>.

