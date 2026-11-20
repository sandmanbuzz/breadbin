# SJD41 generator disk: first-pass reverse-engineering

Source: user-supplied `ajnsjd41.d64` (35-track D64, 174,848 bytes; SHA-256 `ef4a52bdaa7204ce1188126ad3d25f8cdf28898a1ae1a402a44819e4106d5d61`). This is the S-JiffyDOS 1541 drive-side generator disk, distinct from `ajnsjd64.d64`.

## Disk contents relevant to generation

- `1.JD/E0&CBM/C0-G` — first-stage drive ROM reader / CBM baseline generator (14 blocks).
- `2.CBM/E0-GENERAT` — generates an interim file from `(C)CMD/J/E0-FF` (16 blocks).
- `3.SJD/E0-GENE460` — generates an interim file from `(C)CMD/J/E0-FF` (10 blocks).
- `EP-GEN/41C&2(NEW` — final EPROM generator for 1541C and 1541-II (8 blocks).
- `EP-GEN/41OLD-HIG` and `EP-GEN/41OLD-LOW` — final upper/lower EPROM generators for the old two-ROM 1541 (8 and 7 blocks).
- `S41-PCUS.TXT` and `S41-PCDE.TXT` — PC-side instructions.
- `INSTRUCTION` and `ANLEITUNG` — Commodore-readable instructions.

The US instructions describe six 33-block intermediate files:

- `(C)CMD/J/E0-FF`
- `(C)CMD/C/C0-DF`
- `(C)CMD/C/E0-FF`
- `(C)CMD/SE0-F/...`
- `(C)CMD/S80-9/...`
- `(C)CMD/SA0-B/...`

The first generator reads the installed JD41 ROM from the drive and writes two intermediate files. The CBM and SJD stages generate further intermediate files. The two CMD-named baseline files are copied from the starting disk. The appropriate `EP-GEN/41...` program then consumes these inputs and writes the final EPROM image(s). The instructions explicitly warn that the intermediate and final files contain copyrighted CMD JiffyDOS routines and must not be redistributed.

## First-stage program: exact ROM capture

`1.JD/E0&CBM/C0-G` performs a real drive-memory extraction, not a file copy.

### Drive-side page copier

The program installs this 15-byte helper at drive RAM `$0400` using DOS `M-W`:

```asm
0400  LDX #$00
0402  LDA $8000,X
0405  STA $0500,X
0408  INX
0409  BNE $0402
040B  INC $0404
040E  RTS
```

The operand at `$0404` is the high byte of the source address. Each `M-E $0400` copies one 256-byte page from the currently selected address `$8000-$FF00` into drive RAM `$0500-$05FF`, then increments that source high byte. The loop runs 128 times, with its page counter from 32 through 159 inclusive.

### C64-side transfer routine

A 134-byte routine is installed at C64 address `$C000`. For each page, it:

1. LISTENs to the selected drive and opens command secondary address `$6F`.
2. Sends DOS `M-R $0500,$80`, then reads 128 bytes from drive RAM `$0500-$057F`.
3. Sends DOS `M-R $0580,$80`, then reads 128 bytes from drive RAM `$0580-$05FF`.
4. Stores the received bytes through the zero-page pointer `$FB/$FC`, then UNTALKs.

The BASIC loop sets `$FB/$FC` to `$2000 + page*256` before each call. Therefore the capture is an exact 32 KiB linear copy of the drive's mapped address range `$8000-$FFFF` into C64 RAM `$2000-$9FFF`. The transfer is done in 256-byte pages, with each page moved over IEC as two 128-byte M-R reads.

### Which captured parts become intermediate files

The subsequent BASIC setup selects the upper portions of that capture for the first-stage outputs:

- `(C)CMD/J/E0-FF` corresponds to the captured drive range `$E000-$FFFF`, held at C64 `$8000-$9FFF`.
- `(C)CMD/C/C0-DF` corresponds to drive range `$C000-$DFFF`, held at C64 `$6000-$7FFF`. Before saving, the BASIC program applies byte patches at several offsets within that buffer (including locations around C64 `$6070`, `$607E`, `$6D92`, `$7367`, and `$7CBB`).

