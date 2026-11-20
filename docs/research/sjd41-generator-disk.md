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
- `(C)CMD/C/C0-DF` corresponds to drive range `$C000-$DFFF`, held at C64 `$6000-$7FFF`. Before saving, the BASIC program applies byte patches at several offsets within that buffer (including locations around C64 `$6070`, `$609F`, `$6D92`, `$7367`, and `$7CBB`).

The captured `$8000-$BFFF` portion is not emitted by these two first-stage files; the final SJD image obtains its lower two 8 KiB regions from the supplied `S80-9` and `SA0-B` files. This aligns with the final generator's four-bank SJD assembly.

The first-stage program checks the status text `JIFFYDOS 5.0 1541`. The user confirms that the 6.01-labelled drive ROM is byte-identical to the 5.0 drive ROM; this is therefore the expected compatibility signature, not a 5.x-only restriction.

## Second and third stages

`2.CBM/E0-GENERAT` and `3.SJD/E0-GENE460` share a BASIC scaffold:

- Load `(C)CMD/J/E0-FF` to C64 address `$6000` using KERNAL LOAD.
- Install a 138-byte helper at `$C000`.
- Run it, then save the resulting `$6000-$7FFF` region under the output filename.

The output names are respectively `(C)CMD/C/E0-FF` and `(C)CMD/SE0-F/460` (the directory name is truncated by the 16-character CBM filename field). The helper's detailed pointer-walk and patch semantics remain to be annotated. The same machine-code payload appears in both BASIC generators.

## Second/third-stage helper: structural disassembly

The 138-byte 6502 helper embedded in both `2.CBM/E0-GENERAT` and `3.SJD/E0-GENE460` is byte-identical. The two programs therefore run the same transformation engine against different input images; the stage distinction is in the input, not a different algorithm.

The helper at C64 `$C000` has two clearly separable phases:

1. **Bulk copy:** it initializes source pointer `$FD/$FE = $E000` and destination pointer `$FB/$FC = $4000`, then copies 256-byte pages until the source high byte wraps. This is an 8 KiB copy from `$E000-$FFFF` to `$4000-$5FFF`.
2. **Embedded record interpreter:** it scans memory from `$0800` upward for the first three consecutive zero bytes. After that marker, it repeatedly reads a three-byte record header:
   - destination low byte
   - destination high byte
   - payload length

   If all three header bytes are zero, it returns. Otherwise it advances past the header, copies that many payload bytes to the specified destination address, advances the source pointer past the payload, and reads the next record.

In pseudocode, the second phase is:

```text
scan = $0800
while memory[scan..scan+2] != 00 00 00:
    scan += 1
scan += 3

repeat:
    dst = word(memory[scan], memory[scan+1])
    len = memory[scan+2]
    if dst == 0 and len == 0:
        return
    scan += 3
    copy memory[scan .. scan+len-1] to dst
    scan += len
```

This is a small table-driven patch/relocation engine, not a byte-for-byte ROM diff routine. The records carry their own destination and payload, so the same 6502 helper can apply different patch sets to the CBM and SJD variants.

The BASIC scaffold's KERNAL parameters are now decoded:

- It sets `$B9=0` (secondary address), `$BA=8` (device), `A=0` (LOAD), and `X/Y=$6000` (relocated load address). Under the documented C64 KERNAL contract, the input PRG payload is therefore loaded at `$6000`, not at its embedded PRG address.
- After the helper runs, the program saves `$6000-$7FFF` (8 KiB) back to disk. Thus the input buffer and generated output occupy the same C64 address range.
- The helper itself does not write the 6510 processor port `$01`. Under the normal post-reset C64 mapping, reads from `$E000-$FFFF` return KERNAL ROM, even though writes go to underlying RAM.

That leaves a concrete unresolved discrepancy: the helper's first phase reads `$E000-$FFFF`, while the BASIC program relocates the input file to `$6000`, and the helper contains no visible `$01` bank-switch. We need to establish whether some external/earlier environment has banked out the KERNAL, whether another memory-map side effect is in play, or whether this copy is intentionally of the visible KERNAL ROM. Do not silently claim that the first copy is a copy of the loaded JD image.

The exact record destinations and their payloads still need to be extracted from a controlled runtime memory image. Do not yet describe the record stream as a specific set of ROM hooks.

## Embedded patch-record tables: decoded

