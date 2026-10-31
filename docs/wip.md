# Work in progress

Rewritten 2026-10-31. For whoever picks this up next, in particular the session running next to the Ultimate. Read `CLAUDE.md` first (build, tests, test policy, standing decisions), then this. `docs/roadmap.md` has the full story list and the memory and disk-speed analyses.

## Two sessions, one repository

| Session | Where | Does |
|---|---|---|
| **Cloud session** | a cloud container, branch `claude/brave-wright-km3nrm` | The kernel: the KERNAL takeover (M0), memory layout, the filesystem interface, the UCI kernel backend. Tests under VICE. Cannot reach the Ultimate or the drives. |
| **Hardware session** | next to the C64 Ultimate and the real 1541 | Everything that needs the machine: verification, and the experiments below. It owns its own branch (`hw-bench`) and rebases it on the cloud branch. |

The hardware session is not a remote hand. It has the codebase and the machine, and it should use judgement: if an experiment shows the plan is wrong, say so in `docs/hardware-notes.md` and say what you would do instead.

## Snapshot

- **Done:** M0-1 to M0-5. The kernel owns the interrupt entry, keyboard, screen, serial bus and channels; the KERNAL ROM is not used; the BSS moved into the old ROM region, leaving 6,079 bytes of room for code (`make size`). Stage 2 of the bus driver is verified under VICE with stock and JiffyDOS ROMs, **and on your hardware** (reported: boot 75.5 s against 46.5 s for the ROM bus, since the ROM's JiffyDOS fast protocol is no longer used).
- **Next on the kernel side (cloud):** the test and size consolidation, then the filesystem interface (S6) and the UCI kernel backend (S10, S11). Disk speed is decided in `docs/roadmap.md` ("Disk speed"): the Ultimate file backend is the principal fast path; an REU block cache is the quick win; JiffyDOS and drive-side loaders are deferred.
- **Not yet done on hardware:** the physical 1541 as the boot drive, `format`, and the full M0-5 build.

## Rules of the road

- Own branch `hw-bench`, rebased on `claude/brave-wright-km3nrm` before each work package. Push it to origin.
- **You own:** `tools/ultimate*.py`, `tools/fake_ultimate.py` and its tests, any new command under `src/bin/` (the Makefile builds every `src/bin/*.s` automatically), anything under `experiments/`, and `docs/hardware-notes.md`.
- **Do not edit** `src/kernel/`, `src/lib/`, `include/breadbin.inc`, `kernel.cfg` or `k.inc`: the cloud session is working there. If you need a kernel change or a library routine, describe it in `docs/hardware-notes.md` (what, why, the smallest version) and carry on with a workaround.
- Test policy as in `CLAUDE.md`: targeted tests per package; the cloud session runs the full suite at milestones.
- ROM images and firmware stay out of the repository. The JiffyDOS images on your machine are for experiments only.
- Credit sources in the code: `fastboot1541` is by Michael Steil and asks for credit.
- Report in `docs/hardware-notes.md`: date, what you ran (a command someone else can repeat), what happened, and the commit.

## Work packages, in priority order

**WP0. Verify the current build (short).** Pull the cloud branch, `make`, boot it, and run the targeted tests from the "hardware list" in `docs/hardware-notes.md` (boot, `test_02`, `test_13`, `test_07`, `test_10`, `test_console`). The change to verify is M0-5: the kernel's tables moved to `$E000`. Record boot time. If the physical 1541 is available as device 8, repeat on it.

**WP1. A UCI explorer, as a Breadbin command.** *The most valuable package.* Write `src/bin/uci.s`: a command that talks to the Ultimate Command Interface directly (registers `$DF1B–$DF1F`; programs may touch hardware, there is no memory protection). Start with `uci id` (read `$DF1D`, expect `$C9`; send the DOS target's identify command and print the reply), then `uci ls [path]`, `uci cat file`, `uci seek`, `uci time`, and whatever else the DOS target offers (`uci/ultimate_dos_target.rst` in the documentation repository). Measure real behavior against the documentation: queue and chunk sizes, status strings, error cases, how long open, read and seek take, and the sustained read throughput on a 32 KB file in 512-byte chunks. This is the prototype for the UCI file backend (S10, S11); what you learn here is what the kernel backend is designed from, so write down every surprise. Deliverable: the command, plus a "UCI as measured" section in `docs/hardware-notes.md`. Constraint: UCI requires the "Command Interface" menu option on (it is, per your notes) and interrupts do not matter to it (polled), but keep one transaction in flight at a time.

**WP2. Fast-read feasibility (groundwork for M0-8).** Under `experiments/fastread/`, build `mist64/fastboot1541` (read its README and `pagetable.com/?p=568`), run it from the Ultimate, and find out: does it work on the emulated 1541 with the JiffyDOS ROM; with a stock ROM (the Ultimate can load a drive ROM by API, `drives/a:load_rom`; `tools/setup-vice-roms.sh` fetches one); on the physical 1541? What throughput does it reach, and does it need the screen blanked or interrupts off? Then a small variant that reads an arbitrary list of sectors, to see whether the technique serves the kernel's block reads. Deliverable: a table of drive and ROM combinations that work, speeds, and constraints, in `docs/hardware-notes.md`. Do not touch the kernel.

**WP3. Pixel-exact frames.** Start the video stream (`streams/video:start`), receive it on the test host, and write `tools/ultimate_video.py` and `UltimateTarget.screenshot(path)` (PNG via the standard library only). Read the stream format from `data_streams.rst`. Answers H9. Useful for console tests that check colour and reverse video exactly. Deliverable: the tool, a test that skips without hardware, and the format notes.

**WP4. Turbo, measured.** Through the configuration API enable the Turbo Mode setting that exposes `$D031`, then write a small command `turbo` that reads and sets the speed index and report `$D031` presence. Measure: does CPU speed change as documented (time a fixed loop against the jiffy clock)? What happens to the IEC bus driver at higher speed (expect it to break; note where), and to REU DMA and bad lines? Deliverable: the command and the measurements. No kernel changes: the kernel will switch turbo off around bus use once these are known.

When a package is done, push, and say so in `docs/hardware-notes.md`. If two or more are done and nothing new has come in, rebase and start the next one. If you are blocked on a kernel change, write it down and move on.

**WP5. Loader POC on the bench (queued, do not start until the IEC quirks of WP0 are explained).** Only after you are confident about the bus behaviour (phantom ATN responders, drive timing). Take Krill's Loader v194 release archive (BSD-style licence, credit "Loader by Krill"; a link is in `docs/design/fast-io.md`) and run its prebuilt `loadertest-c64.d64` unmodified from the Ultimate: (a) drive A with a stock 1541 ROM, (b) drive A with the JiffyDOS ROM, (c) on the physical 1541 with the JiffyDOS ROM, (d) with a second drive on the bus. Record: does it run; the kB/s lines it prints; whether the screen must be blank; any hang or error. The same experiment under VICE is already done (`docs/design/fast-io.md`, section 16): 6.0 to 6.4 kB/s raw on both ROM sets. A negative result on hardware is as useful as a positive one; write down *where* it fails. Do not touch the kernel for this.
