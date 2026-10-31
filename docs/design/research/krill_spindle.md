# Research: Krill's Loader and Spindle (C64 disk loaders)

Prepared 2026-10-31 by read-only research. Sources were downloaded into their own directories under the scratchpad (dl-*/ and x-*/) and read with grep/cat/pdftotext only; nothing was executed. Items marked UNVERIFIED were not confirmed in a source.

Shared note: the drive-side and host-side byte counts below come from the source as read, not from a build (no assembler was run). Where a figure is an estimate it says so.

---

## Loader A: Krill's Loader (Krill / Plush)

Primary version: repository version 194 (Krill's Loader, Repository Version 194). Older version 146 is also covered where it differs.

- name / author / version / date
  - Krill's Loader, repository version 194; code by Krill (Gunnar Ruthenberg) of Plush. README dated November 2022; csdb release date 24 November 2022. VERIFIED.
  - Older: repository version 146, released 7 May 2013 by Plush (csdb 118713). VERIFIED.
  - csdb 226124 (v194) and 118713 (v146) pages read; both list Code: Krill of Plush. v194 also lists Help: Bitbreaker of Nuance. VERIFIED.
- source URL(s) (code, docs)
  - https://csdb.dk/release/?id=226124 (v194 release page)
  - https://csdb.dk/getinternalfile.php/238373/loader-v194.zip (v194 archive, downloaded and extracted; README, docs/, src/, include/ read)
  - https://csdb.dk/release/?id=118713 (v146 release page)
  - https://plus4world.powweb.com/tools/Krills_Loader (v146 description; download path /dl/tools/loader-v146.zip, downloaded and extracted)
  - Protocol doc in the archive: loader/docs/Protocol.txt; v146 docs: docs/Protocols.txt, Usage.txt.
- licence or usage statement (verbatim) + URL; any reuse evidence
  - Licence, verbatim from loader/README in loader-v194.zip (https://csdb.dk/getinternalfile.php/238373/loader-v194.zip). VERIFIED:

```
TL;DR: Please give credit, thanks.

When using this software or a derivative thereof in own works, please give
appropriate credit, e.g., "Loader by Krill".
This does not need to be on prominent display within the actual running
production itself, but at least in an accompanying note, readme, info file,
directory, or a similar means of attribution contained in the official release
archive or disk images.
Exclusively external credits on websites or online forums are no such instances.

Copyright 2022 Gunnar Ruthenberg

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice in
an appropriate form, e.g., "Loader by Krill" displayed anywhere in the actual
production itself and/or accompanying documentation contained in the official
release archive or disk images.

3. Neither the name of the copyright holder nor the names of its contributors
may be used to endorse or promote products derived from this software without
specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Third-party software (particularly in loader/tools and loader/samples/resources)
and its derivatives (particularly in loader/src/decompress) are not affected and
retain their original licenses.
```

  - v146: no licence file in the archive; no copyright header in its own sources. The Plus/4 World page says: "It comes with no strings attached." (https://plus4world.powweb.com/tools/Krills_Loader). VERIFIED. Its only licence text is therefore that statement, not a formal licence.
  - Third-party tools (cruncher sources and binaries in loader/tools and loader/samples/resources) keep their own licences, per the README. VERIFIED.
  - Note for the Breadbin policy: the v194 licence is a 2-clause-plus-attribution BSD-style licence with an attribution request ("Loader by Krill"). It is a permissive licence, so a clean-room reuse under it is compatible with MIT, but attribution must be kept. This is a reading of the text, not legal advice.
  - Reuse evidence (csdb comments, all VERIFIED in the csdb pages):
    - Krill, 24 Nov 2022: "Consider https://github.com/thierer/sd2iec for SD2IEC firmware with proper support for this loader (current and relevant earlier revisions)."
    - Krill, 14 Sep 2024: a format change (see known problems).
    - Several demos report use: Swoffa ("We used it in the 'Goats who stare at men'-demo"), Radiant (cruncher backend in his framework), DJ Gruby (tutorials in Attitude #15).
    - Burglar (7 May 2013) says of Krill's loader: "the gold standard for demoloaders" and that his own loader "supports only 1541, and only exomizes".
    - Krill (13 Aug 2018): a new version 164 was announced; v194 is the later release present on csdb.
    - Save support: no csdb comment about save; save is in the v194 README (see below).
- host (C64) side: resident size in bytes; zero page / memory used; needs IRQs off? screen blanked? works with interrupts and screen on? sprites?
  - Resident size (README, Features): $01f9 bytes for combined load+depack with ZX0 (fits in $0200..$03f8); $01fb bytes with TSCrunch (fits $0200..$03fa); $e0 bytes for load-raw only. VERIFIED (README). The sizes are the README's stated figures, not re-measured.
  - Install routine is separate and relocatable; the README says the install routine's location and the resident and transient portions are free to relocate (RESIDENT=, INSTALL=, TRANSIENT= make parameters, e.g. `make prg ZP=e8 INSTALL=1000 RESIDENT=ce00`). VERIFIED.
  - Zero page: variables are at loader_zp_first..loader_zp_last (in loadersymbols-c64.inc); ZP base is set by the ZP= build option (example ZP=e8). The README says these addresses must not be written while loading. Exact default count: UNVERIFIED (the list was not extracted).
  - Needs IRQs off? No. The README: "IRQ/NMI/DMA/sprites/badlines are allowed without restrictions." VERIFIED. The install routine calls KERNAL routines that do SEI/CLI, so set interrupt handlers after install. VERIFIED.
  - Screen blanked? Not required by the README; no screen blanking is mentioned. VERIFIED by absence in the text (weak).
  - Works with screen on, sprites and badlines: yes per the README sentence above. VERIFIED.
  - Bus: the loader uses CIA2 port $DD00 for the IEC lines; the VIC bank is set via $DD00 with the upper 6 bits zero. The README says any value may be written to $DD00 while the loader is idle. VERIFIED.
  - Host side is fully inert when idle (README). VERIFIED.
  - v146 feature list also mentions polled loading and non-blocking loading using CIA timer NMIs. VERIFIED (plus4world page).
- drive side: size in bytes; where it runs ($0300..?), uploaded how (M-W/M-E), which ROM routines it calls (addresses)
  - Size: not measured. The drive code is assembled with `.org 3` (drivecode1541.s line ~122). Its own memory map: zero-page and the block buffer at $0100 (used as stack/block buffer), a decode table at $0700 (effective from $0722), and the watchdog handler assert at $0700. So the drive image spans roughly $0003 to $07xx. Exact byte count: UNVERIFIED (no assembler was run).
  - Upload: install.s writes the code with the DOS memory-write command ("m-w") in blocks, then runs it with "m-e" / JMP $0300 (install.s lines ~383-400 and ~1048-1085). Installation starts the drive code at $0300 for the silencing and mute code (`drvmuteme` jumps to $0300; `drvsilence` writes at $0300). VERIFIED.
  - ROM routines/addresses: the drive side itself does not call DOS ROM routines in the data path (it uses its own GCR decoding and VIA timers $EF00-region counters, per the comments). It does use the drive ROM reset vector `jmp ($fffc)` in the mute and reset code (install.s line ~1168; drivecode1541.s). VERIFIED.
  - Host-side detection reads drive ROM bytes with "m-r" at $E5C6, $C002, $EAA3, $E5B7 and $FEF0 (install.s getmodel, lines ~900-1020) to tell 1541 / 1541-C / 1541-II / 1541U apart. VERIFIED.
- disk format: normal 1541 DOS disk/arbitrary track+sector, or custom? file-level or sector-level API?
  - Default (v194): standard DOS format, file-level. Files are found by name via the directory (track 18; filenames 0-terminated, 2-16 chars, FILENAME_MAXLENGTH setting). The loader's README: "full standard Commodore DOS format compatibility". VERIFIED.
  - It is read-only at the directory level: "a read-only disk driver (with limited saving capabilities)". VERIFIED.
  - Arbitrary track/sector: v194 has no track/sector API. The v194 config has only DIRECTORY_NAME-style addressing (DIRTRACK, FILENAME_MAXLENGTH). VERIFIED by absence in config.inc and loader.inc.
  - v146: has a compile-time FILESYSTEM option, DIRECTORY_NAME or TRACK_SECTOR (include/config.inc). In TRACK_SECTOR mode, the host sends track and sector to the drive (resident.s sends track then sector bytes). Krill's docs (Usage.txt) describe "loading via track and sector". VERIFIED. This was removed in v194 (grep for TRACK_SECTOR finds nothing in v194 loader sources).
  - Shadow directory: the loader can keep its own directory on another track (DIRTRACK != 18), so the visible directory can be hidden. VERIFIED.
  - Custom drive code: "The drive's CPU may run custom code provided by the user." (README). Sample: samples/drivecode. VERIFIED.
- save/write support (yes/no/limited; how)
  - Limited. Save overwrites an existing file in full with the save routine: "The file to save must exist on disk prior to saving. I.e., it is overwritten in its entirety, replacing the original file." It needs the save build (`make save`, with TRANSIENT region and an $0800-byte drive-code scratch buffer). New files, formatting, and DOS-level writes are not supported ("it cannot save to newly-created files, format disks"). VERIFIED (README, Saving files).
- transfer scheme: bits per step, lines used (CLK/DATA/ATN), handshake or timing based, sync with raster?
  - Two bits per step, with ATN as a third clock/signalling line: "2bit+ATN protocol (72 cycles per byte)". Host clocks bit pairs out on CLK OUT/DATA OUT and receives on ATN OUT / ATN IN. The handshake is by the lines in docs/Protocol.txt (a sequence of request, ready, ack, busy states). VERIFIED.
  - v146 also had "asynchronous 2-bits+ATN and 2-bits+resend (experimental)" transfer protocols, which allow arbitrary interruptions. VERIFIED (plus4world).
  - Sync with raster: no. The loader polls and is asynchronous with respect to the raster; no raster sync is needed. VERIFIED by README (IRQ/badlines allowed). The Protocol doc is the authority.
- speed: bytes/second (give number and where from)
  - Maximum raw loading speed on 1541: 7.7 kB/s (~20x); typical about 7 kB/s (~18x). Source: loader/README, Features. VERIFIED (as stated by the author).
  - Native interleave for uncompressed files: 3 revolutions per track on tracks 18+, 4 on tracks 1-17; compressed: 4 revolutions across the disk. README. VERIFIED.
  - v146 figures: max 4.0 kB/s uncompressed (4+1 revolutions per track); combined load+decompress with Doynamite about 8.5 kB/s. Source: plus4world page. VERIFIED.
  - Benchmark chart: Spindle's own comparison (v3plot1.png, "Code (BASIC + Kernal)") shows a Krill 184 with Bitnax at roughly 5,900 bytes/s at 100% raster time left for the loader and about 1,300 bytes/s at 20%. This is version 184, not 194, and is Spindle's measurement. VERIFIED (chart read).
- drive compatibility: stock 1541 ROM, JiffyDOS drive ROM, 1541-II, 1571, 1581, Ultimate emulated 1541, multiple drives on the bus
  - Natively supported (README, v194): 1541 (all variants), 1570/1571, 1581, CMD FD, and 1541U (Ultimate). VERIFIED.
  - Stock 1541 ROM: yes (the primary target).
  - 1541-II, 1541-C: detected and handled (install.s getmodel). VERIFIED.
  - 1581: supported natively, but a bug was reported on csdb (see known problems). VERIFIED.
  - Multiple drives: "multiple drives on the bus are allowed, but loading only from the primary drive" (README). VERIFIED.
  - Non-native fallback: KERNAL fallback for devices such as SD2IEC (slow), IDE64 (fast) and netload (LOAD_VIA_KERNAL_FALLBACK option; requires DIRTRACK 18). VERIFIED.
  - JiffyDOS drive ROM: UNVERIFIED. No text mentions JiffyDOS support. The install code comment says a drive whose ROM bytes do not match the 1541-C/1541-II signatures is treated as 1541-II "so as not to detect JiffyDOS, SpeedDOS etc. as 1541-C but 1541-II instead" (install.s ~line 942). That shows the authors considered custom DOS ROMs, but no JiffyDOS test is recorded. Krill's csdb comment recommends sd2iec for proper support of the loader (for the 2022 version) and does not mention JiffyDOS. The drive-side code is custom and uploaded, so a JiffyDOS drive's own job loop may still matter. Test on hardware before relying on it.
- known problems
  - csdb, 6 Oct 2026 (user alwyz): on a 1581, a file whose first block is on track 80 cannot be loaded; the user patched a byte in the disk image. Posted as a comment on the v194 page. VERIFIED (comment text).
  - csdb, 14 Sep 2024 (Krill): a bitstream format change (destination pointer byte order and control-bit shift direction); the reporter (Burglar) said Dali 0.3 is supported, not Dali 0.3.2. VERIFIED.
  - README limitations: 16-bit filename hashes can collide (two names may load the wrong file silently); there must always be at least 2 directory entries; an invalid final directory block (starts with 00 00) locks the loader in a retry loop; changing the directory block count breaks it unless a shadow directory is used; compressed files may overwrite a few bytes after their range. VERIFIED.
  - Known platform issue on the 1541 with recent ld65 for the build tools (csdb, Dec 2014): loadersymbols generation; fixed by a script in v194. VERIFIED (csdb comments).
  - Build: needs cc65/ca65 and perl; the v194 build outputs are prebuilt in loader/build. Not executed.

---

## Loader B: Spindle (Linus Akesson, lft)

Version: Spindle 3.1 (spindle-3.1.zip; the operator's handbook in the archive is "rev. 2, Spindle 3.1"). The 3.0 release was announced with the Gubbdata 2021 demo (4 Jul 2021 news post). Date of 3.1 release: UNVERIFIED (not stated on the page read).

- name / author / version / date
  - Spindle 3.1, by Linus Akesson (lft). Handbook rev. 2. VERIFIED.
  - Release 3.0 post: "Posted Sunday 4-Jul-2021". 3.1 changelog: "Reintroduced NTSC compatibility." Date of 3.1: UNVERIFIED.
- source URL(s) (code, docs)
  - https://linusakesson.net/software/spindle/v3.php (v3 page; the http:// redirect is to this page)
  - https://hd0.linusakesson.net/files/spindle-3.1.zip (downloaded and extracted; src/, template/, examples/, README, COPYING, spindle-handbook.pdf)
  - https://linusakesson.net/software/spindle/v3manual.pdf (same handbook as the archive's spindle-handbook.pdf; checked with cmp)
  - https://hd0.linusakesson.net/files/spindle-3.0.zip (prior release, not read)
  - https://csdb.dk/release/?id=53729 and https://csdb.dk/release/?id=205537 (linked from the page; not read)
- licence or usage statement (verbatim) + URL; any reuse evidence
  - COPYING, verbatim (spindle-3.1.zip, COPYING; also https://linusakesson.net/software/spindle/v3.php "License" section). VERIFIED:

```
The code in the "src" directory is released under the following conditions
(known as the MIT license):

	Copyright (c) 2013-2022 Linus Akesson

	Permission is hereby granted, free of charge, to any person obtaining a
	copy of this software and associated documentation files (the
	"Software"), to deal in the Software without restriction, including
	without limitation the rights to use, copy, modify, merge, publish,
	distribute, sublicense, and/or sell copies of the Software, and to
	permit persons to whom the Software is furnished to do so, subject to
	the following conditions:

	The above copyright notice and this permission notice shall be included
	in all copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
	OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
	MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
	IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
	CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
	TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
	SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Everything in the "template" and "examples/pefchain/spindlelogo" directories is
hereby declared to be in the public domain.

Other files in "examples" may be redistributed in their current form.
```

  - Also from the README and the handbook (verbatim): "Go ahead and use this in your demos! You can include the spindle logo (example-pefchain/spindlelogo) if you like, but you don't have to. I would appreciate some credit, e.g. "Loader by lft"." VERIFIED.
  - Note: the MIT grant covers "src" only. "template" and "examples/pefchain/spindlelogo" are public domain, and other "examples" may be redistributed in their current form. VERIFIED.
  - Reuse evidence: the page links the demo "Revelations Delivered" (csdb 205537 / 53729 pages linked, not read). The page comments include a user asking about using Spindle as a general fastloader (answered: "the short answer is no", April 2022). The handbook and release notes credit Krill and Monte Carlos as sources of inspiration for drive silencing. VERIFIED (text on the page and handbook).
- host (C64) side: resident size in bytes; zero page / memory used; needs IRQs off? screen blanked? works with interrupts and screen on? sprites?
  - Resident: one page of RAM ($0200-$02FF by default, configurable with -r). Buffer page $0300-$03FF by default (-b). Zero page: five consecutive bytes $F4-$F8 by default (-z). The handbook says these are free between loader calls. VERIFIED (handbook 1.1; features list: "one resident page, one buffer page, and five zero-page bytes").
  - Resident size in bytes: 256 (one page). VERIFIED.
  - Interrupts: at initialisation Spindle disables CIA interrupts, sets SEI and writes 35 to $01. You should leave $01 at 35 when making loader calls. It writes 34 only for shadow-RAM loads ($D000-$DFFF). VERIFIED (handbook 1.3).
  - Interrupts during loader calls: the handbook's example runs a raster-IRQ music player while the main program makes loader calls; it says you only need to save and restore $01 in your interrupt handlers if they run during a shadow-RAM load. VERIFIED (handbook 1.3, 1.4).
  - Sprites, screen blanking, badlines: not specified in the handbook as a requirement. Sprite handling is mentioned in the timing notes for effect interrupt start (handbook 2.4: "If you enable sprites ... the length of the" interrupt prologue must change), which concerns interrupt timing, not loader constraints. UNVERIFIED for screen on/off.
  - Loading to shadow RAM under I/O: transparent (handbook 1.2). VERIFIED.
  - Bank select: VIC bank must be selected with $DD02, not $DD00 (handbook 1.3). VERIFIED.
- drive side: size in bytes; where it runs ($0300..?), uploaded how (M-W/M-E), which ROM routines it calls (addresses)
  - Size in bytes: not measured. The drive code's own memory map (src/drivecode.s header): zero page $00 for the GCR loop ($30-$91), stack $0100 used as block buffer, code at $0200, fetch code at $0300, misc $0400, GCR tables $0500, init/buffer 1 at $0600, buffer 2 at $0700. So the drive image covers the drive RAM $0000-$07FF. The compiled byte count (drivecode.bin, built by xa65): UNVERIFIED (no assembler was run).
  - Upload: stage1.s uses "M-E" with $0205 (cmd_install, `.byt "M-E"`, `.word $205`) and "M-W" with $0400 and $20 bytes for the silence code ("M-W",$00,$04,$20). The first drive code block is loaded into buffer 3 at $600 by the bootstrap. The drive code is supplied as a stage1 block read by the drive's own DOS. VERIFIED (src/stage1.s lines ~215-235, 547).
  - ROM routines: drivecode.s line ~167 `dosreadblock: sta $f9; jmp $d586` calls the 1541 ROM routine at $D586 for DOS block reads (used by drivecode.s lines 78-82 during initialisation). The drive also uses the reset vector `jmp ($fffc)` (drivecode.s line ~784 and ~1130). VERIFIED (source). The meaning of $D586 is inferred as the DOS read-block routine: UNVERIFIED for the exact routine.
  - Drive VIA use: drive-side ports at $1800 (bit 7 ATN read at start: "bit $1800 ; Wait until the host is up (atn held)") and BUSY indicator writes to $1800 (drivecode.s line ~87). VERIFIED.
- disk format: normal 1541 DOS disk/arbitrary track+sector, or custom? file-level or sector-level API?
  - Custom, but coexists with DOS. Spin "uses its own D64-compatible storage format, [and] respects and coexists with the native Commodore disk structure" (handbook 1.5). The bootstrap is an ordinary PRG on the disk, loaded by the KERNAL LOAD (stage1 header: "the small bootstrap prg loaded by the kernal"). VERIFIED.
  - The data sectors are owned by Spindle and placed in whole tracks; the handbook shows the free-block count "blocks free (538 for DOS)". Non-Spindle files can be added, using c1541 or similar. VERIFIED.
  - API: load-script based (chunks: filename, load address, offset, length, per "job"), with seeking to labels. There is no user-facing track/sector read API in the handbook. VERIFIED (handbook 1.2, 1.6).
  - Arbitrary track/sector on a normal 1541 disk: NO for a disk not written by Spin. The loader reads sectors by header IDs on the disk Spin laid out (the drivecode has "headerless scanning" and "triple sector buffers", handbook 1.9 and features). Reading a Spin-written disk with its sector layout is the point. A normal disk with arbitrary files is not loadable by Spindle's script. VERIFIED from handbook; the exact header-scan code path not traced.
  - 40-track mode: yes (--40). VERIFIED.
- save/write support (yes/no/limited; how)
  - None documented. The handbook has no save or write-to-disk feature for the loader. The loader's documented operations are loading, seeking and silencing. The drive code's only uploads are M-W and M-E for code; no write command was traced in drivecode.s (UNVERIFIED that no write path exists at the code level). VERIFIED for the handbook.
- transfer scheme: bits per step, lines used (CLK/DATA/ATN), handshake or timing based, sync with raster?
  - Custom serial protocol over the IEC lines, timing based: "Spindle uses a very fast serial protocol (18 cycles per bit pair) when transferring data from the drive ... When Spindle detects that other drives are present on the bus, it will automatically switch to a slower serial protocol (19 cycles per bit pair)" (handbook 1.9). VERIFIED.
  - Bits per step: two bits per step (bit pair) as stated. VERIFIED.
  - Lines: IEC CLK, DATA and ATN; the drive reads ATN from port $1800 (drivecode.s line ~150), and the drive code sets output lines through $1800. Which exact line is which is UNVERIFIED in detail. Handshake: timing-based (cycle counts per bit pair in comments; a "safety" margin $F4 in zero page inside the drive code). VERIFIED for the cycle counts.
  - Other drives: Spindle silences 1541, 1541-II, 1570, 1571 and 1581 on the bus and restores them on C64 reboot (reset detection). VERIFIED (handbook 1.9).
  - Raster sync: the loader is interrupt-independent in the handbook's model; sync to raster is the effect's business. Not claimed by the handbook. UNVERIFIED.
  - Streaming and simulated timing: "Simulated playroutine timing" in the build tools (handbook features). VERIFIED.
- speed: bytes/second (give number and where from)
  - Benchmark chart (Spindle's own measurement, handbook site https://linusakesson.net/software/spindle/v3.php, image v3plot1.png, "Code (BASIC + Kernal)", 16 KB set, median of eight loads): Spindle 3.0 about 6,800 bytes/s at 100% raster time left for the loader, about 5,100 at 65%, about 1,850 at 20%. Spindle 2.3 about 6,000 at 100%. VERIFIED (chart read; values estimated from the plot axes). Estimates, not exact.
  - Second chart (v3plot2.png, FLI picture data set) not read: UNVERIFIED for that set.
  - Speed is stated relative to raster time left for the loader, so there is no single number.
- drive compatibility: stock 1541 ROM, JiffyDOS drive ROM, 1541-II, 1571, 1581, Ultimate emulated 1541, multiple drives on the bus
  - Stock 1541: yes (the target). Expected to work with 1541-II, 1570, 1571 and 1581 as silencing targets (handbook 1.9). VERIFIED for silencing list; 1571/1581 full loading not claimed beyond the features list.
  - Multiple drives on the bus: supported; silenced, with a slower bit pair when other drives are present (handbook features and 1.9). VERIFIED.
  - Ultimate (emulated 1541 or Ultimate hardware): not mentioned in the handbook. UNVERIFIED.
  - JiffyDOS drive ROM: UNVERIFIED. The drive-side code calls the drive ROM's $D586 (DOS read block) and the reset vector at $FFFC (drivecode.s), so a custom drive ROM that moves or changes those routines could break it. Test on hardware before relying on it.
  - Spindle's drive-side "silence" code is uploaded over M-W and modifies the drive's job loop, so a drive with a different DOS may behave differently. UNVERIFIED.
- known problems
  - Handbook 1.9: "Note that in the Vice emulator, drive silencing currently only works when the demo is loaded from the highest-numbered drive. This problem is not present on real hardware." VERIFIED.
  - C128DCR: high bus capacitance; an external 1541 may be needed to enforce the slow protocol (handbook 1.9). VERIFIED.
  - Spin trade-offs: padding sectors and "--squeeze" option trade disk space against speed (handbook 1.9). VERIFIED.
  - Comment on the page (Sep 2025, anonymous): the user reported a pink screen and a high-pitched whine with lft-revolutions-delivered.d64 on NTSC, which contradicts the 3.1 note "Reintroduced NTSC compatibility." Unresolved in the page read. VERIFIED (comment text), not reproduced.
  - Handbook: the loader only supports the Spin layout; the demo must be a trackmo (linked disk), not a general file loader. The lft comment says it is "not" a general-purpose fastloader. VERIFIED.

---

## Cross-check of the two loaders against the Breadbin criteria

- Reads arbitrary track/sector on a normal 1541: Krill v194 does not (directory-based only; v146 had a TRACK_SECTOR build option). Spindle does not (its own layout, via load scripts). Krill is the closer fit for normal DOS disks.
- Save: Krill v194 has limited overwrite-in-place save (existing files only). Spindle has none.
- Drive RAM: Krill's drive code is installed at $0300 and uses the full drive RAM for its own buffers; Spindle's covers $0000-$07FF. Byte counts UNVERIFIED for both.
- Host resident: Krill $01f9 bytes (ZX0 combined), Spindle 256 bytes plus a 256-byte buffer page and 5 zero-page bytes.
- Licence: Krill v194 is a permissive BSD-style licence with attribution, with a v146 "no strings attached" statement. Spindle is MIT for src, public domain for template, with an attribution request. Both are compatible with an MIT repo in terms of text; this is a reading, not legal advice.
- Speed: Krill claims 7.7 kB/s max (7 typical) on 1541 (its own figure). Spindle's own chart shows about 6,800 bytes/s at full raster time for the loader. The two are not measured on the same rig.
- JiffyDOS: both UNVERIFIED. Test on hardware.
