# 1541 sector write from uploaded drive code: what public sources do

Research only. Fetched 2026-10-31 by Bash curl (pages saved under `.../research2/pages_save/`). No downloaded code was executed.

Legend: VERIFIED = read directly in a fetched source. UNVERIFIED = stated by a source but not checked, or claimed in the task without a source.

## Sources and what each shows

### 1. pagetable.com, "The story of 15 Second Copy for the C-64" (Mike Pall, 2011)
URL: https://www.pagetable.com/?p=656
- VERIFIED: this is a parallel-cable copier that moves raw GCR between C64 and 1541. It does not use the DOS job queue or the ROM write routines. The 1541 side loops on `bvc *` / `clv` (byte-ready from the SO pin), `eor $1c01`, and `sta $1c01`, toggling the serial lines through `$1800` (`inc/dec $1800`).
- VERIFIED: the write loop XORs bytes coming from the C64 and writes them to the shift register at `$1c01`, with a 5-byte checksum kept at `$80-$84` and verified by XOR to zero.
- VERIFIED: the article gives only the inner loops, not the full copier. No write-protect check, no header search, no error codes, no LED or motor handling are shown.
- Licence: "Published with permission." No code licence is stated. Excerpts are under 15 lines.

### 2. ELoad (Thomas Giesel), chaco repo, `chtransfer/libs/eload/src/`
Note: the URL in the task, `svn.icomp.de/svn/chaco/...`, now returns a redirect page only (VERIFIED). Source moved to GitLab: https://gitlab.icomp.de/chameleon-dev/chaco/-/raw/master/chtransfer/libs/eload/src/drive_1541_write.s (and `drive_1541_read.s`, `drive_1541.s`, `drive_1541_inc.s`, `eload_macros.s`).

This is the best source for the question. It is a drive-side write routine uploaded with M-W and run at `$0500`.
- VERIFIED job flow: the drive receives a job from the host. Job 1 is write, job 2 is track checksum, anything else returns. These are ELoad's own codes, not DOS `$90`.
- VERIFIED write-protect: `lda $1c00 / and #$10 / bne ok`, error `ELOAD_WRITE_PROTECTED = 8`.
- VERIFIED header search: `drv_1541_search_header` (helper in `drive_1541.s`), then skip the 9 header-tail bytes.
- VERIFIED write mode: `$1c03` port A to output, `$1c01` = `$FF` sync, `$1c0c = $ce` (write), then 5 sync bytes, then 69 bytes from `$0100+$bb..$ff` (the buffer tail at `$01bb`), then 256 bytes from `buffer` (`$0700`). Ends with `$1c0c = $ee` (read) and `$1c03` back to input. So it writes one raw 325-byte GCR data block after the existing header. It does not write the header.
- VERIFIED: GCR is not encoded on the drive. The host sends already-encoded GCR, and the drive writes it byte for byte.
- VERIFIED: no read-back verify in the write path. The checksum (`checksum16`) is for the read path.
- VERIFIED motor and LED: `drv_1541_prepare_read` switches on the motor (`jsr $f97e`) and the LED (`ora #$08` on `$1c00`). Motor off is `jsr $f98f`, LED off is `and #$f7` on `$1c00`.
- VERIFIED status back to host: A (code), then job track and sector+1.
- ROM addresses called here: `$F97E` (motor on), `$F98F` (motor off), `$FE00` ("head to read mode", per this source), `$FA2E` (head step), `$F934` ("header to GCR"), and `$FED1`/`$FED6` (sectors per zone table), plus the job-exec routine.
- UNVERIFIED: none of these ROM contents have been checked. The ROM is not in the repo and must not be copied in.
- Zero page used (VERIFIED from `drive_1541_inc.s`): job code `$04`, job track `$0E`, job sector `$0F`, speed zone `$06`, status `$08`, `zptmp $C1`. This conflicts with the task's premise of a job code at `$90` with track and sector at `$06-$0B`.
- Speed: "26 to 32 cycles per byte" depending on zone (ELoad comment). VERIFIED as a comment, not measured.
- Licence (verbatim, zlib-style): "This software is provided 'as-is', without any express or implied warranty. ... Permission is granted to anyone to use this software for any purpose, including commercial applications, and to alter it and redistribute it freely, subject to the following restrictions: 1. The origin of this software must not be misrepresented ... 2. Altered source versions must be plainly marked as such ... 3. This notice may not be removed or altered from any source distribution." Copyright: "(c) 2011 Thomas Giesel". This is permissive, not GPL/LGPL. It still needs attribution in the file header, and the policy decision is the user's.