The captured `$8000-$BFFF` portion is not emitted by these two first-stage files; the final SJD image obtains its lower two 8 KiB regions from the supplied `S80-9` and `SA0-B` files. This aligns with the final generator's four-bank SJD assembly.

The first-stage program checks the status text `JIFFYDOS 5.0 1541`. The user confirms that the 6.01-labelled drive ROM is byte-identical to the 5.0 drive ROM; this is therefore the expected compatibility signature, not a 5.x-only restriction.

## Second and third stages

`2.CBM/E0-GENERAT` and `3.SJD/E0-GENE460` share a BASIC scaffold:

- Load `(C)CMD/J/E0-FF` to C64 address `$6000` using KERNAL LOAD.
- Install a 138-byte helper at `$C000`.
- Run it, then save the resulting `$6000-$7FFF` region under the output filename.

The output names are respectively `(C)CMD/C/E0-FF` and `(C)CMD/SE0-F/460` (the directory name is truncated by the 16-character CBM filename field). The helper's detailed pointer-walk and patch semantics remain to be annotated. The same machine-code payload appears in both BASIC generators.

## Final EPROM generator: 1541C / 1541-II

`EP-GEN/41C&2(NEW` defines the following input files in its REM header:

0. `(C)CMD/S80-9/***`
1. `(C)CMD/SA0-B/***`
2. `(C)CMD/C/C0-DF**`
3. `(C)CMD/SE0-F/***`
4. `(C)CMD/C/E0-FF**`
5. `(C)CMD/J/E0-FF**`

It makes two passes, each loading four 8 KiB files into C64 memory pages `$20`, `$40`, `$60`, `$80`, then saving 32 KiB from `$2000-$9FFF`. The first output (`.../00`) is assembled from `S80-9`, `SA0-B`, `C/C0-DF`, and `SE0-F`: four consecutive 8 KiB regions forming the 32 KiB SJD image. The second output (`.../80`) is assembled from `C/C0-DF`, `J/E0-FF`, `C/C0-DF` again, and `C/E0-FF`. The repeated common `C/C0-DF` region plus the separate JD and CBM `E0-FF` regions strongly indicates that this second 32 KiB output contains two selectable 16 KiB legacy DOS images (JD and CBM), while the first contains the 32 KiB SJD image. This interpretation fits the three-way ROM selection described in the hardware instructions; confirm the exact EPROM address-pin mapping against the wiring diagram before treating bank numbers as physical switch positions.

The `41OLD-HIG` and `41OLD-LOW` generators are separate outputs for the old 1541's two-ROM configuration. Their input selection differs; do not assume the C/2 concatenation layout applies to them.

## Compatibility caveat

The first-stage program's literal check is `JIFFYDOS 5.0 1541`, while the local binary under analysis has been identified by filename/hash as JiffyDOS 6.01. Before claiming the generator can consume that exact local image, compare the embedded version/signature bytes and run the generator's read/patch logic against a controlled copy. The supplied SJD41 image's similarity to the supplied JD image is strong evidence of family relationship, but not a substitute for proving this generator's accepted input.

## Next reverse-engineering work

1. Fully disassemble the first-stage helper at drive `$0400` and the C64-side transfer routine; establish exact source ranges and the 128-page transfer mapping.
2. Annotate the first-stage post-capture patches that produce `(C)CMD/C/C0-DF`.
3. Disassemble the shared 138-byte helper in stages 2 and 3; identify pointer tables, source/destination spans, and transformation differences caused by their inputs.
4. Trace the final generator's exact load/save address ranges and file offsets, then compare generated layout against the supplied SJD41 image.
5. Keep all extracted ROM-derived files and generated images local; commit only clean-room descriptions, tests, and original Breadbin code.