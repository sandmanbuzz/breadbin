# JiffyDOS 6.01 / S-JiffyDOS 1541 binary comparison

Status: initial byte-level comparison, 2026-11-20. The ROM images themselves are user-supplied test inputs and are **not** stored in this repository.

## Inputs

| Image | Size | SHA-256 |
|---|---:|---|
| `JiffyDOS_6.01-1541-and-1541-II.bin` (Ultimate dump) | 16,384 bytes | `2de4d06b4aa2a1b1129cc641a01cbac7e631de362dbd6fe2129eec7336afad53` |
| `S-JiffyDOS_1541C_v1.bin` (previously supplied) | 32,768 bytes | `5a8d9dc8f44e9e3469587d78bba2eb6dfb54932e37387f1e16a4d938fbe06974` |

## Binary relationship

The S-JiffyDOS image's upper 16 KiB (`$C000-$FFFF`, file offsets `$4000-$7FFF`) is a close derivative of the supplied JiffyDOS 6.01 image:

- 15,261 / 16,384 bytes identical (93.1458%).
- 1,123 differing bytes in 121 contiguous difference runs.
- The S-JiffyDOS image's lower 16 KiB is the additional `$8000-$BFFF` region.
- This layout agrees with Jochen Adler's instructions: SJD41 uses `$8000-$FFFF` on 1541C and 1541-II; the 1541C/1541-II build is the same target family.

This is strong evidence that the Ultimate's JiffyDOS image is the correct base family for reproducing the 1541C/1541-II S-JiffyDOS layout. It is not yet proof that every changed byte is a direct patch against this exact dump; the SJD image may have been generated from a closely related JD build.

## Notable changes in the existing SJD image

- NMI vector remains `$FF01`.
- RESET vector remains `$EAA0`.
- IRQ vector changes from `$FE67` (JD) to `$FF67` (SJD).
- The SJD image populates the formerly unused `$C000`-area of the JD image with code, and adds a full extension bank at `$8000-$BFFF`.
- Major changed ranges in the `$C000-$FFFF` bank include:
  - `$C010-$C0AD`
  - `$DCBB-$DCD8`
  - `$E5B7-$E5C2`
  - `$E781-$E7A1`
  - `$E91D-$E998`
  - `$EAA2-$EB29` (includes the reset path)
  - `$F15C-$F194`
  - `$FB0F-$FC38`
  - `$FF60-$FF78` (includes the new IRQ entry)
- The new bank contains substantial code and data. Long zero-filled spans include `$94C1-$9C1F` (1,887 bytes), `$87C8-$88FF` (312 bytes), and `$B880-$BA00` (385 bytes). These are *candidate holes only*: do not treat them as free until all references, bank mapping, and execution paths have been checked.

## What the author's instructions establish

Jochen Adler's SJD41 instructions describe S-JiffyDOS as a patch to CMD JiffyDOS 1541. They explicitly say:

- SJD41 uses the original JD IEC bus routines.
- It works with JiffyDOS computers and compatible speeders; SJD64 is not required.
- SJD41 and SJD64 are independent.
- The 1541C and 1541-II use the same generated build.
- The extension occupies `$8000-$FFFF` on 1541C and 1541-II.
- The patch-generation programs read an existing JD41 ROM and generate intermediate and final EPROM images.

Source: Jochen Adler, [S-JIFFYDOS 1541 instructions](https://retro-bobbel.de/nlq/ajnsjd41.html), and [his project page](https://retro-bobbel.de/nlq/ajnhome.html).

## Consequence for Breadbin

The existing Breadbin host IEC layer already selects its JiffyDOS byte transport for a device that answers the JiffyDOS probe:

- `iec_ch_open`, `iec_out_begin/byte/end`, and `iec_in_begin/byte/end` remain the host-facing interface.
- The low-level JiffyDOS send/receive implementation is in `src/kernel/iec.s`.
- `src/kernel/blk.s` currently uses DOS `U1`/`U2` commands and data channel 2 for 256-byte sectors.

Therefore, the likely integration boundary is **drive-side only at the transport level**: preserve the existing JiffyDOS IEC protocol and host byte routines; add a drive-side command/service that accepts a block request and returns or consumes sector data through the existing JiffyDOS byte protocol. The block layer may need a new command sequence, but `iec.s` should not need a new wire protocol.

A useful first test is to confirm that the existing Breadbin `U1`/`U2` sector path is already taking the JiffyDOS byte path with this exact ROM. If it is, that establishes the transport compatibility baseline before any ROM extension is added.

## Licensing / artifact handling

The author's instructions explicitly warn that generated SJD images contain CMD JiffyDOS routines and must not be distributed. Keep both supplied ROM images and any combined/modified ROM images out of the repository. Repository work should contain our own extension source, analysis, and a local patch/build tool that operates on a user's own ROM input; do not commit a derived ROM image or the proprietary ROM bytes.

## Next analysis

1. Verify that the supplied JD image is byte-for-byte the base expected by the author's SJD generator, not merely a close family match.
2. Disassemble and annotate the SJD command-dispatch hooks, reset path, IRQ hook, and IEC entry points.
3. Identify safe extension space in `$8000-$BFFF` and any necessary dispatch patch points.
4. Prototype a minimal custom drive command (PING first), using the existing JiffyDOS byte transport; then add sector READ/WRITE.
5. Test the resulting private ROM image in the Ultimate emulator and VICE before considering physical EPROM deployment.
