# Fastest known loaders for an unexpanded C64 + stock 1541 (2022 to 2026)

Scope: loaders that run on a stock C64 and a stock 1541 with no REU and no cartridge. Sources were fetched with curl on 2026-10-31. Raw downloads are in `pages_modern/` and `modern_dl/`. Verification labels:

- VERIFIED (URL): the claim was read in the cited source, and any arithmetic was checked here.
- UNVERIFIED: claimed by a secondary source or inferred, not measured here.

## Baseline

- Stock KERNAL load: 403 B/s on a 177-block (44,958-byte) file, 1:51.5. VERIFIED (https://www.obliterator918.com/benchmarking-transwarp-the-insanely-fast-1541-loader/). The 254-bytes-per-block convention matches the arithmetic: 44,958 / 111.5 s = 403.
- Physical limit: 300 rpm gives one revolution per 200 ms. Per-zone ceilings for 223 payload bytes per sector, as stated by the Transwarp Writer docs: tracks 1-17 23.4 KB/s; 18-24 21.2; 25-30 20.1; 31-35 19.0. VERIFIED (`modern_dl/twwriter/x/transwarp-writer-1.0/docs/how-the-fast-paths-work.md`, from the source zip at https://csdb.dk/release/?id=264615). The arithmetic is checked here: 21 x 223 / 0.2 s = 23,415 B/s.

## 1. Transwarp (Krill, Plush), v0.84 and v0.86

- Who: Krill (Gunnar Ruthenberg) of Plush. CSDb release, Transwarp V0.86, 24 Feb 2022, and "50x Fastload System on Plain Vanilla Stock 1541". VERIFIED (https://csdb.dk/release/?id=214786). Earlier V0.64 is at https://csdb.dk/release/?id=197710.
- Measured: 16,056 B/s on DTB (177 blocks, 2.8 s), 40x, with Transwarp 0.84. Method: Disk Transfer Benchmark, timed around JSR LOAD and return, so it includes overhead. VERIFIED (https://www.obliterator918.com/benchmarking-transwarp-the-insanely-fast-1541-loader/). Obliterator says up to 50x excluding overhead, which is about 19.5 KB/s. The "just under 20 KB/s" figure is therefore the outer-track ceiling and the excluding-overhead figure, not an end-to-end measurement. UNVERIFIED for the v0.86 number.
- Mechanism: the drive reads raw GCR with one table lookup per byte, with no GCR decode and no handshake per byte. The encoder pre-shapes each sector so the raw stream is correct. Whole tracks are read in any sector order. Payload is 223 bytes per sector. The C64 receive loop runs in RAM under the KERNAL with the screen blanked, sprites off and interrupts off. The C64 uses `jmp ($DD00)` as a four-way bus-state branch. VERIFIED (`docs/how-the-fast-paths-work.md`, same tree as above).
- Requirements: pre-encoded files only (cc1541 -W or the Transwarp Writer); load only; saving fails (the DTB save run put the drive in an error state); screen blanked; v0.86 files must fit $0400-$CFFF; v0.86 hangs with a second drive on the bus. VERIFIED (Obliterator page and `how-the-fast-paths-work.md`).
- Drive code: resident table at $0600 and the loop fit in drive RAM. Byte count not given in the sources read. UNVERIFIED.
- Licence: `transwarp.s` is GPL v3 per the Transwarp Writer source (`README`). Under the repo policy this code cannot be adopted, only described from public sources. VERIFIED (the Writer's docs).
- Transwarp Writer 1.0 (Obliterator918, 26 Sep 2026) encodes Transwarp files natively on a C64. Its own reads are about 1.9 KB/s and its writes about 5.5x the serial bus. VERIFIED (https://www.obliterator918.com/transwarp-writer-native-c64-encoder/ and https://csdb.dk/release/?id=264615).

## 2. Krill's Loader, Repository v194 (Plush), 24 Nov 2022

- Source: CSDb https://csdb.dk/release/?id=226124 (download `loader-v194.zip`, unpacked to `modern_dl/krill194/x/loader/`). VERIFIED.
- Measured: "maximum raw loading speed of 7.7 kB/s (~20x) on 1541, typical speed is around 7 kB/s (~18x)". VERIFIED (`loader/README`, Features). Method not stated, and the README does not say whether this is raw or includes decompression. UNVERIFIED as to method.
- Native interleave for uncompressed files: 4 revolutions on tracks 1-17, 3 on tracks 18+. Compressed: 4 everywhere. VERIFIED (README). The arithmetic is inferred here: 21 sectors x 254 bytes over 3 to 4 revolutions gives 6.7 to 9.0 KB/s, which brackets the stated 7.7 KB/s. INFERRED.
- Protocol: 2-bit+ATN, 72 cycles per byte. VERIFIED (README and `docs/Protocol.txt`).
- Resident size: $1F9 bytes for load plus ZX0 depack; $1FB with TSCrunch; $E0 for raw load only. VERIFIED (README).
- Requirements: IRQ, NMI, DMA, sprites and badlines are allowed (no screen blanking needed). Standard DOS format, so ordinary files work. Multiple drives on the bus are allowed. Loads only from the primary drive. VERIFIED (README).
- Drive code: `drivecode1541.s` is 51 KB of source including comments. Assembled size not given. UNVERIFIED.
- Licence: custom permissive licence with attribution, "Copyright 2022 Gunnar Ruthenberg" (`loader/README`, License). Not GPL. VERIFIED.

## 3. Bitfire 1.1 (Bitbreaker, Performers), 11 Feb 2022

- Source: CSDb https://csdb.dk/release/?id=214232 and GitHub https://github.com/bboxy/bitfire (the GitHub API is blocked here, so the README came from raw.githubusercontent). The tarball `bitfire-1.1.tar.gz` contains `benchmark/benchmark_bitfire.ods`. VERIFIED.
- Layout: fixed interleave 4, own directory of 63 entries per sector on track 18, and its own file format that is d64-compatible only for the BAM. VERIFIED (`bboxy/bitfire` README).
- Measured (sheet, v1.0-era numbers in the 1.1 tarball): raw load of a 98,719-byte set takes 17.94 M cycles, which is 5.29 KiB/s. Loadraw plus depack of 190,819 bytes gives 15.38 KiB/s. Units are KiB/s at the PAL clock (985,248 Hz), checked here by arithmetic against a row of the sheet. Method: cycle counts in the sheet, with the raw-transfer and depack timings split. VERIFIED (the ODS, `content.xml`).
- Resident size: $8B to $1EA bytes, depending on configuration. VERIFIED (`readme.txt`).
- Requirements: the framework uses IRQs. Whether it blanks the screen is not stated. UNVERIFIED.
- Licence: BSD 3-clause, "Copyright (c) 2021, Tobias Bindhammer" (`LICENSE`). VERIFIED.
- Drive code size: not found. UNVERIFIED.

## 4. Sparkle 2.2 (2022) and 3.4 (27 Apr 2026), OMG / Sparta

- Sources: CSDb https://csdb.dk/release/?id=218961 (Sparkle 2.2), https://csdb.dk/release/?id=261356 (Sparkle 3.4), and the manuals inside `Sparkle2.2.zip` and `Sparkle3.4.zip`. VERIFIED.
- Specs from the manuals: 124-cycle GCR loop, tolerant of 269 to 314 rpm (3.4: 272 to 314); 2-bit+ATN at 72 cycles per byte; resident $2A0 bytes; 3 zero-page bytes; default interleave 4 on tracks 1-17, 3 elsewhere. VERIFIED (manuals).
- Measured speed: none published in the manuals or CSDb pages. The only CSDb comment is qualitative ("best loader there is"). Speed claims: none found. UNVERIFIED (no numbers).

## 5. Spindle 3.1 (Lft, 4 Feb 2022)

- Sources: CSDb https://csdb.dk/release/?id=214051, and `spindle-3.1.zip` (README and `spindle-handbook.pdf`). VERIFIED.
- Handbook claims "World class loading speed" but gives no B/s figure. Serial protocol is 18 cycles per bit pair, or 19 with other drives present. Silences 1541, 1541-II, 1570, 1571 and 1581 on the bus. Resident: one page, one buffer page, 5 zero-page bytes. VERIFIED (handbook text, `txt/spindle.txt`).
- Speed measurement: none found. UNVERIFIED.
- Licence: src MIT (Linus Akesson). VERIFIED (README).

## 6. Obliterator918 DTB comparison (2021, page updated in 2026)

- https://www.obliterator918.com/comparison-of-commodore-64-speed-loaders/ . The table covers stock 403 B/s; Epyx 2121; Warp Speed 3017; JiffyDOS 1541-II 3746; Super Snapshot 5 4163; Action Replay 5 5352; Transwarp 0.84 16056; U2+ Hyperspeed 64223. VERIFIED.
- Method: DTB, one 177-block file. The page's own caveat: some loaders cannot be tested this way, and a commenter reports timing differences against manual timing (https://www.obliterator918.com/more-speed-loaders-tested-new-page-for-c64-fast-load-data/). VERIFIED.

## Not reached

- csdb.dk forum and comments search: no loader-benchmark threads found (searches for "fastest loader" and "loader benchmark" returned nothing).
- lemon64.com: Cloudflare challenge. Not reached.
- forum.6502.org: search URL returned 404. Not reached.
- pagetable.com: no loader articles in the 2026 home page. Not reached for loader posts.
- github.com repos (mist64/krill, linusakesson/spindle, spartaomg/SparkleCPP): the GitHub API is blocked for this session. Raw README for Bitfire fetched.

## Summary

For a stock 1541 and stock C64, the fastest measured loaders are Transwarp (16 KB/s end to end on DTB; outer-track ceiling about 19 to 23 KB/s), then Krill v194 (7 to 7.7 KB/s, IRQ-friendly, standard DOS format) and Bitfire (5.3 KiB/s raw). Sparkle and Spindle publish specs but no throughput numbers. Transwarp needs pre-encoded files and a blanked screen, and it is GPL, so only its ideas can be used here.
