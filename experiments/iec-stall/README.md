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
4. **Putting a disk image on the physical 1541** (the physical disk is overwritten): `nibsetup.sh up IMAGE_PATH_ON_THE_ULTIMATE`, `nibcopy.py IMAGE_PATH` (the Keymaster nibbler from the Ultimate's SD card, `NIBBLER=` the PRG file; about 2 to 3 minutes; the physical drive is renumbered to 9 in software and back), `nibsetup.sh down`. `mcdup.py --dst 8` is the slow, verifying alternative (27 minutes for 683 sectors, read-back compare of every sector); `--base IMAGE` copies only the sectors that differ from an image already on the disk.
5. **Pitfalls measured**: `runners:run_prg` and `load_prg` reset the machine and the bus (a renumbered drive returns to 8); `machine:reset` leaves a renumbered drive alone, `machine:reboot` and `UI` bring it back; the Ultimate has no key injection (type by writing PETSCII into `$0277` and `$C6`, as `bench_basic.py` does); a switched-off 1581 left on the bus changes behavior. Everything found so far is in `docs/hardware-notes.md`.
