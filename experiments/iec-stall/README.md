# IEC stall on the physical 1541

Stage 2 of the bus driver (`src/kernel/iec.s`, M0-4) works against the Ultimate's emulated 1541
and under VICE, but stalls the root mount on a physical 1541 in most boots. Findings and the
history are in `docs/hardware-notes.md` (2026-10-31 entries). These are the tools.

Setup that matters: only the physical 1541 on the bus (disable Drive A and Software IEC through
the config API for the run and restore them after; a switched-off 1581 that is still attached
changes behavior, keep it off the bus). Hold the machine's state in your head: a run that dies
between `pause` and `resume` leaves the machine paused, and a reset does not un-pause it.

1. Build the images you want to compare and keep each kernel's labels:
   `make && cp build/breadbin.prg old.prg && cp build/kernel.lbl old.lbl` (repeat per variant).
2. `BREADBIN_ULTIMATE=host python3 dmaboot.py old.prg` (about 45 s on a pass, 170 s on a stall).
   Alternate variants, at least five of each; one run says nothing (the old kernel passes about
   one boot in five).
3. `python3 decode.py old.prg` for the state at each stall.
4. `stockload.py` is the control: the ROM's own receive code, same drive, same file.

Never poll the screen with long DMA reads while a disk transfer is running.

## Running a hardware job (for any session)

The Ultimate and the physical 1541 are shared. Everything below assumes `BREADBIN_ULTIMATE=host` (the address is private: never write it into the repository).

1. **Take the lock for the whole job**: `tools/with-lock -r ultimate -- <command>`. A second session waits. Scripts that change the configuration must restore it on exit (`trap`), and you check `GET /v1/drives` and the Kernal ROM afterwards. Normal state: JiffyDOS KERNAL (`JiffyDOS-C64.bin`), Software IEC on, drive A a 1541 with the JiffyDOS 1541-II ROM on bus 9, the physical 1541 on bus 8, turbo off. A changed `Kernal ROM` needs `machine:reboot`, a reset does not apply it; a run that dies between `pause` and `resume` leaves the machine paused (call `resume`).
2. **Never read the screen with a long DMA while a disk transfer runs** (a CPU halt mid-handshake corrupts it): wait, or read a few bytes.
3. **Booting Breadbin on the Ultimate without touching the keyboard**: `ucirun.sh 'cmd' ...` boots `build/breadbin.d64` from drive A on bus 9 (it sets "DMA Load Mimics ID" to 9 and restores it) and types shell commands. Add `plainboot.py IMAGE.prg` (stock KERNAL, Software IEC off, root on the physical drive) for boot series on the 1541; `bisect.sh COMMIT N` builds a commit, writes its image onto the physical disk and boots it N times.
4. **Putting a disk image on the physical 1541** (the physical disk is overwritten): `nibsetup.sh up IMAGE_PATH_ON_THE_ULTIMATE`, `nibcopy.py IMAGE_PATH` with `NIBBLER=` the local PRG path (see "Nibbler, canonical method" below; about 2 to 3 minutes; the physical drive is renumbered to 9 in software and back), `nibsetup.sh down`. `mcdup.py --dst 8` is the slow, verifying alternative (27 minutes for 683 sectors, read-back compare of every sector); `--base IMAGE` copies only the sectors that differ from an image already on the disk.
5. **Pitfalls measured**: `runners:run_prg` and `load_prg` reset the machine and the bus (a renumbered drive returns to 8); `machine:reset` leaves a renumbered drive alone, `machine:reboot` and `UI` bring it back; the Ultimate has no key injection (type by writing PETSCII into `$0277` and `$C6`, as `bench_basic.py` does); a switched-off 1581 left on the bus changes behavior. Everything found so far is in `docs/hardware-notes.md`.

## Nibbler, canonical method

The copy path uses one nibbler and one way to start it.

