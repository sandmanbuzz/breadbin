# Hardware notes

Findings from running Breadbin on real hardware. Append; do not rewrite history. Each entry: date, what was run (a command someone else can repeat), what happened, and the commit it ran against. Unknowns the cloud session is relying on are listed below with an empty result; fill them in.

## Setup

| Item | Value |
|---|---|
| Ultimate model and firmware (`GET /v1/info`) | |
| REST password set? Reachable from where? | |
| Drive A (device 8): type and ROM | |
| Physical drives on the IEC bus, and their device numbers | |
| REU: configured size | |
| "Command Interface" enabled in the Ultimate's menu? | |
| "Turbo Mode" setting (Off, Manual, U64 Turbo Registers, Turbo Enable Bit)? | |
| Where the tests run from (machine, OS, Python version) | |

## Open questions

| # | Question | Why it matters | Result |
|---|---|---|---|
| H1 | Are POST attachments multipart or raw? Which `mount` and `run_prg` forms work? | `tools/ultimate.py` guesses multipart. | |
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
