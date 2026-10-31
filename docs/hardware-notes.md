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
