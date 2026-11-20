# S-JiffyDOS 1541: source evidence and Breadbin implications

Status: reverse-engineering note based on Jochen Adler's SJD41 instructions and the user's supplied 1541 ROM images. The separately supplied ajnsjd64.d64 is the SJD64/C64 generator disk, not the SJD41/drive generator disk.

## Product distinction

Jochen Adler publishes two independent products:

- SJD64: a C64 KERNAL patch for JiffyDOS C64 v6.01.
- SJD41: a 1541 DOS ROM patch for JiffyDOS 1541.

The author explicitly says SJD64 and SJD41 are independent and can be mixed in any constellation. The uploaded ajnsjd64.d64 belongs to SJD64. Its C2/C3 programs inspect the C64 KERNAL signature at $E4DC and generate C64-side interim files; they are not the SJD41 drive-ROM generator.

## What the SJD41 instructions establish

Jochen Adler's SJD41 instructions (https://retro-bobbel.de/nlq/ajnsjd41.html) state:

- SJD41 is a patch for JiffyDOS 1541 and requires JD41 as its input environment.
- It uses the original JD IEC bus routines, and is intended to work with JiffyDOS computers and speeder cartridges; SJD64 is not required.
- SJD41 adds drive-side fast operations: fast open/load/save, fast scratch and validate, plus GCR-to-HD decoding while reading. Fast save verifies the written blocks.
- The SJD41 image uses $8000-$FFFF on 1541C/1541-II. On the old 1541, it can use $8000-$FFFF if both ROMs are replaced, or $A000-$FFFF when only the upper ROM is replaced.
- The author describes separate SJD41 generator stages and a separate SJD41 D64. The workflow reads JD41 from a floppy and emits interim files, then EP-GEN produces the final EPROM image.
- The author warns that generated files contain original CMD JiffyDOS routines and must not be redistributed.

These facts validate the architectural premise that a drive-side extension can retain the existing JiffyDOS IEC wire protocol. They do not establish a generic sector RPC or prove that every DOS block command is accelerated.

## What Breadbin already does

Breadbin's src/kernel/iec.s has a clean-room JiffyDOS byte transport. It probes the addressed device during TALK/LISTEN and selects JiffyDOS framing for data bytes in that session. The command/ATN phase remains ordinary IEC.

src/kernel/blk.s uses DOS U1/U2 and channel 2 for 256-byte sectors. This already benefits from JiffyDOS byte framing when the drive answers the JiffyDOS probe. It does not yet issue any SJD41-specific operation.

## Consequence for the S-ifier

Do not transplant the SJD64 C2/C3 generator or infer drive-side hooks from that disk. The correct reverse-engineering inputs are:

1. The user's JD 1541 ROM (16 KiB).
2. The user's SJD41 1541C ROM (32 KiB).
3. The actual SJD41 generator disk and SJD41 instructions, especially the stages that create the drive interim files.

The current ROM image composer is only a safe image-layout/patching scaffold. The next meaningful work is to map the SJD41 ROM's changed entry points against the JD ROM and trace the SJD41 generator's drive-specific transformations. Then decide whether Breadbin should:

- reproduce selected SJD41 drive-side optimizations while keeping DOS U1/U2 semantics; or
- add a Breadbin-specific sector command/ABI and hook it into the JD drive command path.

Those are different products. The second is not implied by SJD41's documented features and must be designed explicitly.

## Sources

- Jochen Adler, S-JiffyDOS home page: https://retro-bobbel.de/nlq/ajnhome.html (separates SJD64 and SJD41).
- Jochen Adler, S-JiffyDOS 1541 instructions: https://retro-bobbel.de/nlq/ajnsjd41.html.
- User-supplied JD 1541 ROM and SJD41 1541C ROM: local analysis inputs only; never commit them or generated derivatives.