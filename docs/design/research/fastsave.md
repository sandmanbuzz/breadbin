# Fast writing (saving) to a 1541 over the serial bus: research notes

Status of sources: pagetable.com, svn.icomp.de, codebase64.net, csdb.dk (WebFetch), dusted.dk, linusakesson.net, commodore.ca and theoasisbbs.com failed DNS resolution from the research environment (ENOTFOUND), so those are UNVERIFIED and only seen through search snippets. Local clones in the scratchpad were read directly. Nothing was executed.

---

## 1. Bitfire save (dotscha fork of bboxy/bitfire)

- name / author / version / date: Bitfire, Tobias Bindhammer (bboxy); save routines in fork "dotscha" (no author line found in save.asm). Version: UNVERIFIED (fork changelog not read). Date: UNVERIFIED.
- source URL(s): https://github.com/bboxy/bitfire (origin of the local clone, git remote verified). Local files: clone_bitfire/dotscha/bitfire/save.asm, sector_routines.asm, drivecode.asm, testing/save_test.asm.
- licence: upstream bboxy LICENSE (VERIFIED in clone_bitfire/bboxy/LICENSE): "BSD 3-Clause License / Copyright (c) 2021, Tobias Bindhammer". The dotscha fork has no LICENSE file; its readme.txt says only "Bitfire is a fixed interleave loadersystem...". Fork licence: UNVERIFIED (assume the upstream BSD terms, check before reuse). Reuse evidence: the fork's readme says it adds "a save routine to the package for the request of game developers".
- host (C64) side: sector_routines.asm is a macro-assembled block placed at BITFIRE_SAVE_ADDR (default $400 in the test); it uploads code with M-W-style byte sends. Resident size: UNVERIFIED (not built). Zero page: uses the ZP-free bit-bang pointer in self-modified code; IRQ and screen: UNVERIFIED (not stated in the code I read; it runs its own bit protocol on $dd00/$dd02 and writes $dd02 directly). Sprites: UNVERIFIED.
- drive side: drivecode_41 writer, uploaded as a chunk of max 256 bytes (comment: "Max size: 256 BYTEs!"). Runs at $0500 (init) and $0600 region (writer, `!pseudopc .d_i_initstart`). Uses 1541 ROM $F77F as dos_bin2gcr (1541), $F8A0/$F8C0 as gcr decode tables. Uses 1541 VIA $1800/$1C00/$1C01/$1C03/$1C0C directly.
- disk format: normal 1541 DOS disk, arbitrary track/sector, sector-level API. The writer builds its own header (ID1/ID2, sector, track, checksum) and data block (sign $07, 256 bytes, checksum, $00 $00), with a sector-number limit table per track.
- save/write support: yes, sector-level. Routine writes one sector per call: X=track, Y=sector, then the 256 data bytes are sent over the serial bus (`bitfire_save_write_block_offs`). Next block offset wraps to the next track with the interleave (`BITFIRE_CONFIG_INTERLEAVE`).
- transfer scheme: 2-bit parallel over CLK/DATA (the "2bit ATN" protocol in the fork readme, port $dd00 on C64, $1800 on the drive). Handshake: ATN toggling for acknowledgement (`.sendbyte_todrv`, `.wait_drv_idle`). Not raster-synced: uses waste loops for timing.
- write protect: VERIFIED. `.d_w_...` checks `$1c00` bit 4 (WPS) and returns status 00 (WP on) to the C64 (sector_routines.asm lines 476-478, 596-598; drivecode lines 372-378 in the iszell variant).
- BAM handling: none in the writer. It writes the sector only; the BAM is not updated (the sectors must already be allocated, e.g. a preallocated file). Verification: after writing, `.d_d_retryvfy` / `.d_d_errorvfy` read the sector back with the GCR decoder and compare, with a retry counter `.verifycnt` (lines 696-736 of drivecode.asm).
- speed: UNVERIFIED (no benchmark numbers read; the benchmark directory has an .ods file, not read).
- drive compatibility: 1541 and 1551 (`BF_DRIVE` switch). Single drive on bus only (2-bit ATN). Not tested here on stock or JiffyDOS ROMs.
- known problems: readme says "no second drive is allowed on bus" (fixed-interleave loader, 2-bit ATN).

## 2. Sparkle save (Sparta/OMG; C64 "SS" + drive "ss" routine)