### 3. codebase64.net
- `base:1541_disk_drive` does not exist (VERIFIED: "This topic does not exist yet"). Also not present: `base:1541_disk_drive_routines`, `..._source`.
- Existing pages: `base:fastloaders` (https://codebase64.net/doku.php?id=base:fastloaders) and `base:formatting_disks` (https://codebase64.net/doku.php?id=base:formatting_disks).
- VERIFIED, formatting_disks, quoting Krill: "If speed is not an issue, just use the built-in format: openN,8,15,"n:disk,id"". Also: "many fast-formatters skip this step completely and use hardcoded values for an assumed rotation speed of 300rpm." This explains why some fast formatters break drives that are off-speed.
- VERIFIED, fastloaders: discusses checksumming and GCR decoding on the drive side. No write code.
- Licence: wiki footer says "CC Attribution-Noncommercial-Share Alike 4.0 International". This is NC and SA, so it is incompatible with the repo's MIT policy for code. Use only as prose reference.

### 4. theoasisbbs.com, "1541 Fast Format Explained by Commodore History"
URL: https://theoasisbbs.com/1541-fast-format-explained-by-commodore-history/ (summary of a video)
- VERIFIED summary claims: the routine uploads code to drive RAM with M-W and starts it. It "still uses the same 1541 ROM encoding routines for header and data blocks". It skips the write-protect check and the pre-fill of sync bytes, uses a fixed 8-byte intersector gap, and skips the verify pass. The article calls it Mike J. Henry's 15-second format.
- Checked in code (below): no write-protect test and no read-back verify. The sync pre-fill claim was not checked in code.
- Source link: https://github.com/commodoreihs/15_second_format

### 5. Mike J. Henry / Alf Maier 15 Second Format disassembly (repo)
Cloned read-only (shallow) to `/home/user/commodoreihs/15_second_format` (outside scratchpad; attached through the read path, nothing pushed). Files: `15_second_format.asm` (C64 side, 6.8KB), `15_second_format_drive_code.asm` (drive code, 12.6KB). Disassembly by Dave McMurtrie, 2026-04-04.
- VERIFIED: the drive code is uploaded with 18 M-W commands to `$0500` (540 bytes to `$071B`). It is started by `UC:` = U3 = JMP `$0500`.
- VERIFIED: it is a whole-track formatter, not a single-sector writer. It runs stepper moves, then per sector writes sync `$FF` x5, a GCR header from `$0300` (10 bytes), gap `$55` x8, sync `$FF` x5, 69 bytes from the stack page `$01BB`, 256 data bytes from `(DATA_PTR),Y`, gap `$55` x8. It writes a `$00` data block with 256 zeros.
- VERIFIED: uses ROM routines `$F24B` (sectors per zone), `$FE30` (header GCR convert, zone 3), `$FDE5`/`$FDF5` (GCR buffers), `$F5E9` (GCR encode, zone 4), `$F78F` (setup write pointers), `$FE00` (job exec), `$F005` (sync wait), `$EE56` (job done).
- VERIFIED: no write-protect test (`$1C00` is only read to set bit 2, motor on). No verify pass.
- CONFLICT, UNVERIFIED: `$FE00` is "head to read mode" in ELoad but ROM_JOB_EXEC in this repo. `$F934` (ELoad) versus `$FE30` (this repo) are different header-to-GCR routines. The ROM is not in the repo, so one of these disassemblies is wrong or the labels differ. Check against a ROM dump the user owns before use.
- Licence: NO LICENCE FILE. README: "All credit for the code goes to Mike J. Henry and Alf Maier." Default copyright applies; not adoptable under policy.

### 6. `bin2gcr $F77F`
- Not in any fetched source. UNVERIFIED and not found. Do not use this address without a ROM check.

## Answers

Job queue `$90`: no fetched source shows a `$90` write. ELoad and the 15-second format both drive their own write path and only use the ROM job loop for helper actions (ELoad: seek `$B0`; the format: job-done hand-back). The premise of `$06-$0B` for track and sector conflicts with ELoad's `drive_1541_inc.s` (`$0E`, `$0F`). UNVERIFIED.

Simplest correct way for ONE normal-format sector, keeping DOS consistent (BAM left to host). This is ELoad's pattern; it is what the sources show, but not tested on hardware:
1. Host: pick the sector, encode the data block to GCR with the host's own encoder (sync not needed; the drive adds it). Compute the data checksum on host. Not in the sources; UNVERIFIED.
2. Drive: `lda $1c00 / and #$10 / beq wprot` (VERIFIED).
3. Motor and LED on (VERIFIED in ELoad).
4. Search the header for T/S with the header-search helper (VERIFIED in ELoad).
5. Skip 9 header-tail bytes, `$1c0c = $ce`, write 5 sync `$FF`, then the 325 GCR bytes (VERIFIED).
6. `$1c0c = $ee`, `$1c03 = 0`, motor and LED off (VERIFIED).
7. BAM is not written on the drive. The host updates the BAM only if the sector was not already allocated. Header is untouched, so DOS consistency holds only if the sector was already formatted.

Error codes: ELoad uses 1 OK, 2 header not found, 3 no sync, 4 sector not found, 8 write protected, 255 unknown. The comment says these match 1541 job codes. UNVERIFIED.

Verify: none in ELoad's write path. Add a read-back and checksum if required (ELoad reads back via its read path, UNVERIFIED for this use).

Speed: 26-32 cycles per byte by zone (ELoad comment). Not measured.

## Licence summary

| Source | Licence | Policy fit |
|---|---|---|
| ELoad (Giesel) | zlib-style permissive, quoted above | Not GPL/LGPL. Needs attribution. User decision. |
| 15 Second Format repo | None; README credits Henry and Maier | Not adoptable as code. |
| pagetable article | "Published with permission." | Prose and short excerpts only. |
| codebase64 wiki | CC BY-NC-SA 4.0 | Prose reference only; NC and SA conflict with MIT. |
| Oasis article | Summary of a video | Prose reference only. |

## Not reached or not checked
- `drive_1541_read.s` was read; `drive_1541.s` was grepped, not read in full.
- The linked linusakesson.net handshake article (pagetable) was not fetched.
- The 1541 ROM was not checked; no ROM addresses are verified against ROM contents.
- The GCR encoder on the host side (ELoad's C64 part) was not fetched.