- **Program.** `keym.d.nibbler.prg` (3,242 bytes, load `$0801`, BASIC stub `SYS 2076`; sha256 `30808e1f…`). Its own screen text reads "KEYMASTER / DUAL DRIVE GCR NIBBLER V1.0 / BY JIM DREW / PRESENT BY CATMAKER 1986": the Keymaster dual-drive nibbler, version 1.0. It is a commercial 1980s program and is **not in git**: keep it untracked (`git status` shows it as `??`); never `git add` it. Its source is the Ultimate's SD card, `/SD/utils/disk/` (copy it over FTP to a local path; do not upload it anywhere).
- **Start it: DMA-poke and RUN.** `nibcopy.py` writes the PRG into `$0801` by DMA (`writemem`), sets the BASIC end pointers (`$2D`, `$2F`, `$31`, `$AE`), then types `run` on the keyboard buffer. Do not use `u.run_prg` or `u.load_prg` for this: both reset the machine, and the reset takes the renumbered physical drive back to device 8 mid-copy. `nibtest.py load` uses `run_prg` and is for looking at the menu only.
- **Keys.** The Ultimate has no key injection: `feed()` writes PETSCII to `$0277` and `$C6` (`bench_basic.py`). Menu choice `c`, then Return.
- **Commands** (all under the lock, with `BREADBIN_ULTIMATE` set; the address stays out of the repo):

  ```sh
  tools/with-lock -r ultimate -- sh -c '
    cd experiments/iec-stall &&
    BREADBIN_ULTIMATE=host ./nibsetup.sh up IMAGE_ON_THE_ULTIMATE &&
    BREADBIN_ULTIMATE=host NIBBLER=/path/local/keym.d.nibbler.prg python3 nibcopy.py IMAGE_ON_THE_ULTIMATE ;
    BREADBIN_ULTIMATE=host ./nibsetup.sh down'
  ```

  `nibcopy.py` opens `NIBBLER` as a **local** file (`open(os.environ["NIBBLER"])`), not a path on the Ultimate. Earlier attempts failed when given an Ultimate path. Run `nibsetup.sh down` even if the copy fails (the `;` above does that); `nibsetup.sh` does not trap on its own.
- **Not yet verified on the current scripts:** the last end-to-end `nibcopy.py` run stopped at opening `NIBBLER` (path, fixed in the script since). The DMA-poke start was not rerun after that fix. A full copy with read-back is still to do under the owner's write gate.

## Writing an image to the physical 1541: one command

`write-physical.sh IMAGE.d64` is the supported way to put a disk image on the physical 1541 (device 8). Run it from the repository root or from `experiments/iec-stall`. It takes the `ultimate` lock itself.

```sh
BREADBIN_ULTIMATE=HOST NIBBLER=/local/keym.d.nibbler.prg experiments/iec-stall/write-physical.sh build/breadbin.d64
```

- **Duration:** about 50 s on the bench (the owner's observation). The copy waits up to 1,500 s before it reports a timeout, so a long wait is not by itself a failure.
- **What it does:** preflight (the nibbler's sha256 `30808e1f…`, the image's sha256 `IMAGE_SHA`, default `f6efbf78…` = main 9cab610, and that the Ultimate answers), then under the lock: `nibsetup.sh up` (Software IEC off, stock KERNAL, the image uploaded read-only into drive A on bus 9), `nibcopy.py` (drive A to bus 8, the physical drive renumbered to 9, the copy, then back to 8), and `nibsetup.sh down` in an EXIT trap, so the config comes back even when the copy fails.
- **Exit status:** 0 written and restored; 1 refused in preflight, nothing changed on the Ultimate; 2 the copy or the config step failed, and the trap restored the config. Read the last lines printed.
- **Checks already run offline** (this session, no Ultimate): refused with no `BREADBIN_ULTIMATE`; refused on a wrong image hash; refused on a wrong nibbler hash; refused when the Ultimate does not answer, with the lock taken and released and no config change.
- **Not checked by this tool:** the physical disk's contents. Check it with the directory listing the copy prints.

### Why the physical disk says "0 blocks free"

That is correct, not a copy error. Two different counters:

- `mkimage` marks every block **used** in the CBM BAM (track 18, `tools/mkimage.py:116-120`) so the drive's DOS never writes over c64fs; `LOAD"$",8` on the physical drive reads that BAM and says `0 blocks free`. The source image's BAM is the same (all zeros), so the copy matches it.
- `mkimage` reports `283 blocks free` from the c64fs bitmap (`FS(img).free_blocks()`, `tools/mkimage.py:424`). That is the number that matters to Breadbin.

The directory entry `BREADBIN PRG 59 blocks` is the same on the source image and the physical disk. Compare the two counters, never one against the other: a CBM `blocks free` of 0 is the design (`docs/filesystem.md`, the CBM BAM paragraph).

### Known gaps

- The write is one way: the script does not read the physical disk back and compare sectors. `mcdup.py --dst 8 --base IMAGE` does that, slowly (about 27 minutes), when a sector-exact check is needed.
- `nibsetup.sh up` uploads a local image now (it used to pass a local path to the Ultimate, which does not exist there). Changed in this commit; not exercised on hardware yet.