- name / author / version / date: Sparkle 3.4 (C++ fork "SparkleCPP") and Sparkle 2.x (VB.NET tool). Authors: Sparta/OMG. Copyright 2019-2026 (LICENSE).
- source URL(s): local clones (Sparkle sources; the origin URL was not captured in the clone). Local files: clone_sparklecpp/SparkleCPP/resources/ss.asm (14041 bytes source), clone_sparklecpp/SparkleCPP/LICENSE, clone_sparkle2/Sparkle2/C64 Source/SS.asm (10875 bytes).
- licence (VERIFIED, verbatim first line of clone_sparklecpp/SparkleCPP/LICENSE): "BSD 3-Clause License" and "Copyright (c) 2019-2026, Sparta/OMG". Clause 3 forbids using the names of the copyright holders to endorse products. Reuse evidence: credits in the source header "Inspired by Lft, Bitbreaker, and Krill" (sd.asm line 4).
- host (C64) side: SS.asm is a hi-score file saver. Block structure documented: first block $F7 data bytes, other blocks $FA; end marker $00 $F8. Resident size: UNVERIFIED (not assembled). Uses ZP at $02/$04 (`.const ZP=$02`, `.const Bits=$04`). IRQs and screen: UNVERIFIED. Does not seem to blank the screen (not stated).
- drive side: ss.asm (drive part, after line ~300) writes a sector: reads sector header (`FetchSHeader`), checks it is on the wanted list, skips the header gap, writes 6 sync bytes ($FF), then the GCR data via $1C01 with a bvc timing loop; calls ROM $FE00 at the end (sector-write finish). Drive code at $0300 range; upload method: UNVERIFIED (the README references "Sparkle_SendCmd" and ATN-based transfer). Drive code size: UNVERIFIED (not assembled).
- disk format: normal 1541 DOS disk; writes data into the existing sector chain of the save file (fixed track/sector list); no directory or BAM update. Sector-level, file-specific.
- save/write support: limited: writes only the hi-score file's sectors (fixed size, $0100-$0F00 bytes in v1.0). Not a general file write.
- transfer scheme: 2-bit + ATN (the drive side comment: "2-bit + ATN protocol"). Timing: `bvc` loop, 1541 ROM sync/gap constants (`skip 6 gap bytes, write 6 sync bytes`).
- write protect: UNVERIFIED (not found in ss.asm; grep for $1C00 found no WPS check).
- BAM handling: none (ss.asm: "Automatically skips track 18" in NextTrkSvr; the writer does not touch the BAM).
- error handling: header sector compare and wanted list; if a sector is missing the loop retries (UNVERIFIED in detail).
- speed: UNVERIFIED (the README and manual not read).
- drive compatibility: the load path claims "Tested on 1541, 1541-II, 1571, the 1541 Ultimate series, and Oceanic drives" (clone_sparklecpp/SparkleCPP/resources/sd.asm header, VERIFIED as text; applies to the loader sd.asm, not the saver). Save-path tests: UNVERIFIED.
- known problems: UNVERIFIED.

## 3. iszell sectorwriter (Bitfire-derived save, legacy and new status modes)

- name / author: UNVERIFIED (directory clone_bitfire/iszell/sectorwriter). Files: save-drivecode.asm (12432 bytes), save-resident.asm (5286 bytes), save-resi-c64-41.asm, save-drive-41.asm.
- licence: UNVERIFIED (no LICENSE in iszell/sectorwriter).
- drive side: same ROM-GCR approach as Bitfire. Status codes: wpon=$00, nosync=$01, sctrnotf=$02, writeerr=$03 in legacy; new mode uses `st_rdymsk` bits. Write protect is checked via $1C00 bit 4 (VERIFIED, lines 253-259 and 372-378).
- speed, compatibility: UNVERIFIED.

## 4. Krill's Loader (Plush) save support

- name / author: Krill's Loader, Krill of Plush (csdb credit "Code .... Krill of Plush"; "Help .... Bitbreaker of Nuance, Performers", VERIFIED from cached page web/https___csdb_dk_release__id_226124.html).
- source URLs: https://csdb.dk/release/?id=118713 (v146, 2013) and https://csdb.dk/release/?id=226124 (v194, 2022), cached copies in clone research2/web/.
- save support: NOT FOUND. The feature list on plus4world (web/https___plus4world_powweb_com_tools_Krills_Loader.html, VERIFIED) lists only loading: "loads uncompressed files ... loads compressed files ... loads via directory ... polled loading and non-blocking loading using CIA timer NMIs". The task's premise of "Krill's Loader save" is not supported by these pages. Licence: UNVERIFIED; no licence text was found.
- The 1541 speed in the feature list: "max. loading speed is 4.0 kB/s for uncompressed files on 1541".

## 5. Not reached

- 15 Second Copy (pagetable.com/?p=656): DNS fail. Only a secondary search summary was available: a Mike J. Henry "15 second format" uploads code by M-W and runs it by M-E, reuses ROM header and data encode routines (DOS 2.6 compatible), and skips the verify pass (theoasisbbs summary via search, UNVERIFIED).
- Chaco eload drive_1541_write.s (svn.icomp.de): DNS fail. The search summary says a job-dispatch loop with a 512-byte cap, write-protect check, and job code $90 (UNVERIFIED).
- codebase64 fast save pages: DNS fail.
- Job queue layout ($00-$05 status/header, $06-$0B track/sector, job $90 write): UNVERIFIED; from prior knowledge of the 1541 ROM, not from a fetched source.

## Summary of what is solid

- Bitfire's writer and Sparkle's writer both bypass the DOS job queue and write raw GCR through $1C01 with bvc timing loops (VERIFIED from source).
- Both check write protect (Bitfire VERIFIED; Sparkle not found).
- Bitfire verifies by reading back and retries (VERIFIED). Sparkle saves into a fixed sector chain with no BAM update.
- Licences: BSD-3 for bboxy/Bitfire and Sparkle (VERIFIED). BSD-3 is permissive and compatible with the repo MIT licence if credit is kept in the header and reuse is checked against docs/design/fast-io.md policy; the Krill loader has no save path.
