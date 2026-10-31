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
