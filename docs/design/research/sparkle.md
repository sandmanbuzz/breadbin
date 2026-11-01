# Sparkle (Sparta/OMG): research report

Research only. Nothing from either repo was executed; only `git clone --depth 1`, `cat`, `grep`, `stat`, `ls` were used. Clones:
- `/tmp/claude-0/-home-user-breadbin/ac401ab2-2ad5-5a0d-81f0-7272d9803b0d/scratchpad/research2/clone_sparkle2/Sparkle2`
- `/tmp/claude-0/-home-user-breadbin/ac401ab2-2ad5-5a0d-81f0-7272d9803b0d/scratchpad/research2/clone_sparklecpp/SparkleCPP`

Both clones are shallow (depth 1), so git history beyond the last commit was not checked. The two user manuals are FlateDecode-compressed PDFs that cannot be read with grep/cat, so no figure below comes from a manual. Anything the manuals might state is UNVERIFIED.

## Template fields

**name / author / version / date**
- Sparkle 2 (repo `Sparkle2`). Author: Sparta (`My Project/AssemblyInfo.vb`: `<Assembly: AssemblyCopyright("Copyright © Sparta 2019-2022")>`). VERIFIED. Versions: loader history ends "v33 ... released with Sparkle 2"; drive code last revision v19 (`C64 Source/SD.asm`); saver SS v1.5; VB assembly version `2.2.22.0814`; manual file "Sparkle 2.2 user manual.pdf". Last commit 2022-08-26 (`53a5a95`). VERIFIED.
- SparkleCPP (repo `SparkleCPP`). Author: Sparta/OMG (LICENSE, see below). VERIFIED. Version: `sparkle.rc` `FILEVERSION 3,4,26,1025` (Sparkle 3.4); drive code last revision v23 (`resources/sd.asm`); manual "Sparkle 3.4 user manual.pdf". Last commit 2026-10-25 `ec1dfb4` "Sparta: 261025 - Saver plugin update bug fix". VERIFIED.

**source URL(s)**
- https://github.com/spartaomg/Sparkle2 (C64 source in `C64 Source/`, VB packer in `*.vb`, manual in `Manual/`)
- https://github.com/spartaomg/SparkleCPP (C64 source in `resources/`, C++ packer in `*.cpp`, manual in `manual/`)

