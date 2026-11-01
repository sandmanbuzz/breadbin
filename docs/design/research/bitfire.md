# Bitfire: research report (filled from the template)

Clones (read only, nothing built or executed):
- `/tmp/claude-0/-home-user-breadbin/ac401ab2-2ad5-5a0d-81f0-7272d9803b0d/scratchpad/research2/clone_bitfire/bboxy` (primary, from https://github.com/bboxy/bitfire, HEAD 5a3964b, tag v1.2)
- `.../clone_bitfire/dotscha` (https://github.com/dotscha/bitfire, HEAD ac62bd6, tags up to 2017.12.13)
- `.../clone_bitfire/iszell` (https://github.com/iszell/bitfire, HEAD 44456ef, tag-like name bf-nbv2-beta5-240917)

Byte counts were not measured: the build needs an assembler run, which was outside the read-only brief. Anything marked UNVERIFIED is a reading of the source or docs, not a measurement.

---

## 1. bboxy/bitfire (the primary fork)

- **name / author / version / date**: "bitfire", Tobias Bindhammer (bboxy). Version: tag v1.2 (`git tag`); HEAD commit 5a3964b "add support for vc20 as well", dated 2026-09-10. VERIFIED (git log in the clone).
- **source URLs**: https://github.com/bboxy/bitfire (code, `readme.txt`, `README.md`, `changelog`). Drive code `bboxy/loader/drivecode.asm`, C64 side `bboxy/loader/resident.asm`, installer `bboxy/loader/installer.asm`, config `bboxy/config.inc`. VERIFIED.
- **licence**: `LICENSE` (BSD 3-Clause), first lines verbatim: "BSD 3-Clause License / Copyright (c) 2021, Tobias Bindhammer / All rights reserved." Clause 3 forbids using the author's name for endorsement. Source headers repeat the BSD text ("(c) Copyright 2021 by Tobias Bindhammer. All rights reserved."). The `packer/zx0/LICENSE` is a separate file for the ZX0 parts. VERIFIED. Reuse evidence: `changelog` and `readme.txt` credit Krill (bvs sync idea), Ikwai and THCM (hardware testing), and Einar Saukas and Emmanuel Marty (zx0/salvador). The fork lineage is shown by dotscha and iszell (below), which carry the same code. VERIFIED.
- **host (C64) side**: resident size is not measured. Docs say "$84 to $200 bytes, depending on configuration" (`readme.txt`, top), "standalone loader size now $7b bytes" (`changelog`), and "loadraw consumes $7e bytes" (`readme.txt`, config section). VERIFIED as documentation only. Zero page: `CONFIG_ZP_ADDR = $02`, "maximum 11 bytes needed, 5 for loader, 6 for depacker" (`config.inc`, `resident.asm`). Default `CONFIG_RESIDENT_ADDR = $f000` in `config.inc`, while the readme recommends `$0200` ("Yes, i prefer to place the whole thing at $0200-$3ff"). VERIFIED. IRQ: the receive loop has no `sei`/`cli` and no interrupt guard in `ld_gloop`; the installer runs under SEI. The resident base IRQ (`link_player`) reads CIA2 `$dd0d` and bumps `$01` (assumes `$01 = $34/$35`). The readme says it "can be used while loading", but how it avoids firing mid-byte is UNVERIFIED. Screen blanking and sprites: no `$d011` or sprite code in the loader (grep). Screen-on or badline behaviour is not addressed in source or docs: UNVERIFIED.
- **drive side**: size not measured (`bitfire_drivecode_size` is computed by the assembler). Placement: code image starts at `$00` (zero-page tables and variables, `.zp_start`), code and a second table at `$0200`, a second table at `$0300` (`.tab0070dd77_hi = .tables + $100`), cache at `$0600`, bootstrap at `$0600` (overlaps the cache; the bootstrap is used once), directory at `$0700`. The stack page `$0100-$01ff` is used as the sector byte buffer: the GCR loop does `pha` per decoded byte and `tsx` (`drivecode.asm` ~lines 218-290). VERIFIED. Upload: the installer first sends `i`, then M-W 32-byte chunks of a bootstrap to `$0600` (`bitfire_bootstrap_run`), then M-E `$0600` (`installer.asm`, `.install_bootstrap`). The bootstrap then receives the rest of the drive image with its own bit-serial loop and writes it into zero page, skipping the stack page (`isc .block+1` loop, `drivecode.asm` ~1370-1410). Drive ROM use: no ROM routine is called. The reset vector is read through `jmp (.reset_drive)` with `.reset_drive = $fffc ;eaa0` (source comment: `$EAA0` is the 1541 reset target, UNVERIFIED against a ROM dump). The bootstrap uses the DOS job queue once: it writes job codes to `$04` and waits for the ROM to write `$01` back, with track in `$0e` and sector in `$0f` (`drivecode.asm`, `bitfire_bootstrap_run`). After that it takes over both VIAs with SEI and never returns to the ROM, except through the reset vector. VERIFIED from source; the job-code meanings (`$B0` seek, `$80` read) are the stock 1541 DOS convention, UNVERIFIED here.
- **disk format**: a custom, file-level format on a stock d64. Files are contiguous sectors with no track/sector link bytes (256 payload bytes per sector). The first sector is found from the directory; the following sectors come from a fixed interleave (`readme.txt`, "Disclayout"). Directory: 4-byte entries (load-address lo/hi, filesize-1 lo/hi), 63 entries per sector, two sectors on track 18 (`readme.txt`; `drivecode.asm` `.DIR_TRACK = 18`, `.DIR_SECT = 18`). Layout written by `d64write/d64write.c` (`d64_allocate_next_block`): interleave 4 on tracks 1-17, interleave 3 on tracks 18-35 (VERIFIED). The drive computes the same interleave: 4 in the slowest zone (tracks 1-17), 3 elsewhere (`drivecode.asm`, `.VARIABLE_INTERLEAVE`, lines ~1018-1095). Files are chained by filenum, not by sector.
- **file-level or sector-level API**: file-level only. Commands are a filenum byte: `$00-$7f` load file, `$ef` load next, `$ee` skip, `$f0-$fe` request disk side, `$ff` reset (`drivecode.asm` `.do_command`; `constants.inc`). There is no exposed "read track/sector N" call. The drive does sector reads internally (`.read_sector`), but the C64 cannot ask for an arbitrary sector. VERIFIED.
- **save/write support**: no, in bboxy. (Yes in dotscha, see section 2.)
- **transfer scheme**:
  - C64 to drive (command/filenum): `ld_loop` in `resident.asm` (~line 170-200) writes `$dd02` ten times, two bits per write, using CIA2 `$dd00` lines. Drive side: `.get_byte` (`drivecode.asm`, ~723-765) polls `$1800` for CLK transitions and samples data and CLK; `bmi .lock` (bit 7, the ATN input) makes it wait while the bus is held.
  - Drive to C64 (block data): 2 bits per step, 4 steps per byte. Drive loop `.preloop` (`drivecode.asm` ~617-650):
    ```
    .preloop
        lda (.preamble_data_),y    ; next byte (preamble, then data)
        bit $1800
        bmi *-3                    ; wait while bit 7 (ATN in) is set
        sax $1800                  ; first pair of bits out
        asl
        ora <.val10
        dey
        bit $1800
        bpl *-3
        sta $1800                  ; second pair
    ```
    C64 side `.ld_gloop` (`resident.asm` ~258-292) reads `$dd00` with `ora`/`and`/`adc` four times per byte, merging bits from two input lines:
    ```
    .ld_gloop
        lsr
        lsr
        ldx <CONFIG_LAX_ADDR
    bitfire_ntsc0  ora $dd00         ; bits from $dd00
        stx $dd02
        ror
        ror
        ldx #$3f
        sax .ld_nibble + 1
    bitfire_ntsc2  and $dd00
        stx $dd02
    ```
  - Naming: the "2-bit ATN" name in `readme.txt` (72-cycle transfer) and dotscha's README ("1541 2bit ATN") refers to this scheme: two bits per step on DATA and CLK, with ATN as the bus-lock/handshake line that the drive polls (`bmi` on bit 7). The exact electrical meaning of each `$dd02` value (ATN out vs. release) is UNVERIFIED here.
  - Handshake: the drive pulls BUSY (`$02`) after the last bit (`sax $1800` with `#$0a` mask). Sync for sector reads: `bit $1c00 / bmi` waits for SYNC, then `bvs` on byte-ready (`read_loop`). Sync with raster: none.
  - Timing: 74 cycles per byte on the bus (`changelog`, "serial transfer back at 74 cycles / byte"); the 72-cycle version failed on a long cable (`readme.txt`, Technical Limitations 4).
- **speed**: docs give no absolute kB/s. Stated: loadraw about 22% faster than v0.7, loadcomp 14%, decomp 20% (`changelog`, lines ~126-128). Our arithmetic (not stated by the docs): 74 cycles/byte at PAL 985,248 Hz is about 13.3 kB/s for the serial link alone. The benchmark spreadsheet `bboxy/benchmark/benchmark_bitfire.ods` (one sheet, cell labels ambiguous) gives cycle counts: loadraw of 98,719 packed bytes, new bitfire 17,944,637 cycles (about 18.2 s PAL), old 22,270,360 (about 22.6 s); loadcomp of 190,819 unpacked bytes, new 20,575,734 cycles (about 20.9 s), old 22,775,160 (about 23.1 s). Conversions are ours. VERIFIED that the cells exist.
- **drive compatibility**: 1541 (stock ROM assumed) and 1541-II tested by the author (`readme.txt`, Testing: "5 1541-ii drives... 2 1541C ... 1 1541 longboard"). 1551 and 1571: the changelog mentions 2 MHz switching on the 1571 (`changelog` line 75); bboxy's own drive code is 1541-only. 1581: not supported. Ultimate-emulated 1541: not mentioned, UNVERIFIED. Multiple drives: `installer.asm` loops device 8-11 and uploads an ATN responder (`.install_responder`, code at `$0205`, `$0400`, `$0440`) to every present non-target drive. The changelog says the responder keeps other drives on. VERIFIED from installer code; behaviour on hardware UNVERIFIED. JiffyDOS: no reference in bboxy, dotscha or iszell (grep). The drive code reads stock ROM tables (below), so JiffyDOS drive ROMs are UNVERIFIED and likely to break the bootstrap's job-queue use and the ROM table reads.
- **known problems** (from `readme.txt`, Technical Limitations): drive speed wobble and 300 rpm assumption; screen-induced read errors on some hardware (author's observation); heat; a 2 m unshielded cable on which the 72-cycle transfer failed; unsettled head after stepping; spin-up misses; 1541-II and "old longboard" failing on fast single-step ("shrydar" stepping, second half-step after `$0c00` cycles). SX64 buslock problems (`readme.txt`, bus_lock). Not supported: loading under I/O (`$d000-$dfff`): "not able to load or loadcompd under IO" (`readme.txt`), split and depack under I/O is possible with `link_decomp_under_io`.

---

## 2. dotscha/bitfire (fork with save and a plus/4 port)

- **name / author / version / date**: "bitfire" fork by dotsch (`git log`: "dotsch", HEAD ac62bd6 dated 2022-09-10; tags 2017.09.05 to 2017.12.13). VERIFIED.
- **source URLs**: https://github.com/dotscha/bitfire (`README.md`, `readme.txt`, `bitfire/drivecode.asm`, `bitfire/sector_routines.asm`, `bitfire/save.asm`).
- **licence**: none. There is no LICENSE, COPYING or NOTICE file in the repo (`find`), and `README.md` has no licence line. Source headers carry no licence text. Treat as all rights reserved until asked. VERIFIED (absence). Reuse evidence: README says it was made "as an attempt to create a plus/4 port"; the code is a superset of bboxy's. VERIFIED.
- **host (C64) side**: resident size and ZP not measured. README: "Supported drives: all 1541 compatible and 1551. Protocolls: 1541 2bit ATN (so no second drive is allowed on bus), 1551 8bit." VERIFIED. Config: `BITFIRE_ZP_ADDR = $04` (`bitfire/config.inc`).
- **drive side**: drive code is `.drivecode = $0000`, upper limit `$0500` ("Upload code is ... bytes too big!" check at end of `drivecode.asm`); the source comment says "maximum is $0110 - $04ae". Size not measured. Directory at `$0500`, GCR buffers at `$0600` and `$0700`, bootstrap at `$0700` (`drivecode.asm`). VERIFIED. Upload: `.upload` receives a 2-byte destination, a 2-byte count, then the bytes (`drivecode.asm` ~1436-1475), same 2-bit channel. ROM use: `.dos_bin2gcr = $f77f` (1541) is read as a data table in the save path, not called. GCR decode tables `.gcr_dec_lo = $f8c0` and `.gcr_dec_hi = $f8a0`. VERIFIED. Seek and stepping are the drive's own code (`.seek`, `.halftrack`, `$1c05` timer, `STEPPING_SPEED = $98`), no ROM call. VERIFIED. Bitrate per zone: `$00` on tracks 31+, `$20` on 25-30, `$40` on 18-24, `$60` on 1-17, with max sectors 17, 18, 19, 21 (`.seek`, `.set_bitrate`). VERIFIED.
- **disk format**: same family as bboxy but with a different directory. README: 42 entries per sector, each entry is track, sector, load-address lo/hi, size (`readme.txt`, "Disclayout", lines 34-42). Fixed interleave 4 (`readme.txt` line 57: "4 always has been the best choice"). VERIFIED. File-level read as in bboxy.
- **save/write support**: yes, sector-level write (`sector_routines.asm`, `save.asm`). Entry points (offsets into `BITFIRE_SAVE_ADDR`): `bitfire_save_init_offs` (upload init, motor on), `bitfire_save_write_block_offs` (`.dsr_sectorwrt`: X = track 1..40, Y = sector, then 256 data bytes sent over the same 2-bit channel), `bitfire_save_write_next_block_offs` (next sector with fixed interleave), `bitfire_save_finish_offs` (`.dsr_exit`, returns to loader). VERIFIED.
  - How it writes: GCR, not job queue. The C64 sends 256 bytes; the drive converts them with its own bin-to-GCR routine (`.d_i_bin2gcr`, table at `$f77f`) into 325 GCR bytes (65 groups of 4 bytes, `.mem_blockgcrb = $06bb`), and writes them raw through `$1c01` with the head in write mode (`$1c0c` mode line, `$1c03` data direction). Sync is five `$ff` bytes (40 bits). The header is NOT rewritten: `.d_i_waitblock` finds the existing header for the target sector first, so the sector must already be formatted. VERIFIED.
  - Verify: after writing, the drive waits for the block again and compares the raw GCR bytes it reads back with the buffer (`.d_d_retryvfy`, `cmp $1c01`). Retries: 3 verify attempts, then 3 write attempts (`.writecnt`, `.verifycnt`). Status codes sent back: `$00` write protected, `$01` no sync, `$02` sector not found, `$03` write error. VERIFIED.
  - Quote (write start, `sector_routines.asm`, `.d_d_start`/`.drv_writed_start`):
    ```
    lda #3
    sta .writecnt
    .d_d_retrywrt  jsr .d_i_waitblock   ; find the header of the target sector
    ```
    and the GCR sync and data loop:
    ```
    lda #$ff
    sta $1c01
    clv
    -  bvc *
       clv
    ```
    (sync write; the full block loop follows, same pattern).
- **transfer scheme**: as bboxy (2 bits per step, C64 to drive via `$dd02`, drive to C64 via `$1800`, `bmi` on ATN). `get_byte` (`drivecode.asm` ~1395-1420): reads CLK on bit 2 and DATA on bit 0 of `$1800`, shifts two bits per transition pair, and waits while bit 7 (ATN) is set. VERIFIED. Stepping at `$1c05` timer.
- **speed**: no figures in dotscha's README or changelog beyond "faster init" and "improved depacker speed" (lines 51-67 of `changelog`). UNVERIFIED for save speed. The 2-bit channel is the same as bboxy (74 cycles/byte per `changelog` line 3).
- **drive compatibility**: 1541 (`BF_DRIVE = 1541`) and 1551 (`BF_DRIVE = 1551`, TCBM ports `$4000-$4004` and `$fef0`). VERIFIED. The 1541 save path reads the stock ROM table `$f77f`, so a drive with a different DOS ROM is UNVERIFIED. JiffyDOS: no reference (grep).
- **known problems**: no licence; 1541 channel does not support a second drive (README); no I/O loading (inherited from bboxy's `readme.txt`); save path stops with error codes rather than retry beyond 3; header is not written, so unformatted disks cannot be saved to.

---

## 3. iszell/bitfire (newest fork, beta)

- **name / author / version / date**: "bitfire" fork by Siz (`git log`: HEAD 44456ef 2024-09-22). Version string in tag/branch: "bf-nbv2-beta5-240917" (`git log`, first lines). VERIFIED.
- **source URLs**: https://github.com/iszell/bitfire (`readme.txt`, `readme+4.txt`, `drive/drivecode.asm`, `sectorwriter/`, `installer/`, `drive/drivecode-fsdv.asm`, `drive/vcpumacros-acme.asm`).
- **licence**: none in the repo (no LICENSE, no notice line in `readme.txt`). VERIFIED (absence).
- **host (C64) side**: "$7b to $1fe bytes, depending on configuration" (`readme.txt` line 4). VERIFIED (docs only).
- **drive side**: `drive/drivecode.asm` (1416 lines) with `drivecode-1541.asm` setting `BF_DRIVE = 1541`. Same stock-ROM tables (`$f70c`-`$f729`, `$f8c0`, `$f8a0`, `$f77f`) as dotscha. VERIFIED.
- **disk format**: same bitfire layout as the other forks, with a `--40` track option (`readme.txt`).
- **save/write support**: yes. `sectorwriter/save-resident.asm` (C64 side, 281 lines) and `sectorwriter/save-drivecode.asm` (drive side). The drive side waits for ATN high after each bit pair ("Wait for ATN high (host accept the last bitpair)", `save-drivecode.asm` ~110). It uses the same bin-to-GCR table `drivecode_dos_bin2gcr` (`$f77f` for 1541, `$f8bf` for 1551). VERIFIED. Is it the same write-and-verify logic as dotscha? UNVERIFIED in detail; the names match.
- **transfer scheme**: 2-bit ATN for 1541, as above. VERIFIED.
- **drive compatibility**: 1541 and 1551 builds (`drive/Makefile` targets `drivecode-1541`, `drivecode-1551`). Plus an "fsdv" build for a FlexSD/VCPU drive (`drive/drivecode-fsdv.asm`, header "SD2IEC - FlexSD/VCPU drivecode"; `vcpumacros-acme.asm`, header "SD2IEC VCPU macros"). VERIFIED.
- **known problems**: the SD2IEC-derived files (`drive/drivecode-fsdv.asm`, `drive/bootstrap-fsdv.asm`, `drive/vcpumacros-acme.asm`) are a licence problem for Breadbin, see section 5. The `readme.txt` buslock note on SX64 (line 260) applies.

---

## 4. Does not work / limits (all three)

- Multiple drives: dotscha and iszell say no second drive on the 1541 bus. bboxy installs a responder on every other present drive (devices 8-11), which the author says keeps them on; it is not shown to work on hardware (UNVERIFIED).
- Loading under I/O (`$d000-$dfff`) is not supported; split and depack under I/O is possible in bboxy (`link_decomp_under_io`).
- Interrupts: the byte loop is cycle-counted and has no interrupt guard. Base IRQ or NMI is provided (`link_player`, CIA2 `$dd0d`), and the docs say it can run during loading. How mid-byte interrupts are avoided is UNVERIFIED.
- Bus locking: `bus_lock`/`bus_unlock` allow writes to `$dd00` when idle; SX64 has problems with an active buslock (`readme.txt`).
- Sectors: no arbitrary read API in any fork. Save (dotscha, iszell) writes arbitrary track/sector with 256 bytes. Verify is raw-GCR, not decoded checksum.
- Drive ROM dependence: bootstrap uses the DOS job queue once; save and bboxy's GCR decode use stock 1541 ROM table addresses. Any drive ROM that moves those tables (JiffyDOS, UNVERIFIED) breaks them.
- Fast stepping: "shrydar" second half-step after `$0c00` cycles fails on some 1541-II and longboard drives (bboxy `readme.txt`, item 9).

---

## 5. Relevance to Breadbin (short)

- Licence: bboxy is BSD-3-Clause, which fits the MIT repo if the copyright notice is kept (CLAUDE.md allows original work or demoscene code with credit; BSD code is not in that list, so it needs a decision). dotscha and iszell have no licence, so they cannot be taken. The iszell FlexSD/VCPU files are SD2IEC-derived and sd2iec is GPL per CLAUDE.md; do not adopt them.
- Hardware: the Breadbin hardware has JiffyDOS in every drive (CLAUDE.md, hardware notes). Nothing in these forks is tested with JiffyDOS. The stock-ROM table reads and the DOS job use are the first things to check.

