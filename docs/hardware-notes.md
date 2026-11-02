# Hardware notes

Findings from running Breadbin on real hardware. Append; do not rewrite history. Each entry: date, what was run (a command someone else can repeat), what happened, and the commit it ran against. Unknowns the cloud session is relying on are listed below with an empty result; fill them in.

## Setup

| Item | Value |
|---|---|
| Ultimate model and firmware (`GET /v1/info`) | C64 Ultimate, firmware 1.1.0 |
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

## Hardware list (run at milestones, not per story)

The standing checklist for a hardware run of a new build. Record the commit and each result in the Log.

1. Boot to the login prompt: `python3 tools/ultimatetest.py build/breadbin.d64`. Note the time.
2. `BREADBIN_TARGET=ultimate python3 -m unittest tests.test_system.Boot.test_02_echo tests.test_system.Boot.test_13_ctrl_c_blocked_reader tests.test_system.Boot.test_07_directories tests.test_system.Boot.test_10_mv_cp tests.test_console`
3. Repeat step 1 and `test_02` with the physical 1541 as device 8 (the Ultimate's drive off or renumbered), and `mount 9 /mnt` of the other drive from the shell.
4. `format` only on expendable media.
5. Anything the changed story says needs checking (the commit message names it).

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

### 2026-10-31, the "everything answers OPEN" scare, and what it was (hardware session)

**Retracted: there is no ghost device and no fault on the bus.** `OPEN 1,N,15` (no filename) returned status 0 for every device number from 4 to 30. That looked like something acknowledging every address. It is ordinary KERNAL behavior: an `OPEN` with an empty filename puts nothing on the serial bus, so there is nothing to refuse. The same `OPEN` with a filename, `OPEN 1,12,0,"$"`, gives `?DEVICE NOT PRESENT ERROR` on an empty bus, with the stock-style probing. An `INPUT#` from a channel to an absent device hangs (the KERNAL waits for a talker that is not there); that is also normal. Lesson for anyone probing the bus from BASIC: **use a name, or read from the channel**, never `OPEN n,dev,15` alone.

Electrical checks, all from BASIC or machine code with the KERNAL out of the way:
- With the 1541 off and the emulated devices disabled, asserting ATN (`POKE 56576,PEEK(56576) OR 8`) leaves DATA high: nothing on the cable or in the C64 Ultimate's port pulls it down.
- With the emulated drive and Software IEC enabled, DATA goes low as soon as ATN is asserted and stays low for the whole 2 ms sampled at about 9 us per sample (a 256-sample routine at `$C000`); releasing ATN releases it. That is the normal ATN acknowledge.
- Both the JiffyDOS and the stock KERNAL behave the same, so the KERNAL is not the issue.

**What this means for the physical-1541 stalls above: nothing is explained yet, and the earlier series needs redoing.** The 5-of-7 stall rate, and the "not the emulated drive or Software IEC" conclusion, were all measured with the **1581 attached to the bus** (powered, or switched off but attached). The user found that removing the 1581 changed behavior: before, loading from the 1541 was unreliable; after, a load from device 8 worked from BASIC. A switched-off device still attached to the bus can load the lines through its interface parts, and the FNX 1581 clone may need to be on if it is attached. So **the 1541 stall results are not trustworthy as a measure of the driver**, and the "most likely suspect" in the entry above (a bounded wait that is too short for a spinning-up drive) is still only a hypothesis. The 1581 is now off the bus entirely and stays off until there is 1581 work.

Next, in this order (each needs the 1541 powered on and the 1581 absent):
1. Boot Breadbin stage 2 from the 1541 repeatedly (the same loop as before) and count stalls. If they are gone, the earlier failures were the 1581 and this is closed.
2. If they remain: stock KERNAL (reboot after changing `Kernal ROM`), `LOAD` the 14 KB boot program from device 8 five times and read blocks with `U1`. That is the standard protocol from the ROM against this drive. If it is solid, the stall is in our driver's timing against a real drive; if it also fails, it is the drive, the cable, or the drive's own JiffyDOS ROM.
3. A stage-1 image on a second physical disk (a sector copy again) would give the direct A/B: same drive, same disk, only the bus code differs.

### 2026-10-31, state of play on the physical-1541 stall (hardware session), for whoever continues

Tools: `experiments/iec-stall/` (README there). Commits referred to: kernel experiments on the branch `iec-bit-waits` (not merged, not proven).

**Facts, measured**
- Only the physical 1541 on the bus (the emulated drive and Software IEC disabled, the 1581 removed), Breadbin stage 2 loaded by DMA with the root on device 8: the root mount stalls in most boots. Counting every clean-bus run so far the original kernel passed about 3 times in 14. The same drive, the same disk and the same file loaded with the stock KERNAL's receive code (`stockload.py`): **5 of 5 byte-identical** loads of 14,362 bytes, screen on.
- The stall state: kernel alive and in `bus_acptr`'s `@rdy` wait (unbounded, interrupts on), `$DD00 = $87` (the drive holds CLK low, DATA released), the drive's motor stopped and its LED steady on. `$90` bit 1 is only ever set by `bus_acptr`'s timeout exit, so an earlier call timed out and every later call then blocks in `@rdy`: **one timeout, then a hang**.
- The bit counter at the first timeout was 5 remaining (3 bits received) in one stall, 2 remaining in another: different positions, so not a fixed cut-off point.
- Kernel variants tried on the real drive, none shown to help: waiting 0.8 s per bit instead of 3 ms (2 stalls, 1 pass); a shorter blind window between seeing the clock rise and watching it fall (1 stall, 2 passes at the time of writing). Neither is a fix.

**What an Opus advisor said (reasoning from the 1541 DOS source, unverified here; a hypothesis list, not evidence)**
- After the 8th bit a stock talker waits forever for the listener to pull DATA (`isr04`; only ATN ends it). That is exactly our stall state, so the drive believes it sent 8 bits: **we miss CLK-high pulses**; the drive is not dropping out.
- Suspected cause: the CLK-high pulse is short (about 34 us; about 75 us in the drive's slow "UI+" mode) and the VIC's badlines (40 to 43 stolen cycles) or sprites can swallow it. A byte spans about two badlines.
- Cheap tests it proposed: (a) send `UI+` on the command channel to the physical drive before the boot (a C64 reset does not reset the drive); (b) `M-R` of `$0023` (the speed-mode flag) on the physical and the emulated drive; (c) screen off during the mount; (d) a straight-line capture of `$DD00` inside `bus_acptr` (480 samples of `lda PORT / sta cap+i`, 8 cycles each, with a CIA timer read before and after to see cycles stolen by the VIC) decoded offline for pulse widths; and recover from a timeout by asserting ATN (UNTALK), not by calling `bus_acptr` again.
- Tests (a), (b) and (d) are not done. (c) was started: round 1 with the screen blanked by DMA still stalled (one sample), and it is not yet confirmed that the blanking took effect.

**Not yet explained, and the questions that remain**
- Why the ROM's receive handles this drive and ours does not, with the same VIC and the same drive. The obvious differences are the ROM's debounced double read of `$DD00`, its sampling points, and how long it is blind between bits.
- Whether the JiffyDOS 5.0 drive ROM changes the drive's speed mode or pulse width compared to the emulated image (`M-R` the same ROM regions on both and diff them).
- Whether the 1581's earlier effect (attached, even switched off) points at weak pull-ups or load on the lines.

**Corrections to earlier entries and to other notes**
- The "phantom ATN responders" mentioned in `docs/wip.md` do not exist: that was `OPEN n,dev,15` with no filename, which puts nothing on the bus.
- Polling the screen during a disk transfer can itself corrupt the transfer (see the 2026-10-31 DMA entry); every stall above was reproduced with no DMA read for the first 20 s.

### 2026-10-31, later: the stall is not in our receive loop (hardware session). Supersedes the "state of play" entry above where they differ

Everything below: only the physical 1541 on the bus, kernel loaded by DMA with the root on device 8, 1581 removed, `experiments/iec-stall/` tools (the histogram and interrupts-off kernels are on the throwaway branches `iec-pulse-hist` and `iec-nocli`).

- **Stage 1 stalls too.** With the stock KERNAL as the host (standard protocol), stage 1 (the ROM's own `ACPTR` running inside Breadbin) ended in the same frozen state as stage 2 (`$DD00 = $87`; `$90 = 0` because the ROM's receive has no timeout): 1 stall and 1 pass in two tries, the same intermittent behaviour as stage 2. **The fault is not in `bus_acptr`.** Every change to our receive loop (0.8 s bit waits, a shorter blind window, interrupts off while waiting) was therefore aimed at the wrong place, and none of them helped.
- **The drive's pulses are fine.** A histogram of how long CLK stays high per bit (about 25 to 85 us, buckets 1 to 6 of 12 cycles) came out identical in the passing run and in five stalling runs, and matches VICE's stock 1541. Not "pulses too short".
- **Where the stall falls inside a byte:** in nine valid dumps the receive bit counter was 2, 3, 5, 4, 5, 4, 6 and so on remaining; never 0, 1, 7 or 8. We were always somewhere in the middle of a byte when the drive went quiet.
- **BASIC does not reproduce it.** On the stock KERNAL, 393 consecutive `U1` block reads of 256 bytes on a `#` channel (all on track 18, no head movement, command channel opened without a command) ran with no stall and no drive error; the same drive loads a 14 KB file five times byte-identical. So the drive, the cable, the media and the standard protocol are fine for that access pattern.
- **What differs about Breadbin, to check next:** the access pattern (the mount reads blocks spread over many tracks, so the head seeks; it opens the command channel with `I0`); the C64's state (VIC, CIA1 timer, `$01 = $35`, interrupts enabled between bytes, the REU probed just before the mount); and the cadence of attention sequences. A scan with random tracks and `I0` first is running to test the first two.
- **Corrections:** the "most likely cause" in the earlier state-of-play entry (a receive loop missing short CLK pulses) is not supported; neither are the VIC-badline and short-pulse stories. The blank-screen test was contaminated by its own DMA and proves nothing.

### 2026-10-31, a flaky test seen under VICE (cloud session), for whoever is chasing flakiness

Observed twice in about 20 runs of `tests.test_keyboard`: keys typed through real X events go missing in a burst. The full-suite failure (M0-5 build): typed `echo abc 0123`, screen showed `ehobc 0123` (the first `c`, the space and the `a` lost); the other six keyboard tests in the same VICE session passed. An earlier, unlogged smoke-test error on a cold start may be the same thing.

My working theory, for the VICE harness only: `xdotool key` presses and releases within a few milliseconds of wall time, and with VICE in warp mode both events can arrive in one batch before the emulated machine has scanned the keyboard, so the key never exists as far as the 60 Hz scan is concerned. The fix being tested is to `keydown`, wait about 60 ms, `keyup` (see `Vice.xkey`). If that holds over repeated runs it is a harness problem, not a keyboard-driver problem. If you are seeing flakiness on the hardware bench (where there is no key injection, so it cannot be this), that is a different cause: the usual suspects are screen-state races (waiting on text that is already on screen), the pause and resume of the machine in `keybuf`, and timing of the bus.

### 2026-10-31, the physical 1541's ROM before the OEM swap (hardware session)

The drive: a long-board 1541 (second revision, twist-lock), JiffyDOS 5.0 installed; the user holds an OEM `901229-05 (C)1983` (`1185`) DOS ROM for the swap and reports that only the DOS ROM (not the low-level driver ROM) is replaced. It answers `73,JIFFYDOS 5.0 1541`.

- `M-R` reads of three 256-byte windows with the **stock KERNAL as the host** (`experiments/iec-stall/romwin.py`; repeatable: the same hashes on a second read). Windows `$C000` / `$E000` / `$FF00` (sha1 prefix): physical drive `aec2a25f` / `dbd462e1` / `562faa37`; the Ultimate's `JiffyDOS_1541-II.bin` `aec2a25f` / `dbd462e1` / `5709caf0`; the Ultimate's stock `1541.rom` `aec2a25f` / `dbd462e1` / `5e6f95c2`.
- The first two windows are the same in all three, so they cannot tell stock from JiffyDOS. **`$FF00` can: it differs from stock in 183 of 256 bytes.** After the swap, that window's hash should become that of the stock ROM revision in the drive (the Ultimate's `1541.rom` may be a different revision from `901229-05`, so compare against that if it differs, and confirm the vectors at `$FFFA`).
- **The physical drive and the emulated image are different JiffyDOS builds.** They differ in two bytes of the window, both the low bytes of `JSR` targets: at `$FF31` the physical drive has `JSR $E977`, the image `JSR $E96D`; at `$FF5A` `JSR $FB83` against `JSR $FB64`. Same call sites, routines at shifted addresses, so the patch code sits elsewhere. Everything that has passed cleanly has run on the emulated image; every stall on the physical drive's build. Until the OEM ROM is tested, that is a variable we have not controlled.
- The drive's speed-mode byte `$0023` reads `00` (slow, C64-compatible pulses) on both. A full 16 KB `M-R` dump with the JiffyDOS KERNAL as host was unusable (a zero after most bytes, offset streams); do not repeat that. A full dump with the stock KERNAL takes about nine minutes.
- A side result: reading 16,384 bytes one `GET#` at a time (16,000 attention sequences, 561 s) on the physical drive did not wedge it, consistent with the 393 and 227 block reads earlier.

### 2026-10-31, the stall predates our work; what has been ruled out (hardware session)

All on the physical 1541 as device 8, nothing else on the bus (the 1581 removed, Drive A and Software IEC disabled), kernels loaded by DMA, the stock KERNAL as the host, the disk that was already in the drive. `experiments/iec-stall/bisect.sh` (the version that copies images) and `plainboot.py`.

**Regression bisect by loading older kernels against the same disk** (the disk format is the same for every commit: `mkimage.py` has not changed since the upstream baseline, and the disk ID is the constant `BB`). Five boots each, interleaved:

| Kernel | Passes in 5 |
|---|---|
| upstream baseline `aa58d27` (before any of our work) | 1 |
| M0-1 `a5ad5dd` (KERNAL shadowed, own vectors) | 0 |
| M0-3 `9fd51a0` (own keyboard and screen) | 3 |
| M0-4 stage 1 `07813bb` (own channel layer, ROM bus routines) | 1 |

5 passes in 20 boots overall, a quarter, with no kernel separable from the others at these sizes (M0-3's 3 of 5 is within chance of a 25% rate). **The stall is not something our changes introduced: the pre-fork upstream kernel has it.** A pass is a login prompt in 42 to 52 s; a stall is the screen frozen in the mount (at the `reu:` line or just after the banner), the drive holding CLK, motor stopped, LED steady.

**Ruled out, with the evidence** (cumulative, this and earlier entries):
- our receive code, the bit timing and the interrupt window inside it (stage 1, upstream and the ROM's own routines stall the same way);
- the drive's CLK pulse width (histogram identical on passing and stalling boots, and identical to VICE's stock 1541);
- the drive's ROM: swapped to an OEM `901229-05` (verified by hash of the `$FF00` window against the Ultimate's stock `1541.rom`; the physical drive had been running a different JiffyDOS 5.0 build from the Ultimate's image), then 2 passes in 6, the same rate;
- other devices on the bus, JiffyDOS vs stock host, turbo, the screen being on (untested properly), head seeks, the `I0` initialisation, a gap between transactions, interrupts held off through a block read (not yet run);
- the media: a timed read of all 683 sectors, one `U1` each, 0 drive errors, every block 4 to 8 jiffies, nothing slow;
- the access pattern and cadence: BASIC did 393 sequential and 227 random-track block reads, and a machine-code program calling the stock KERNAL's routines in the kernel's exact sequence did **512 block reads over a spread of tracks at full machine speed**, all with no stall and no drive error; the same drive loads a 14 KB file byte-identically 5 of 5.

**What is left, i.e. what differs between the runs that stall (every Breadbin kernel, including upstream) and those that don't (BASIC, the machine-code stress, LOAD):** the C64's own state under Breadbin (its interrupt handler and tick, the CIA and VIC setup, the REU probe, memory map), or something in the environment that only some host behaviours expose (the cable: long, a repurposed synth cable; the drive's power or RAM). In progress: the same machine-code stress with a deliberately slow IRQ handler (`BURN=4`, about 5 ms per tick) to see whether interrupt latency alone can wedge the drive. Next, with hands: a different cable (the 1581's), the 1541's second IEC socket, and a RAM test of the drive via `M-W`/`M-R`.

### 2026-10-31, the stalls are not tied to particular blocks, nor to command termination or interrupt latency (hardware session)

- **Which block each stall dies on** (the kernel's last `U1`, read from `cmdbuf` at the stall; original stage-2 kernel, 8 boots, 3 passes): track 3 sector 15; track 16 sector 1 (twice); track 11 sector 11. Always mid-byte (bits left 5, 4, 5, 6). Different blocks on different tracks, so no single bad sector.
- **Command termination is not it.** The kernel's `cmd_send` sends the `U1` text with no carriage return, so the command ends by EOI at `UNLISTEN`; BASIC's `PRINT#` and my first machine-code stress ended it with CR. The same stress with EOI only (`CR=0`): all 512 blocks, no stall.
- **Interrupt latency is not it.** The same stress with a deliberately slow IRQ handler (`BURN=4`, 5.2 ms burned on every 16.7 ms tick, about a third of the CPU): all 512 blocks, no stall.
- So, over 1,100 full block reads in the stock environment (BASIC and machine code, sequential, random and pseudo-random tracks, CR or EOI commands, normal or hostile IRQ) there is no stall, against about one per 25 to 40 block reads under any Breadbin kernel including the upstream baseline. Everything that can be varied in software and in the stock environment has been; the next variables are physical: a different IEC cable (the 1581's), the drive's second IEC socket, a shorter run, the drive's RAM and supply. `experiments/iec-stall/cabletest.sh LABEL [N]` runs N boots and appends `RESULT LABEL: k of N passed` to a results file, so each change gets one comparable line; the baseline is 5 passes in 20 (1 in 4 to 3 in 8 across series).

### 2026-10-31, the REU is not the cause; undocumented opcodes pass on the C64 Ultimate (hardware session)

- **REU disabled in the Ultimate's configuration** (`RAM Expansion Unit = Disabled`, the screen then shows `reu: none`), original stage-2 kernel, 8 boots on the physical 1541 with the stock KERNAL host and a clean bus: **1 pass in 8**, the same rate as with the REU on (3 in 8, 5 in 20 across series). The REU probe and the REU hardware are cleared.
- **Hammering one block:** 512 consecutive stock-environment reads of track 16 sector 1 (the `/bin` directory block that three of five recorded stalls died on): no stall. The block is just one of the most-read in a boot.
- **Illegal opcodes** (`experiments/illegal-ops` from the `reu-cache` branch, requested by the cache session): loaded with `runners:run_prg` on the C64 Ultimate, firmware 1.1.0: `ILLEGAL OPS: PASS`, 0 failures of 21 checks (LAX, SAX, DCP, ISC, SLO, RLA, SRE, RRA, ANC, ALR, ARR in binary mode, SBX, `$EB`, and the NOP forms). The kernel may use those on this machine. Not checked: the unstable ones (ANE, LXA, SHA, SHX, SHY, TAS, LAS), which the test leaves out on purpose, and any real 6510.

### 2026-11-01, more negatives on the physical-1541 stall, and a recommendation to park it (hardware session)

All on the physical 1541 as device 8, clean bus, stock KERNAL host, the original stage-2 kernel by DMA unless stated; baseline is about 1 pass in 4 (5 in 20 across series; individual series of 8 range from 1 to 3 passes).

| Change | Passes |
|---|---|
| the 1581's short IEC cable, plugged into the 1541's other IEC socket | 1 of 8 |
| upstream kernel with its IRQ vector pointed at the ROM's own handler (`$EA31`) | 2 of 8 |
| `Command Interface` disabled in the Ultimate (UCI registers off) | 1 of 8 |
| `RAM Expansion Unit` disabled (earlier entry) | 1 of 8 |

- **Drive RAM** (`experiments/iec-stall/drvram.s`): 25 passes of 8 patterns over the drive's free buffer RAM `$0300-$06FF` through `M-W`/`M-R` (about 200 KB written and read back, about 6,400 write commands): 0 mismatches.
- **State at a stall** (`envdump.py`): a stalled upstream kernel against a stock BASIC machine, every register that a read cannot disturb: the CPU port, the CIA data-direction and control registers, the VIC mode and enable registers and the SID are identical. What differs is cosmetic (character set, colours), the interrupt vectors, the KERNAL's IEC bookkeeping (consistent with "reading from device 8 in the bit loop") and the running timer counters. Upstream never touches the CIA1 timers.
- The upstream interrupt handler is the ROM's plus Breadbin's own work (cursor, sleeper scan, Ctrl-C check, scheduler tick); replacing it with the ROM's gave the same rate, and a deliberately slow handler (5 ms per tick) in the stock environment did not stall either.
- **Everything the stock environment can vary has now passed 1,600+ full block reads on this drive without a single stall:** BASIC and machine code, sequential, random and spread tracks, CR or EOI-only commands, a hostile IRQ handler, 512 reads of one block. Every Breadbin kernel, including the pre-fork upstream one, stalls at about 3 boots in 4.

**Recommendation: park the root-cause hunt.** It is a rathole by the usual test: more than 130 boots across about 30 conditions, each eliminating a hypothesis and none localising the cause, the problem appears with code we did not write, and the cost is mostly wall time on a machine that other work needs. What it costs the product is limited: the Recommended tier (UCI) and the Expanded tier (the REU cache) do not depend on repeated bus reads; Classic on a real 1541 does, and is the exposure. Reopen if any of these happens: (1) a second physical 1541 or another C64 shows the stall or does not (the cheapest high-value datum there is); (2) Classic reliability on real drives becomes a ship criterion; (3) the fast-loader work (M0-8) needs the bus understood; (4) the stall appears on the emulated drive or in a UCI-era design.

**One last piece of work worth doing before parking, because it turns the finding into product value whatever the cause:** in a stall the drive is waiting for us (CLK held low, in its talker loop, where per the 1541 DOS source only ATN ends the wait). Make the stage-2 driver time out at every bus wait, assert ATN (UNTALK) to release the drive, and retry the block. That converts a hang into a retry. It needs two things to be checked on hardware first: that ATN really releases a stalled drive, and that a stall never completes silently with wrong bytes (all recorded stalls ended in a timeout, and 1,600+ full-speed reads showed none; with the host DMA polling a corrupted transfer was seen on stage 1 and 2 alike, which is a different mechanism).

### 2026-11-01, UCI as measured (hardware session; answers WP1 and the seven items from the breadbin-next session)

C64 Ultimate, firmware 1.1.0, Command Interface enabled. Tool: `experiments/iec-stall/uci.s` + `uci.py` (a script interpreter on the C64 side polling the registers, timed with CIA2 timers A and B cascaded: 1 us resolution). The DOS target identifies as `ULTIMATE-II DOS V1.2`. Test file: 32,768 bytes in `/Temp` (a RAM disk), created through the interface itself.

| What | Measured |
|---|---|
| IDENTIFY | 2.4 ms |
| ECHO / GET PATH / GET TIME | 1.4 ms / 0.8 ms / 2.8 ms |
| OPEN (read) | 4.3 to 4.8 ms (10 samples) |
| FILE INFO | 4.7 to 5.1 ms |
| SEEK | 0.8 ms |
| CLOSE | 0.8 to 0.9 ms |
| CREATE file (open for write, create) | 54 ms |
| WRITE 32 KB in 64 requests of 512 bytes | 1.53 s, **21 KB/s** |
| **READ 32 KB** in requests of 256 / 512 / 4,096 / 32,768 bytes | **15.7 / 16.1 / 16.2 / 16.2 KB/s** (2.03 to 2.08 s) |
| **LOAD REU** of the 32 KB file (needs the file open first) | **6.2 ms, about 5 MB/s**; reply `$008000 BYTES LOADED TO ...` |

1. **Latency** is in the table. **Throughput** through the data register is about 62 us per byte, flat in the request size: the cost is the byte-wise register read (`LDA $DF1E` loop storing to memory), not the command. A request larger than 512 bytes completes as a chain of `Data More` chunks (one command, 32,768 bytes). Anything that wants more than about 16 KB/s should not read through `$DF1E`: **`LOAD REU` moves a file into the REU on the Ultimate's side at about 5 MB/s**, after which the REU-to-C64 DMA is the only C64 cost. The DMA bit of the control register (`$DF1C` bit 7) was not tried.
2. **Status strings and errors:** open of a missing file `FILE DOESN'T EXIST` (no number); read with no file open `85,NO FILE OPEN`; close with none open `84,NO FILE TO CLOSE`; write to a file opened read-only `ACCESS DENIED`; read past the end of file returns no data and an **empty status**; seeking to or beyond the end of file `00,OK`; `LOAD REU` with no file open `85,NO FILE OPEN`. `FILE STAT` with the absolute path that `OPEN` accepted returned `82,FILE NOT FOUND` (not understood; `FILE INFO` after an open works and returns 22 bytes: size, date, time, extension, attributes, name).
3. **Two files open at once:** a **second open on the same target succeeds** (`00,OK`, re-opens). **Both DOS targets (`$01` and `$02`) can have the same file open at the same time with independent positions**, and a command on one target does not disturb the file open on the other (a read on target 1 continued at byte 16 after a seek on target 2 to byte 100, and target 2 read from byte 100).
4. **Interrupt on completion: not usable as documented.** With the IRQ bit written, the identification register never read `$49` at the moment the data was ready, and after that command the interface did not return to idle: the next command timed out (100 s in my loop). Poll.
5. **Network target (`$03`) is present:** `ULTIMATE-II NETWORK INTERFACE` (34-byte identification, `00,OK`). The control target (`$04`) answers `CONTROL TARGET V1.1`. Not exercised further.
6. **Mounted image write-back: not measured yet** (needs the drive to write and then a look at the file on the Ultimate's side).
7. **Effect of the UCI registers on the 1541 path:** none seen. The physical-1541 stall rate is the same with the Command Interface disabled (1 of 8) as enabled (about 1 in 4).

### 2026-11-01, UCI as measured: CORRECTION to the throughput above, and more (hardware session)

**The 16 KB/s read figure in the entry above was my measuring loop, not the interface** (a `JSR` to a store routine with a wrap check per byte, about 60 cycles; the breadbin-next session spotted this). With a tight loop (`experiments/iec-stall/uci.s` ops 5 and 6) reading a 32 KB file:

| Read loop | Throughput |
|---|---|
| tight loop, `DATA_AV` tested on every byte (`LDA $DF1C / BPL / LDA $DF1E / STA page,Y / INY / BNE`, about 20 cycles) | **44.0 to 44.8 KB/s** (0.73 s), the same for 512-byte, 4,096-byte and 32,768-byte requests |
| tight loop, no status test, 512 bytes per chunk (about 14 cycles) | **61.6 to 63.3 KB/s** (0.52 s); the per-chunk handshake costs about 0.2 ms |

So the interface keeps up with the CPU and the figure to design with is about **44 KB/s with a safe loop, 62 KB/s blind**. The 21 KB/s write figure was measured with the same kind of loop (the command is built byte by byte through a routine) and is probably also loop-bound; not re-measured.

- **`LOAD REU`** (the file must be open for read): 32 KB 6.2 ms; **128 KB 13.7 ms (9.6 MB/s); 512 KB 44.4 ms (11.8 MB/s)**: a few ms of fixed cost plus about 12 to 13 MB/s. Reply text: `$080000 BYTES LOADED TO ...`.
- **Create (open for write, create always, flag `$0A`):** 54.8 to 55.7 ms for a new file, the same for an overwrite; close 1.1 ms. Flag `$0E` (write + create new + create always) answers `FILE EXISTS` for an existing file: use `$0A` to overwrite.
- **Paths:** `CHANGE DIR /Temp` works (7.8 ms); `GET PATH` returns `/Temp/`; `OPEN` accepts an absolute path. **`FILE STAT` (`$08`) answered `82,FILE NOT FOUND` for every name I gave it, absolute or relative, while `OPEN` and `FILE INFO` of the same file work**; use `OPEN` + `FILE INFO` (4.9 ms, 22 bytes: size, date, time, extension, attributes, name) to get a size.
- Not tried: the DMA bit (`$DF1C` bit 7), SAVE REU, writes at higher rates.

### 2026-11-01, ATN frees a stalled drive (hardware session)

`experiments/iec-stall/atnprobe.py`: boot the original stage-2 kernel by DMA on the physical 1541 (clean bus) until it stalls, then point the IRQ vector at a probe in free RAM (the hung kernel keeps taking timer interrupts), which calls the driver's own routines: `UNTALK` under ATN, then `TALK` device 8 secondary 2, then reads the drive's buffer byte by byte. Three stalls, three identical outcomes:

- **Before:** CLK held low by the drive, DATA released (`$DD00 = $87`), `ST = $02`.
- **After `UNTALK` under ATN:** CLK released (DATA reads low, the ATN acknowledge while the bus is in attention).
- **A fresh `TALK` is answered** (`ST = 0`), and the drive sends the **rest of its buffer ending with a proper EOI and no timeout**: 61, 192 and 146 bytes. If it continued from its pointer, as it appears to, it had already sent 195, 64 and 110 bytes of that 256-byte block before the stall: the stall point is spread over the block, not fixed.
- (Display bug in that run, fixed in the tool: the second stall was printed as "256, no EOI" because the probe's flag shared a byte with the first-bytes copy; the counts above are right.)

**So the drive is healthy and recoverable: ATN is all it needs.** A recovery in the driver is: on any receive timeout, send `UNTALK` (ATN), then re-issue the whole `U1` (a fresh block, not the remainder), `TALK`, and read again; the unbounded wait in `bus_acptr`'s `@rdy` becomes a bounded one so a hang can no longer occur. Not yet tried in the driver: how often the retry itself stalls (about 1 in 40 block reads by the earlier rate), and whether a stalled receive can ever complete *silently* with wrong bytes; every recorded stall ended in a timeout.

### 2026-11-01, UCI write throughput re-measured with a tight loop (hardware session)

The 21 KB/s write figure was loop-bound as well. With a tight loop (`uci.s` op 7: the header four bytes, then 512 bytes sent with `LDA page,Y / STA $DF1D / INY / BNE`, about 13 cycles per byte) writing 32 KB, 127 requests of 512 bytes and 125 more: **64.8 to 65.1 KB/s**. `FILE INFO` of the file afterwards reports exactly the bytes sent (129,024 = 252 x 512), so nothing was dropped. Create for write about 56 to 58 ms; close 1.2 ms. So polled **reads reach 44 KB/s (status checked per byte) to 62 KB/s (blind), writes 65 KB/s**; `LOAD REU` is 10 to 12 MB/s.


## Request from the cache session, 2026-10-31

1. (Answered: PASS 21 of 21, see above.) Run `experiments/illegal-ops` once on the C64 Ultimate (README has the build line and what a FAIL means). It decides whether the kernel may use the stable undocumented opcodes. Expected: `ILLEGAL OPS: PASS` (it does under VICE).
2. When the regression bisect is done: the cache A/B on `reu-cache` (`make CACHE=0` against `make CACHE=2`, cold REU each boot, five or more boots each), and one run of the `Cache` behaviours that need hardware: warm boot should show far fewer bus reads. The cache does not fix the root-mount stall; it can only hide it on REU machines.

### 2026-11-01, ATN recovery in the driver: 8 of 8 boots on the physical 1541 (hardware session)

`fix/iec-recover` (commit c2e13ca, on top of the cloud kernel): `bus_acptr`'s ready wait is bounded (about 2 s, three passes of a 256 x 256 loop with interrupts enabled; it sets ST bit 1 like the other timeouts), and `iec_read` (blk.s) stops at the first timeout, sends UNTALK under ATN (`iec_in_end`) and asks for the block again, up to three times in all. Cost +56 bytes of code (13,400 to 13,456); room below $CF00 after merging main is 180 bytes.

Series: the image written onto the physical disk (683 sectors verified; the copy took a little over 25 min, so `mcdup.py` now allows an hour), stock KERNAL host, DMA boot, clean bus, 8 boots: **8 of 8 reached the login prompt, 52 s each** (the unmodified kernel passed about 1 in 4 on the same drive and cable; 5 of 20 across series). Not measured: how often the retry fired in those boots (no counter; the 52 s is a pass without a visible 2 s wait, a boot with one stall plus recovery would show about 54 s), and a block checksum is not available, so a stall that completed with wrong bytes is not excluded by this series, only by the earlier observation that the stalled drive ends the buffer with EOI. Not run: VICE tests, JiffyDOS-ROM subset, the hardware list.

### 2026-11-01, cache A/B on the physical 1541 (hardware session)

Main at the merge of `fix/iec-recover`, built with `make CACHE=0` and `make CACHE=2` (cache on, every boot cold), DMA boot on the physical 1541, stock KERNAL host, clean bus, alternating, 5 boots each: **10 of 10 reached the login prompt, 52 s every time** (no difference between the modes to the second). Expected: a cold cache only adds REU writes next to a boot dominated by bus reads, and the retry path keeps the root mount working. Not measured: a warm boot (`CACHE=1`, second boot, matching build id on the disk), where the number of bus reads should drop; that needs the image written onto the physical disk with the same build, and the bus-read count is not exposed to a DMA boot. Not run: the `Cache` behaviours under VICE (the container suite covers those).

### 2026-11-01, UCI control bit 7 (DMA), as measured (hardware session)

The public documentation (core UCI architecture page) says only: bit 7 of `$DF1C` set when the command is pushed makes the Ultimate "enter DMA mode immediately", ending when the command is done; bit 6 (TRIGGER) does the same once `$FF00` is written. It does not say what DMA mode is for, and no DOS or control target command in the documentation moves data into C64 memory. Measured with `uci.py dmabit` (new op 8 SETPUSH in `uci.s` changes the byte pushed to `$DF1C`): the DOS target commands ECHO, IDENTIFY and FILE STAT pushed with `$81` instead of `$01` behave exactly as with `$01`: same responses and status, same latency (ECHO 912 vs 918 us, IDENTIFY 2.5 ms), no hang, the interface returns to idle and the next plain push works. So the bit is accepted and harmless on the DOS target and gives no faster or different data path; it is not a DMA read of the response queue. Conclusion for the UCI v1 design: leave bit 7 alone and use the polled byte path (read 44 to 62 KB/s, write 65 KB/s) or `LOAD REU` for bulk. Not measured: whether the C64 is actually halted during the command (the timing source in the test is the C64's own clock), and bit 6.

### 2026-11-01, JiffyDOS ROMs under VICE: Boot, Cache, Drives (hardware session)

Main at the merge of `fix/iec-recover` (plus the cache A/B notes), VICE 3.10 (macOS app, windowless recipe in `docs/testing.md`), the JiffyDOS C64 KERNAL and the JiffyDOS 1541-II DOS ROM as the Ultimate holds them (`-kernal`, `-dos1541`, `-dos1541II`, images kept out of the repository), `python3 -m unittest tests.test_system.Boot tests.test_system.Cache tests.test_system.Drives`: **39 tests, all OK, 1,868 s.** That covers the recovery change on the bus driver with the JiffyDOS drive timing. Not run: `Persistence`, `REU`, `Pool` classes, `test_keyboard`, `test_console` (the container suite ran the full set on stock ROMs: 55 green).

### 2026-11-01, UCI v1 assumptions checked on hardware (hardware session)

`uci.py gaps`, `gaps2`, `gaps3` (DOS target, firmware 1.1.0). The "unverified" list in `docs/design/next/uci-v1.md`:

- **(b) DIR attribute at offset 11 of FILE INFO: confirmed.** A FILE INFO / FILE STAT packet is: size (4 bytes LE), date/time (4), then 4 bytes of which the last (offset 11) is the attribute and the first three the extension (`BIN` + `$20` for a file: archive; `$00 $00 $10` for a directory: AM_DIR), then the name from offset 12. Seen: `00040000 615d0f1b 42494e20 676170312e62696e` (1,024-byte file `gap1.bin`) and `00000000 615df41a 00000010 67617064697232` (directory `gapdir2`).
- **(c) DELETE, RENAME and CREATE DIR take absolute names after a CHANGE DIR elsewhere: confirmed.** After `CD /Temp/gapsub` (GET PATH answered `/Temp/gapsub/`), `CREATE DIR /Temp/gapdir2`, `RENAME /Temp/gap1.bin` to `/Temp/gap3.bin`, `DELETE /Temp/gap3.bin`, `DELETE /Temp/gapdir2` and (after `CD /Temp`) `DELETE /Temp/gapsub` (a directory) all answered `00,OK` and acted on the absolute names. Each of these took about 57 to 70 ms.
- **(d) OPEN `$02` (write only, no create, no truncate) does not truncate: confirmed.** A 1,024-byte file opened with `$02`, closed, still reports 1,024 bytes by FILE INFO.
- **(a) DATA_ACC / 512-byte packets: no packet skipped, by count.** Reads of 32 KB in 256, 512, 4,096 and 32,768-byte requests all returned exactly 32,768 bytes with `00,OK` statuses (earlier entries). The content of every packet was not compared (the test discards it); a pattern-file `cat` is still the right check.
- **Surprise, FILE STAT (`$08`) by name answers `82,FILE NOT FOUND` for a file that was just written and closed**, in all four attempts (absolute and relative names, with the current directory at `/Temp/`, `/` and a subdirectory), while the same file opens normally (`$02` read) and FILE INFO of the open file answers correctly; FILE STAT worked for a directory and for the file after it was renamed. Cause not found. Consequence for UCI v1: do not rely on FILE STAT by name to probe a file that was just written; open it and use FILE INFO.
- Create for write (flag `$0A`, overwrite) 56 ms; CREATE DIR 57 to 60 ms; DELETE 59 to 61 ms; RENAME 70 ms; CHANGE DIR 11 to 15 ms; GET PATH 1.2 to 1.7 ms.

### 2026-11-01, image write-back timing (hardware session; `experiments/iec-stall/writeback.py`)

Setup: `build/breadbin.d64` put on `/Temp/wb.d64` by FTP, mounted read/write (`mode=readwrite`, by path) on drive A (bus 9), drive reset, then from BASIC `OPEN 15,9,15`, `OPEN 2,9,2,"#"`, a 15-byte marker printed into the buffer and `U2:2 0 1 1` (the drive answered `00, OK,00,00` by JiffyDOS `@`). The image file was then fetched by FTP every second and compared at track 1 sector 1. **The block did not appear in the file**: not within 45 s of the U2, not after closing channels 2 and 15, and not within 30 s after unmounting the image (`drives/a:remove`). So with this path (REST mount of a Temp file as read/write, FTP read-back) no write-back to the file was observed at any point, including the unmount. The cause is not established: the writes may stay in the emulated drive's memory image, the flush may need a menu action or a drive power cycle, or `/Temp` (the RAM disk) is handled differently; not tested: a file on the SD card, the `unlinked` mode's documented behaviour next to it, `drives/a:reset` after the write, a longer wait. For UCI v1 (image write-back) the safe reading is that nothing guarantees an emulated drive's changes reach the file; do not depend on it.


### 2026-11-01, UCI v1 in the real kernel, first run on the Ultimate (hardware session; `experiments/iec-stall/ucirun.sh`)

Main at the UCI v1 merge, `build/breadbin.d64` in the emulated drive A (bus 9, "DMA Load Mimics ID" set to 9 for the run and restored to 8), DMA boot, login as root, shell commands typed by DMA. **It works the first time**: `mkdir /u`, `mount uci /u` (listed as `uci on /u (uci)`), `ls /u` (`SD Flash Temp`), `ls /u/Temp` (about 50 entries, wrapped at the screen width, one name cut with `?`), `cat /u/Temp/hello.txt` (`hello from the host`). Read and write round trip: a 40,000-byte pattern file copied from the host with `cp` to the RAM disk stops at the c64fs file size limit (`cp: file too large`, 35,840 bytes kept), copied back with `cp /tmp/p /u/Temp/pat2.bin`: the 35,840 bytes on the Ultimate are **byte-identical to the first 35,840 bytes of the original** (`cmp`, checked on the host over FTP), so UCI reads and writes of 70 packets deliver the right content (this settles the content half of bench check (a)). `mkdir`, `cp` into the new directory, `rmdir` of the non-empty directory (`directory not empty`, the firmware's answer is mapped), `rm`, `rmdir` and a final `ls` (`no such file or directory`) all behaved as they should. Not run: `Temp\..` (the kernel refuses backslashes anyway), directory commands next to an open file, timing of `cp` from the shell, `wc -c` (the `wc` here takes no `-c`).

### 2026-11-01, recovery fix after the module loader merge (hardware session)

Main at `0a4dba1` (module loader, SYS_CACHE ops 4 to 6, KSTART `$9600`): image written to the physical 1541 (683 sectors verified), DMA boot, stock KERNAL host, clean bus: **5 of 5 boots reached login (32, 22, 22, 22, 22 s)**, so the retry fix holds with the new code size. Boots are faster than the 52 s measured on the earlier tree (not investigated which change did it; the physical drive here still carries the OEM DOS ROM). The `Boot` class under VICE with the JiffyDOS C64 and 1541-II ROMs on the same tree: 26 tests OK (896 s). Not run: hardware list on this tree (waits for the physical drive to be off or the JiffyDOS drive ROM to be back).

### 2026-11-02, the reassembled 1541 with the JiffyDOS ROM: no stall, with or without the retry (hardware session)

The user swapped the drive's DOS ROM from the OEM part back to the JiffyDOS chip (same chip as originally), reseated the RF shield, resealed the case, put back the original cable (the one exonerated earlier) and added a ferrite clamp at the drive end. Main at `67d0972`, image written to the physical disk (683 sectors verified), DMA boot, stock KERNAL host, clean bus, alternating a kernel with the retry fix and one with the two retry hunks reverted (`git revert` of c2e13ca on the same tree): **6 of 6 boots to login with the fix (32, 22, 22, 22, 22, 22 s) and 6 of 6 without it (22 s each)**. The unfixed kernel used to stall in about 3 of 4 boots on this drive. So with this drive ROM, cable and clamp the stall did not appear in 6 boots of the old code; which of the three changes (the cable swap, the clamp, the re-seating of the ROM and shield) removed it is not known, and with a 25% chance of passing per boot, 6 passes in a row is not much (about 18%) if the old rate still held. Not run: more boots, the combination changes one at a time.

### 2026-11-02, where the 25 minutes of a disk copy go (hardware session; `mcdup.py --variant`)

60 sectors of `mcdup` onto the physical 1541 (JiffyDOS drive ROM, stock KERNAL host, source image in the emulated drive A on bus 9): source read only (`--variant srconly`) 40 s, write without the read-back (`noverify`) 101 s, full copy with the read-back 141 s (polled every 5 s). Per sector: reading the source about 0.67 s, writing to the target about 1.0 s, the read-back verify about 0.67 s, so 2.3 s and 683 sectors take 27 minutes. The three transfers of 256 bytes at stock IEC speed (about 0.4 s each) and the commands and status reads are most of it; the drive's own write job is the rest. A per-phase timer inside the copier did not work: the jiffy clock stops while the serial routines hold interrupts off (it gave 0.8 s a sector where 2.3 s elapsed), CIA1 timer B chained to timer A gave nonsense, and the TOD clock stayed at zero. A drive-side routine that takes whole tracks over a faster protocol and writes them in one rotation would move the bound to the bus speed of whatever protocol is used.

### 2026-11-02, a nibbler (Keymaster dual-drive GCR nibbler) as the copier, in VICE (hardware session)

`keym.d.nibbler.prg` from the Ultimate's SD card runs under VICE 3.10 (true drive emulation, real time): the menu takes keys from the key buffer, `c` and Return start the copy of drive 8 to drive 9, it reports "copy complete" in 49 s. The destination is not a readable disk: with a raw-track (G64) destination, `c1541` finds none of the 683 sectors, the VICE drive says `file not found` on `LOAD"$",8`, and the same happens for a standard CBM DOS source disk (XCOPY), while a freshly formatted G64 reads back fine. The nibbled tracks do contain sync marks like a formatted disk. Not run: the same on the real drive (the user offered to swap media for an emulated-drive-to-1541 test where "did we get a directory" is the check), other nibblers, XCOPY.

### 2026-11-01, kernel module loader and exec, JiffyDOS ROMs and hardware (hardware session)

JiffyDOS C64 and 1541-II ROMs under VICE: Boot + Drives on the CBM-DOS-module tree 30 tests OK; Boot, Drives, Pool, Modules, Persistence on `d991b1a` (exec, `cbm.km`, `uci.km` together) **34 tests OK, 1,662 s**. On the real Ultimate (`ucirun.sh`, emulated drive A on bus 9): `ps` after login shows init, sh, ps; the shell keeps working after `exec /bin/ps` (a child, by design); `mount uci /u` loads the module (`mod ls`: 10 pages, `free` 6 to 9 K used), `ls /u` and `cat` work, `umount /u` frees it (`mod ls` empty, 6 K); with the Command Interface disabled (and restored afterwards) `mount uci /u` answers "no such device or no disk" and nothing is loaded. Not run: the hardware list (the physical drive collides with drive A on bus 8), `Cache` and `REU` classes with JiffyDOS.

### 2026-11-02, the Keymaster nibbler on the real drives: it works (hardware session; `experiments/iec-stall/nibsetup.sh`, `nibtest.py`)

Setup: stock KERNAL, Software IEC off, the emulated drive A at bus 8 with `XCOPY.D64` (read-only), the physical 1541 with a scratch disk, both off, then the nibbler's "change device #" dialog: it renumbers the drive that is switched on first to #9 (the physical 1541, powered on by hand when the prompt "turn on drive to be #9" appeared; the nibbler writes the new number into the drive), then "turn on drive to be #8" (drive A powered on through the REST API), then the copy from #8 to #9 (menu `c`, Return). Observed by the user at the machine: the heads moved at speed, the write activity was fast, the program reported "copy complete" with no error after about 2 to 3 minutes (the 49 s seen under VICE was therefore not the real figure). Checks afterwards: `LOAD"$",9` listed `"x - copy / fatum"  13 prg, 651 blocks free` from the physical drive, and `LOAD"*",9` of that file put exactly the 3,131 bytes of XCOPY's program into memory: **byte-identical to the file in the original image** (13 data blocks, plus the directory and BAM). Not a whole-disk compare (only those blocks were read back), and the disk copied was a standard CBM DOS disk, not our c64fs image, which would additionally prove that nothing depends on the BAM; the whole-disk read-back of the physical drive against the image (a reader, like `mcdup` in reverse) is the missing check. The device number the nibbler wrote lives in the drive's RAM, so a power cycle brings the physical drive back to 8. Config restored afterwards (JiffyDOS KERNAL, Software IEC on, drive A back at bus 9, with `XCOPY.D64` still mounted in it).

### 2026-11-02, the nibbler with no hands: renumber the hardware drive in software (hardware session; `experiments/iec-stall/nibcopy.py`)

The first nibbler run needed the user to power the physical drive off and on for the nibbler's "change device #" dialog. It is not needed: the 1541 keeps its device number in RAM, so with the emulated drive A switched off (`drives/a:off`) the physical drive (wired as 8) is renumbered by a memory write over the command channel, `M-W` to $0077 with the listen address $29 (device 9) and to $0078 with the talk address $49 (`open15,8,15,"m-w"+chr$(119)+chr$(0)+chr$(2)+chr$(41)+chr$(73)`), then drive A is given bus ID 8, the image and power, and the nibbler's default copy (8 to 9) is run. Afterwards `UI` sent to device 9 resets the drive, which reads its switches again and is back at 8; no power cycle. Two traps found on the way: **`runners:run_prg` and `runners:load_prg` both reset the machine, and the reset line takes the renumbered drive back to 8** (the nibbler then says "device not present - drive #9"), so the program is put into memory by DMA (`$0801`, the BASIC pointers at $2D, $2F, $31 and $AE set to the end) and started with `RUN` from the key buffer; and the screen test for "copy complete" must look at row 19 (the copying line is row 16, "press any key" row 22). Run under `tools/with-lock -r ultimate` on the stock KERNAL host with Software IEC off (`nibsetup.sh up IMAGE`, `down` afterwards).

Result with `BBI Copy V6.3 (TOOL).d64` (a different image from the first run) onto the scratch disk: copy complete (the user watched it), the physical drive back at 8 by software, `LOAD"$",8` lists `"bbi-copy6.3" prg 28, 636 blocks free`, and the 28-block program loaded from the physical drive is **byte-identical (6,912 bytes) to the file in the image**. Two runs now: the nibbler gives a working copy in 2 to 3 minutes, against 27 for `mcdup`. Still not run: a c64fs image through it with a whole-disk read-back compare.

Which resets take a software-renumbered 1541 back to device 8, measured with the drive at 9 and drive A off: `machine:reset` does **not** (still 9 afterwards, 8 absent); `machine:reboot` **does** (8 present, 9 absent after about 18 s); `UI` on the command channel does (about 8 s); `runners:run_prg` and `runners:load_prg` do (the failure above). So `nibsetup.sh down`, which reboots to restore the KERNAL and Software IEC, un-renumbers for free; the explicit `UI` in `nibcopy.py` is only needed when nothing reboots afterwards.
