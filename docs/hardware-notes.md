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
| H2 | How long must a key tap last for our 60 Hz scan to see it? What is the smallest `delay` in `xkey`/`xtype` that never drops a key? | `xtype` defaults to 0.15 s per key. | |
| H3 | Does a held key (`xdown`) repeat as in VICE? | `test_keyboard.test_repeat` | |
| H4 | What does a DMA read of `$0001` return once Breadbin runs: `$35` (the port) or the RAM under it? | `test_00_kernal_is_shadowed` asserts `$35`. | |
| H5 | Time from mount and reset to the shell prompt. | Sizes the value of the fast boot (M0-8). | |
| H6 | Does `machine:pause` leave the key buffer update in `keybuf()` atomic? Any visible glitch? | `UltimateTarget.keybuf` relies on it. | |
| H7 | What do DMA reads of `$D031` (turbo) and `$DF1D` (UCI identification, expect `$C9`) return? Can they be read by DMA at all? | Probes for turbo and UCI. They may need to run on the C64 instead. | |
| H8 | Do the VICE-reference tests pass? List each that differs: `test_02`, `test_13`, `test_14`, `test_24`, `test_keyboard`, `test_console`. | The point of the bench. | |
| H9 | Video stream: does `streams/video:start` deliver frames to the test host? Format, port (default 11000), and a way to grab one frame. | A pixel-exact screenshot for the tests. | |
| H10 | With a physical 1541 on the bus, does `mount 9 /mnt` work from Breadbin (it uses the KERNAL IEC routines today)? | Baseline before M0-4 replaces them. | |

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