The 138-byte helper is a generic patch-table interpreter. Its table is not in the BASIC `DATA` statements: each generator PRG has a binary payload appended immediately after the BASIC program terminator.

The marker is the final BASIC line's zero terminator followed by the two-byte zero link pointer. The helper scans upward from `$0800` for three consecutive zero bytes, skips those three bytes, and begins reading the appended records.

Each record is:

| Field | Meaning |
|---|---|
| byte 0 | destination low |
| byte 1 | destination high |
| byte 2 | payload length |
| following bytes | payload copied to destination |

A length byte of zero means 256 bytes: the helper uses an 8-bit Y index and the copy loop terminates only when Y wraps back to zero. An all-zero three-byte header terminates the table.

The same helper bytes occur in all three generator programs. Their embedded record tables are different:

| Generator | Records | Payload bytes | Record destination span |
|---|---:|---:|---|
| Stage 1: `1.JD/E0&CBM/C0-G` | 33 | 463 | `$8781-$9F5A` |
| Stage 2: `2.CBM/E0-GENERAT` | 67 | 1,992 | `$65B7-$7FE5` |
| Stage 3: `3.SJD/E0-GENE460` | 82 | 625 | `$65B7-$8064` |

### What the tables actually patch

- **Stage 1** applies its 33 records to the captured E000-FFFF bank while that bank is still at C64 addresses `$8000-$9FFF`. Those C64 addresses map to drive ROM addresses `$E000-$FFFF`. Consequently, `(C)CMD/J/E0-FF` is not a raw ROM dump: it is the captured JD bank after the Stage 1 record table has been applied.
- **Stage 2** loads that intermediate at C64 `$6000`, applies its own 67 records, and saves the resulting 8 KiB as `(C)CMD/C/E0-FF` (the CBM E000-FFFF bank).
- **Stage 3** loads the same Stage 1 intermediate at `$6000`, applies its 82 records, and saves the resulting 8 KiB as `(C)CMD/SE0-F/460` (the SJD E000-FFFF bank).

This explains why applying only the Stage 3 records to the original JD image was insufficient: Stage 1's 33 records are part of the input-generation process.

### Reconstruction against the supplied ROM images

A clean-room interpreter was run against the supplied D64 and ROM binaries, without copying any patch payload bytes into the repository. Using the supplied JD image's E000-FFFF half, then applying Stage 1 followed by Stage 3, produces an 8 KiB E000-FFFF bank that differs from the supplied SJD 1541C image in just nine bytes:

- `$EAD5`
- `$EBC3-$EBC4`
- `$FA32-$FA37`

The generated bank SHA-256 is `3f7151c402d60a00308d1a0a10b34c28bbe5bad3b1c5851e1435a84c85d37f97`. This is a strong confirmation of the record format and stage ordering, but not yet an exact reproduction of the supplied SJD image. The six bytes at `$FA32-$FA37` are now understood: the supplied JD image has the 1541-II track-step code there, while the SJD target has `JMP $C010` followed by three NOPs. Wolfgang Moser's ROM comparison documents the 1541C track-zero sensor routine at `$FF36`; the 1541-II ROM lacks it. The SJD image relocates that routine into the otherwise unused C-bank area at `$C010` and redirects the `$FA32` hook to it. This explains the 67-byte C-bank addition described below.

The two bytes at `$EBC3-$EBC4` change a call target from `$F259` to `$C049`. The added helper at `$C049` calls `$F259`, then sets zero-page `$06` to 1 and `$00` to `$C0` before returning. This is a wrapper around the existing routine; its caller's broader purpose still needs mapping. The final mismatch at `$EAD5` is a byte set by a Stage-3 patch record: the reconstructed value is `$C0`, while the supplied SJD binary contains `$D0`. This may be a generator/image revision or model difference, but the evidence does not yet decide. Do not paper over it with a guessed patch. See [1541C-to-1541-II ROM comparison](https://www.zimmers.net/anonftp/pub/cbm/firmware/drives/new/1541/1541C-to-1541-II.txt).

One Stage 3 record starts at C64 address `$7FFF` and is 102 bytes long, so the interpreter writes through `$8064`. The generator subsequently saves only `$6000-$7FFF` as the 8 KiB output file. Only the first byte of that record is therefore in the saved bank; the remaining 101 bytes are written beyond it. The purpose of this spill is not yet established and should be investigated rather than silently discarded.

### C000-DFFF bank caveat

