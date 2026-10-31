# Stable undocumented 6510 opcodes: do they behave on this CPU?

`illegal.s` is a standalone C64 program (no Breadbin). For each stable opcode it sets A, X,
carry and a zero-page byte, runs one instruction, then compares A, X, the byte and the
N V Z C flags with values worked out by hand: LAX, SAX, DCP, ISC, SLO, RLA, SRE, RRA, ANC,
ALR, ARR (binary mode), SBX, `$EB` (SBC), and the NOP forms (implied, immediate, zero page,
absolute). 21 checks. Not covered, on purpose: the unstable ones (ANE/XAA, LXA, SHA, SHX,
SHY, TAS, LAS), whose results depend on the chip.

Result: the screen shows `ILLEGAL OPS: PASS`, or `FAIL` and the ids of the failing checks;
`$C000` holds the number of failures and `$C001..` their ids.

    ca65 -o illegal.o illegal.s && ld65 -C illegal.cfg -o illegal.prg illegal.o
    python3 run_vice.py        # under VICE (uses tools/vicetest.py): PASS 2026-10-31

To run on the Ultimate: load `illegal.prg` (for instance with `tools/ultimate.py`'s
`runners:run_prg`, or by DMA and `RUN`), then read the screen or `$C000`. Wanted: the
result on the C64 Ultimate, per core / firmware, and on any real 6510 you have. A FAIL
names the opcode family: it decides whether the kernel may use that opcode.
