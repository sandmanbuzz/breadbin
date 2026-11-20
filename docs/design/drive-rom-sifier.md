# Breadbin drive-ROM S-ifier

Status: first build-tool slice; **not yet a runnable Breadbin drive ROM**.

This work targets the 1541C/1541-II 32 KiB ROM layout demonstrated by the
supplied S-JiffyDOS 1541C image:

| CPU address | Image offset | Purpose |
|---|---:|---|
| $8000-$BFFF | $0000-$3FFF | Added extension bank |
| $C000-$FFFF | $4000-$7FFF | JiffyDOS-derived bank |

The supplied JiffyDOS 6.01 dump is 16 KiB and has SHA-256
`2de4d06b4aa2a1b1129cc641a01cbac7e631de362dbd6fe2129eec7336afad53`.
The supplied S-JiffyDOS image is a close derivative: 15,261 of 16,384 bytes
in its upper bank match. This supports the layout and base-family choice, but
does not prove that the SJD generator consumes this exact dump byte-for-byte.

## What exists now

`tools/sjd41/rom_image.py` is a conservative image composer:

- `inspect` reports size, SHA-256 and the NMI/RESET/IRQ vectors.
- `build` accepts a user-supplied 16 KiB JD ROM, our 16 KiB extension bank,
  and a JSON patch manifest.
- It requires the base SHA-256 to match the manifest exactly.
- Every patch is guarded by expected original bytes; overlapping patches,
  out-of-bank addresses, length mismatches and stale input bytes are rejected.
- It emits the 32 KiB image as extension bank followed by the patched JD bank.
- No CMD/JiffyDOS/S-JiffyDOS ROM bytes or generated derivative are checked in.

The example manifest is deliberately empty. It is a safe image-layout smoke
test, **not** a functional S-ifier: a real extension and proven hook patches
must be supplied before the result can boot.

Example:

```sh
python3 tools/sjd41/rom_image.py inspect JiffyDOS_6.01-1541-and-1541-II.bin

python3 tools/sjd41/rom_image.py build \
  --base JiffyDOS_6.01-1541-and-1541-II.bin \
  --extension breadbin-extension.bin \
  --manifest tools/sjd41/manifest.jd601.example.json \
  --output breadbin-jd601-1541c-private.bin
```

Keep all input ROMs, extension+ROM output images and intermediate combined
images local. The upstream S-JiffyDOS instructions explicitly warn that
generated images contain CMD JiffyDOS routines and must not be redistributed.

## Reverse-engineering evidence: S-JiffyDOS generator disk

The user-supplied `ajnsjd64.d64` contains the C64-side generator programs
`C2-GEN/JD` and `C3-GEN/SJD/US`, plus PC and C64 instructions.

The US PC instructions establish this generation sequence:

1. Run the appropriate C64-side generator(s) with JiffyDOS 6.01 active in
   the C64's EPROM.
2. The generator writes intermediate files to a prepared destination disk.
3. Run the matching `EPROM-GEN` program to combine the intermediate files
   into the final EPROM image.
4. The author explicitly says the generated files contain original CMD
   JiffyDOS routines and must not be given to others.

The C3 BASIC program checks for the exact KERNAL signature
`JIFFYDOS V6.01` at C64 address $E4DC, loads a 138-byte machine-code routine
at $C000, executes it, initializes device 8, then saves the memory range
$4000-$5FFF under a generated filename. The machine-code routine visibly
copies $E000-$FFFF into $4000-$5FFF. It then scans from $0800 and performs
a further pointer-driven copy; that second phase is not yet fully annotated
and must not be described as a proven patch algorithm.

The C2/JD program uses the same BASIC scaffold but a shorter 29-byte routine.
The exact role of its shorter transformation, and the precise data contracts
between the C1-C4 and EPROM-GEN stages, remain to be disassembled and traced.

## Next implementation gates

1. Fully annotate the C2 and C3 machine code, including the scan and copy
   loop, pointer sources, destination range, and exact intermediate-file
   contents.
2. Extract and understand the C1-C4 / EPROM-GEN file naming and concatenation
   rules from the generator programs and PC instructions.
3. Disassemble the exact JD and SJD ROMs around the changed dispatch, reset,
   IRQ and DOS entry points; identify safe extension placement and all hook
   callers.
4. Define our own extension ABI and implement a harmless PING path first.
5. Add only byte-verified hook patches to a manifest for this exact JD dump.
6. Assemble the extension and test the private image in VICE, then the C64
   Ultimate emulated drive, before physical hardware.

The intended transport boundary remains unchanged: preserve JiffyDOS's
existing IEC bus routines and Breadbin's host-side byte transport. The
extension adds Breadbin block semantics on the drive side; it must not invent
a second host transport or assume that S-JiffyDOS already provides a generic
block RPC.