The first-stage BASIC program also manually patches its captured C000-DFFF buffer at C64 addresses around `$6070`, `$609F`, `$6D92`, `$7367`, and `$7CBB`, then saves `(C)CMD/C/C0-DF`.

Applying those literal patch locations to the C000-DFFF half of the supplied JD binary leaves 68 differences against the supplied SJD image: 67 bytes within `$C010-$C054`, plus one at `$C0AD`. The `$C010-$C048` portion is a relocated 1541C track-zero sensor routine: its instruction sequence corresponds to Wolfgang Moser's documented routine at `$FF36`, and the SJD E-bank hook at `$FA32` jumps directly to `$C010`. The `$C049-$C054` bytes are a small wrapper helper: it calls `$F259`, sets `$06=1` and `$00=$C0`, then returns. The Stage-3 output redirects a call at `$EBC2` to this helper; the caller's broader purpose remains to be mapped. The lone `$C0AD` mismatch is within the first-stage manual patch at `$C09F-$C0AD` and remains unexplained.

The generator's first stage reads the live drive address space, so the authoritative C000-DFFF input is a capture from the matching 1541C/JD configuration. The inspector supports two inputs: `--c000-capture` accepts a raw 8 KiB `$C000-$DFFF` capture and applies the literal first-stage POKEs extracted from the operator-supplied D64; `--c000-intermediate` accepts the Stage-1 `(C)CMD/C/C0-DF` PRG (8192-byte payload with `$6000` load address), which is already patched. Either path can be compared with the supplied SJD image, and `--c000-output` writes the resulting 8 KiB bank.

## SJD41 runtime hook map: first cross-bank pass

Static inspection of the supplied SJD image now identifies several explicit trampolines from the modified DOS bank into the added `$8000-$BFFF` extension bank. This is the architectural answer to the original "diff patch versus hook into JD" question: SJD41 does both, but its distinctive behavior is reached through hooks into new extension code.

| Hook address | SJD destination | Evidence / current interpretation |
|---|---:|---|
| `$FB15` | `$A003` | The hook is inside the original `FORMT` routine (the format-track path around `$FB0C-$FB17`), not the LOAD path. SJD diverts this format path into the extension; exact extension behavior remains to be disassembled. |
| `$F15C` | `$B4DD` | Replaces `NXTERR`, the disk-full path reached after the standard sector allocator exhausts its search. The extension scans tracks `$24-$28` (36-40) before returning disk-full, confirming the 40-track overflow path. |
| `$F173` | `$B842` | Replaces `FNDNXT`, the routine that chooses the optimum next sector on the current track. The extension routine consults the sector increment and track's maximum sector, so this is the configurable interleave/gap allocator path, not a read helper. |
| `$FA32` | `$C010` | 1541C track-zero sensor routine relocated into the C-bank, as described above. |
| `$EBC2` | `$C049` | Calls a small wrapper around `$F259`, then sets zero-page state. |
| `$DCD6` | `$C075` | Calls a short C-bank cleanup/helper routine after the modified status/job handling sequence. |

A raw byte-pattern scan of the SJD upper bank versus the supplied JD base finds 34 **changed** absolute JSR/JMP candidates into `$8000-$BFFF`. This is a candidate inventory, not a disassembly: some apparent opcodes may be data or operands. The confirmed/partially mapped entries above are only the starting subset.

| DOS call site | Extension target |
|---:|---:|
| `$E653` | `$B721` |
| `$E6D1` | `$B75F` |
| `$E6EA`, `$E6F4` | `$B7AA` |
| `$E8D7` | `$B81D` |
| `$E9FA` | `$B100` |
| `$EBFC` | `$AF00` |
| `$EC55` | `$B638` |
| `$EE1D` | `$B6A8` |
| `$EE3D` | `$B690` |
| `$EE43` | `$B678` |
| `$EE7F` | `$B4D6` |
| `$EED2` | `$B5DF` |
| `$EF28` | `$B5D6` |
| `$EF3A` | `$B4A4` |
| `$EF4F` | `$B46D` |
| `$EF85` | `$B794` |
| `$EFC5` | `$B86F` |
| `$F077`, `$F0B7` | `$B5CC` |
| `$F0D1` | `$B72F` |
| `$F15C` | `$B4DD` |
| `$F173` | `$B842` |
| `$F1AE` | `$B7C4` |
| `$F1DC` | `$B505` |
| `$F1FA` | `$B5F6` |
| `$F24B` | `$B613` |
| `$F27A` | `$A900` |
| `$F348` | `$B618` |
| `$F37C` | `$B6B1` |
| `$F3E8` | `$B82F` |
| `$F4D1` | `$B2F7` |
| `$FACB` | `$B6AD` |
| `$FB15` | `$A003` |