**licence or usage statement (verbatim) + URL; reuse evidence**
- SparkleCPP, `LICENSE` (https://github.com/spartaomg/SparkleCPP/blob/main/LICENSE), verbatim:
  > BSD 3-Clause License
  >
  > Copyright (c) 2019-2026, Sparta/OMG
  >
  > Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
  >
  > 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
  >
  > 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
  >
  > 3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.
  >
  > THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
- Sparkle2: there is no licence file. `git ls-files` lists no LICENSE, COPYING or NOTICE file, and the shallow history shows none. The only rights statement is `My Project/AssemblyInfo.vb`: `<Assembly: AssemblyCopyright("Copyright © Sparta 2019-2022")>`. Without a licence grant, the code is all-rights-reserved by default. VERIFIED (absence).
- Reuse evidence: the sources credit "Inspired by Lft, Bitbreaker, and Krill" (SL.asm/SD.asm headers) and "based on THCM's tests" (SparkleCPP SD.asm v10). Third-party code in SparkleCPP (`thirdparty/lodepng`, `tinyexpr`) is not Sparkle's. Forks and reuse elsewhere were not checked (no GitHub API access used).
- Breadbin policy note: the BSD-3 licence is permissive and not GPL/LGPL. The Sparkle2 code carries no licence, so it cannot be adopted without the author's permission.

**host (C64) side**
- Sparkle2 (`C64 Source/SL.asm`, `SS.asm`):
  - Resident loader image copied to `$0160–$02FF` (LCopyLoop writes `LoaderCode+0..255` to `$0160` and `LoaderCode+$A0..` to `$0200`). That is about 416 bytes of code, including the fallback IRQ at `$02E6` and the depacker. Data buffer `$0300–$03FF` (256 bytes), which the source says must be left untouched between loader calls. Address ranges VERIFIED; exact byte count UNVERIFIED (nothing was built).
  - Saver plugin on disk, run at `$0300` (`SS.asm` `.pseudopc $0300`). Installer and saver code sizes are not stated in the repo; `Resources/SS.prg` and `SSIO.prg` are 487 bytes each (including the 2-byte header). VERIFIED (stat).
  - Zero page: `$01` (CPU port: `$35` = KERNAL off, I/O on; `$34` for I/O-off loads); `$02/$03` (destination pointer); `$04` (Bits); `$f8` (bus-lock value written to `$DD00`); `$FB/$FC` (DriveNo/DriveCt, installer only). `$BA` (device number) is used by the installer.
  - Non-ZP registers: CIA2 `$DD00/$DD02`; `$D012` (PAL/NTSC detection and optional IRQ raster); `$D019` (IRQ acknowledge, fallback IRQ); `$D018` and `$3C00` (multi-drive warning only); `$FFFA/$FFFB` (NMI vector set to an RTI); `$FFFE/$FFFF` (fallback IRQ vector).
  - Interrupts: the installer does `sei` (SL.asm line 262). The source contains no `cli`, and the first loader call "returns with I=1". So IRQs stay off during loading. VERIFIED from source.
  - Screen: not blanked and `$D011` is not touched. Sprites: no `$D015` access. VERIFIED (grep).
  - KERNAL ROM calls used by the installer: `$ED0C` (LISTEN), `$EDB9` (SECOND), `$EDFE` (UNLSN), `$FDF9` (SETNAM body), `$FE00` (SETLFS body), `$FFC0` (OPEN), `$FFD2` (CHROUT, for the drive-count message). Author comment: `JSR $E544` was removed because it "does not work properly on machines with old Kernal ROM versions".
- SparkleCPP (`resources/sl.asm`, `sc.asm`): the same loader in three configurations, selected by the stack value at load: Full `$0160` (`ldx #$5f`), NoIRQ `$017A` (`#$79`), Basic `$019F` (`#$9E`). Exports listed in `resources/Sparkle.inc` (`Sparkle_LoadA $19C`, `Sparkle_IRQ $160`, `Sparkle_NTSC_Check $1B7`, and others). Same `sei`/`$01 = $35` pattern. Byte count UNVERIFIED.

**drive side**
- Sparkle2: drive code `$0300` (`SD.asm` `.pseudopc $0300`), GCR ZP tables and loop at `$00–$7F` (copied from `$0600`), installer at `$0700`. Source `SD.prg` = 1,337 bytes (2-byte header plus 1,335). ModDisk.vb (line 750: `ReDim Preserve Drive((6 * 256) + 1)`) stores 6 blocks = 1,536 bytes on track 18 sectors 11–16. VERIFIED.
  - Upload: the C64 sends a command buffer (`SL.asm` `Cmd`): `M-E` to `$0205`, then a loop of `jsr $D586` ("Read Block into Buffer in Buffer Pointer") reading 18:15 down to 18:11 into buffers 4..0 (`$0700..$0300`), then `jmp $0700`. Author comment in the source. VERIFIED.
  - Drive ROM routines: `$D586` (block read, used by the C64-side command); `$FE00` (SS.asm line 328, "Using ROM function here", drive-side write mode; the C64 side also imports it as SETLFS body); `$FFFC` (reset vector, `jmp ($fffc)`); `$F77F,Y` (GCR table in drive ROM, SS.asm line 465). VERIFIED.
- SparkleCPP: drive code `$0300–$06FF`, directory `$0700–$07FF` (`sd.asm` layout comment). Installer at `$0600`, ROM constants `ROMReadBlock = $D586` and `ROMSeekBlock = $D038` (`sl.asm` line 223) plus `ROMLoadBAM`. Drive code size: not in the repo (only `.asm` source; `resources/sd.prg` is not present). UNVERIFIED.

**disk format: normal 1541 DOS disk / arbitrary T/S / custom; file-level or sector-level API?**
- Custom. The disk has a BAM and track 18 directory, but track layout is non-standard: Sparkle2 "tracks start with Sector 2", zones 0–2 IL3, zone 3 IL4 (`SD.asm` v01); SparkleCPP v18 "each track starts with sector 0". Data is GCR-encoded bundles with custom headers and ID checks. Not a normal CBM file system. VERIFIED from the history comments; the full layout is UNVERIFIED.
- Directory (SparkleCPP v16): 4 bytes per entry (track, first sector, sector count, block pointer), 64 entries per block, 128 files per disk max.
- API: file-level only. Loads are by bundle index (`Sparkle_LoadA`, 0–127), sequential (`Sparkle_LoadNext`), or prefetch (`Sparkle_SendCmd` then `Sparkle_LoadFetched`). No sector read or write call.
- Sector-level in principle: SparkleCPP has a custom drive-code plugin (`sc.asm`, `SparkleCustom.inc`: `Sparkle_RcvDrvCode $302`, `Sparkle_SendDrvCode $380`). The C64 can upload drive code blocks, so a programmer could reach sectors, but the loader provides no such API. Sparkle2 has no equivalent plugin.

**save/write support (yes/no/limited; how)**
- Limited, Hi-Score file only. Yes-limited. A saver plugin (`SS.prg` or `SSIO.prg`, the latter for I/O-space buffers) is written to the disk. The C64 calls `Sparkle_Save` (`$0302`) with A = high byte of file size (`$01–$0F`), or `A=$00` to abort. The drive switches to write mode via `$FE00`, Encodes blocks to GCR, and writes them back to the sectors.
- Limits: size must be a multiple of `$100` (SparkleCPP sparkle.cpp error text "Hi-Score File must be rounded up to the nearest $100 bytes"); address+length must be `<= $10000`; plugin bundle indices `$7E/$7F` (max 126 bundles, ModDisk.vb line 866). SS.asm v1.0: "high score file size: $0100-$0f00". SparkleCPP v22: "HSFile can be larger than $0f00 bytes"; multiple plugins and HSFiles per disk side. VERIFIED from source.

**transfer scheme: bits per step, lines used (CLK/DATA/ATN), handshake or timing based, sync with raster?**
- Scheme: "2-bit + ATN protocol" (SD.asm header). The drive sends 2 bits per step on CLK/DATA (`$1800` on the drive; the C64 samples `$DD00` bits 6–7). The C64 toggles ATN between steps as the handshake. Four steps per byte.
- C64 loop (Sparkle2 SL.asm, lines ~415–460; excerpt):
  ```
  Read1:  lda $dd00      ; 2 bits in
          sty $dd00      ; Y=#$08 -> ATN=1
          lsr
          lsr
          inx
          nop
          ldy #$c0
  Read2:  ora $dd00
          sty $dd00      ; Y=#$C0 -> ATN=0
  ```
  Each `ldaXX/ora` reads 2 bits, and the `sty $dd00` toggles ATN, so one byte takes four steps. VERIFIED.
- Host-to-drive (command/bundle index, C64 SendCmd): 1 bit per step on the ATN/AO line, with CO toggled. The source notes "18 cycles/bit - drive loop needs 17 cycles/bit". VERIFIED.
- Timing: timing-based, no raster sync during transfer. The drive uses a 124-cycle GCR read-decode-verify loop (SD.asm header); the C64 transfer loop is 72 cycles per byte (SD.asm v01 and SL comments). `$D012` is only read for PAL/NTSC detection and for the IRQ raster.
- Spartan Stepping (author's term): the drive moves the head half a track during data transfer (after `Sp=$52` bytes) so that the next track is pre-positioned without a pause. VERIFIED from source comments; mechanism described by the author, not measured.
- Compression: LZ with literals and matches (match lengths up to 255 bytes, v25), blockwise back-to-back (v27 "no half-blocks left unused"). Packer is `packer.cpp` (SparkleCPP) and `ModPacker.vb`. VERIFIED.

**speed: bytes/second (give number and where from)**
- Author-stated figure: none found in the sources (no "KB/s" or "bytes/second" text). Manuals not readable without decompression. UNVERIFIED.
- Derived ceiling (my calculation, not the author's): 72 C64 cycles per byte at the PAL clock of 985,248 Hz gives about 13.7 kB/s for the bus transfer alone. Disk read speed and stepping add to that. Treat as an upper bound, not a measurement.

**drive compatibility**
- Author's list (both repos, VERIFIED): "Tested on 1541, 1541-II, 1571, the 1541 Ultimate series, and Oceanic drives".
- Ultimate-II+: `ANC` was replaced with `AND+CLC` for compatibility (SD.asm, SparkleCPP sd.asm).
- JiffyDOS drives: not mentioned in either repo. UNVERIFIED.
- 1581 and other devices: not mentioned. UNVERIFIED.
- Multi-drive: the installer scans devices 8–11 and counts them (`SL.asm`, `Start:`). If more than one is present, it shows "sparkle supports only one active drive pls turn everything else off on the bus!" and loops until fixed. It does not support two active drives. VERIFIED. SparkleCPP's `sl.asm` has the same check.

**known problems**
- Requires a custom disk format and drive code. Not readable by normal DOS file access (inferred from format; UNVERIFIED in practice).
- Multi-drive is refused (above).
- Requires KERNAL ROM internals `$FDF9/$FE00` and old-ROM notes in the source. Compatibility with other KERNAL ROMs beyond the tested ones is UNVERIFIED.
- Sparkle2 v1.0 saver limit `$0F00`; later larger (SparkleCPP v22).
- Known fixed bug in SparkleCPP sparkle.cpp (line 6092): "UpdateZP BUG in Sparkle 3.3 REPORTED BY Wacek/Arise". Fixed; noted for history.
- SparkleCPP v19 removed trailing-zero and sync checks because "these make loading fail on Star Commander warp disks". Relevant if our format has similar disks.
- Speed claims are not in the repos (see above).

**safe behaviours: does it keep IRQs running?**
- No, during loading. The loader runs with `sei` and never `cli`s (both repos). Interrupts are off for the duration of a load call. VERIFIED from source.
- Between loads, a fallback IRQ can be installed (`Sparkle_InstallIRQ`, `$02D2` in Sparkle2; `$0160` vector in SparkleCPP). The IRQ saves and restores `$01` and calls a user subroutine (`Sparkle_IRQ_JSR`). Whether it runs safely while a load is in progress: UNVERIFIED (the code path implies no).
- The loader takes the NMI vector (`$FFFA`) and points it at an RTI, and sets `$01` = `$35` (KERNAL off) during loads. It also holds the bus with a bus-lock write to `$DD00` after each load (`BusLock`).
- Screen and sprites: not touched in normal operation (see host side).