Run the scanner with:
`python3 tools/sjd41/crossrefs.py --jd-rom JiffyDOS_6.01-1541-and-1541-II.bin --sjd-rom S-JiffyDOS_1541C_v1.bin`

A separate in-place replacement at `$E91D-$E998` is a high-confidence disk-controller read/decode routine: it manipulates VIA registers `$1800`, `$1801`, and `$180D`, rotates sampled bits, and stores decoded bytes into the DOS buffer. This aligns with the documented GCR-to-HD decoding while reading. It is not one of the cross-bank calls; it is a replacement routine in the existing DOS bank. The nearby `$E781-$E7A1` change also reconfigures VIA registers and appears to support the altered controller path.

The first three entries are the key SJD extension call-ins, but they are not all read paths: `$A003` is reached from FORMAT, `$B4DD` extends the disk-full/track search to 40 tracks, and `$B842` replaces next-sector allocation. The GCR-to-HD LOAD optimization is a separate in-place routine at `$E91D-$E998`. This corrects the earlier tentative classification of `$FB15` as a fast-load hook.

A useful next static-analysis pass is to disassemble each trampoline's caller and the first extension routine block, then build a call graph across `$8000-$BFFF`. The host-side JiffyDOS byte transport should remain a separate question: the extension may accelerate drive-side disk operations while still using the existing JD IEC bus routines.

The helper's initial copy of C64 `$E000-$FFFF` to `$4000-$5FFF` is separate from the record interpreter. The helper does not subsequently reference that copied range in its visible code; its purpose is also still open.

### Reproducible local inspector

`tools/sjd41/generator_records.py` parses the supplied 35-track D64, finds the three PRGs, extracts record metadata without printing payload bytes, applies Stage 1 and Stage 3 to a user-supplied JD image, and optionally compares/writes the resulting E000-FFFF bank. No ROM bytes or extracted patch payloads are embedded in the tool.

Run the local reconstruction/inspection tool from the repository root:

```sh
python3 tools/sjd41/generator_records.py \
  --disk /path/to/ajnsjd41.d64 \
  --jd-rom /path/to/JiffyDOS_6.01-1541-and-1541-II.bin \
  --compare-sjd /path/to/S-JiffyDOS_1541C_v1.bin \
  --output /tmp/sjd-e000.bin \
  --c000-intermediate /path/to/C_C0-DF.prg \
  --c000-output /tmp/sjd-c000.bin \
  --summary-only
```

The E-bank output is only the reconstructed 8 KiB E000-FFFF bank, not a complete drive ROM. When a live C-bank capture is supplied, the tool also emits/compares the patched 8 KiB C000-DFFF bank. It reports the remaining E-bank mismatches and the 101-byte spill separately. Parser and C-bank decoder tests live in `tests/test_sjd41_generator_records.py`.



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

## Compatibility and model caveat

The first-stage program's literal check is `JIFFYDOS 5.0 1541`. The user confirms that JiffyDOS drive ROMs did not rev from 5.0 to 6.x and that the drive ROM binaries are byte-identical, so this literal status string is the expected signature and is not a 5.x-only restriction. The remaining compatibility question is **drive-ROM model baseline**, not JiffyDOS release number: the local 16 KiB JD image is labelled for 1541/1541-II, while the comparison target is explicitly a 1541C S-JiffyDOS image. The documented 1541C/1541-II track-zero differences explain six of the nine E-bank mismatches. Do not infer that one model's captured C000-DFFF bank is interchangeable with the other.

## Next reverse-engineering work

1. Fully disassemble the first-stage helper at drive `$0400` and the C64-side transfer routine; establish exact source ranges and the 128-page transfer mapping.
2. Annotate the first-stage post-capture patches that produce `(C)CMD/C/C0-DF`.
3. Disassemble the shared 138-byte helper in stages 2 and 3; identify pointer tables, source/destination spans, and transformation differences caused by their inputs.
4. Trace the final generator's exact load/save address ranges and file offsets, then compare generated layout against the supplied SJD41 image.
5. Keep all extracted ROM-derived files and generated images local; commit only clean-room descriptions, tests, and original Breadbin code.