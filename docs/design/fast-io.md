# Fast disk I/O: paper design

Status: paper only (2026-10-31). No kernel changes. The hardware session is busy with IEC corner cases and has no VICE access yet, so everything here that depends on timing is a hypothesis to be checked, not a measurement. Companion to "Disk speed" in `docs/roadmap.md`, which holds the measured baseline (standard protocol: about 1.8 ms per byte, 0.55 s per block, boot about 70 blocks).

## 1. What we want

- Faster reads **and writes** on 1541-class drives (stock and JiffyDOS), without making the core depend on either.
- Code small enough to be worth it: the kernel has 6,079 bytes of room today, and M0-7 will squeeze it.
- Everything probed at run time (platform tiers: Classic must still boot on the plain protocol).
- Prefer code we may legally adopt and then compact over reimplementation.

## 2. The candidates

| # | Approach | Host code | Needs in the drive | Read | Write | Licence of what we would adopt |
|---|---|---|---|---|---|---|
| A | Standard serial (today) | in `iec.s` | nothing | ~0.4 KB/s | same | ours (MIT) |
| B | **JiffyDOS** byte protocols (send, receive, LOAD) | ~740 bytes in the stock JiffyDOS KERNAL (per cbmbus_doc) | JiffyDOS drive ROM | ~2.1 KB/s measured | **yes** (send is symmetric) | none usable: proprietary ROM; clean-room only (see 4) |
| C | **Drive-side uploaded loader** (`fastboot1541`, M-W/M-E) | ~100 bytes host, ~130 bytes drive | any 1541-class drive, stock or JiffyDOS (calls ROM routine `$D586`; must be checked per ROM) | several KB/s, raster-synchronised | not in the original; a write loop is the mirror image | **permissive** ("do anything, credit Michael Steil, email appreciated") |
| D | REU block cache | ~200 bytes | nothing | cache hits are DMA speed | write-through | ours |
| E | UCI DOS target (file backend) | S10/S11 | Ultimate | no bus at all | yes | ours; documented |
| F | Cartridge fast loaders (Epyx, Action Replay...) | resident in the cartridge | their own drive code | fast | some | not adoptable |
| G | sd2iec / SD2IEC-family fast protocols | their firmware is the *device* side; the host side is in the Jiffy/Dreamload/EPYX code of the KERNAL replacements | n/a | n/a | n/a | **GPLv2**: cannot be copied into an MIT tree without relicensing the whole kernel |

Honest ranking for *this* project: E (principal, already decided) and D (cheap, fixes the hardware bench), then C (it is the only one that is adoptable code and helps stock drives), and B last and optional.

## 3. What is worth adopting

### 3.1 `fastboot1541` (C): adopt, with credit

`start.s` is 199 lines; the whole scheme is one sector holding both the drive code and the host receive loop. Notes from reading it:

- The host sends `M-E` through an ordinary open on channel 15 using the KERNAL `filnam`/`open` (`$FDF9`, `$F34A`): we would use our own `iec_ch_open`.
- The drive routine reuses ROM routines (`$D586` read-sector) so only the transfer loop is new. This is the compatibility risk: the JiffyDOS drive ROM moved things, and `$D586` has to be confirmed in both ROMs. Local disassembly of both is available to the hardware session; WP2 in `docs/wip.md` is the experiment that answers it.
- Transfer: 2 bits per step on CLK/DATA, raster-synchronised (waits for a good raster line so badlines do not steal cycles in the window), interrupts off, screen state matters. Bits use the same two lines as ATN-free serial.
- It is a *boot* loader (fixed track-18 table, `seccnt` sectors). For the kernel we need the generalisation: a drive routine that takes `track, sector` pairs (or reads them from the command) and streams 256 bytes per call; the host side becomes `iec_fast_read(track, sector, buf)`. Size estimate: host 120 to 160 bytes, drive 130 to 180 bytes (uploaded, so it costs *no kernel space* apart from storing the image, ~170 bytes in RODATA).
- Writes: the mirror routine (host sends 256 bytes, drive loops writing to the buffer, then calls the DOS job queue (exact ROM entry points to be confirmed in the disassembly; not checked yet)). Same size class. This must be proven on hardware; the DOS job queue protocol (job codes at `$00-$05`, track/sector at `$06+`) is documented in cbmbus_doc "3 Commodore DOS" and the 1541 ROM.

Why it is the best fit: it works for stock and JiffyDOS drives alike, needs no knowledge of JiffyDOS, and its cost is almost all in the drive. Its limits: not for 1581 or Software IEC (those take other paths; NTH), and it replaces the *block* layer, not the file layer, which matches how Breadbin uses disks (`blk.s`, b-block reads).

### 3.2 JiffyDOS (B): learn from, do not copy

The ROM is proprietary. We use two clean public descriptions: Michael Steil's `cbmbus_doc` ("7 JiffyDOS.md") and the MEGA65 open-roms `Protocol-JiffyDOS.md`. The open-roms authors worked from bus logs only. Facts that matter to us (both documents agree):

- **Detection (side channel):** during ATN, the controller delays CLK about 400 us before the last bit of TALK/LISTEN; a JiffyDOS device answers by pulling DATA for about 100 us (a stock 1541 uses a 218 us threshold). We already hold CLK at that moment in `bus_talk`/`bus_listen`; a probe costs one bit-time stretch and one DATA sample. Cheap and safe, and stock drives ignore it.
- **Byte send:** 2 bits per 10 to 13 us step on CLK/DATA, no handshake after the initial "go"; bit order 4-5, 6-7, 3-1, 2-0, no inversion. Window about 63 us that must not be disturbed.
- **Byte receive:** order 0-1, 2-3, 4-5, 6-7, inverted; window about 55 us. EOI by delaying the last step; "both released" means error.
- **LOAD:** TALK on channel 1 with the file open on channel 0; skips the load address; drive reads each block with the C64 interrupts off (about two thirds of the time is the drive reading). Has an escape mode for stalls.
- **Constraints:** no interrupts, sprites off, no badline DMA in the window (blank screen or raster-sync), 1 MHz, no one-to-many.
- Measured: about 2.1 KB/s, controller code about 739 bytes.

Where JiffyDOS gives us what C does not: file-level LOAD semantics and the Jiffy-equipped drives we have on the hardware bench. Where C wins: it is adoptable and sector-level. Because `blk.s` reads *blocks*, the JiffyDOS per-byte send/receive would be used as a replacement for `bus_acptr`/`bus_ciout` on a JiffyDOS-detected device, giving roughly 5 times the standard rate without any drive-side upload. It is about 250 bytes of host code per direction if clean-roomed from the specification above (the 739-byte figure includes the LOAD loop and the detection).

### 3.3 Other prior art (to survey, not adopt)

- **Epyx FastLoad / Action Replay / Final Cartridge:** same family as C (drive-side upload), proprietary in source form, although the technique is public. Not adoptable; useful as protocol confirmation.
- **sd2iec (GPLv2):** `iec.c`, `fastloader-ll.c`, `jiffy` and `dreamload` support are the reference for the *device* side of JiffyDOS, Epyx, Dreamload, Turbo-Disk. Good for timing sanity checks and for building a fake device for our tests, but **GPLv2 and Breadbin is MIT**. Reading it to understand is fine; copying is not, unless the project's licence changes. Flagged for the user.
- **1541 Ultimate emulated drive:** loads the same drive code as a real 1541, so C works on it; its own fast paths need the C64 side to cooperate with UCI instead.

## 4. Licensing summary and the clean-room path

| Source | May we copy code? | May we learn from it? |
|---|---|---|
| `fastboot1541` | Yes, with credit (author asks for an email too; ask the user) | yes |
| cbmbus_doc, open-roms JiffyDOS notes | Documentation: yes; keep attribution | yes |
| **open-roms JiffyDOS code** (`src/kernal/iec_fast/jiffydos_*.s`, acme syntax) | **Literal code exists**, licensed **LGPLv3** (see 10). Usable only with the files kept LGPL and the user's agreement | yes |
| JiffyDOS ROM images | **No** (not in the repo; for experiments only) | observing bus behaviour: yes |
| sd2iec | **No** (GPLv2 vs MIT) | yes, read-only, for understanding |
| Epyx, AR, FC | **No** | techniques are public |

For B, the open-roms method is the one to follow: write the host routines from the descriptions, then compare with **bus traces from VICE running the JiffyDOS ROMs as the reference device** (record CLK/DATA transitions with timestamps per byte; compare against our implementation talking to the same ROM). The JiffyDOS images the user has are acceptable as a test oracle in that sense and stay out of the repo, as already decided.

## 5. Integration plan

Each step stands alone, in the order the roadmap already prefers, and each leaves the plain protocol working.

1. **REU block cache** (D). Independent of the bus; fixes the bench time first. Not repeated here.
2. **UCI file backend** (E, S10/S11). Principal fast path, designed from WP1 measurements.
3. **Fast block read for any 1541-class drive** (C):
   - Add `iec_fast_probe` (is it a 1541-class drive: from the drive's status string / `M-R` of a ROM location that differs between stock and JiffyDOS (address to be found by diffing the two ROM images; not checked yet); the status after reset is also a hint).
   - Upload the drive routine with `M-W` (a few 32-byte chunks), start with `M-E`, stream sectors, return to the standard protocol with a defined end sequence (`UNTLK`).
   - API: `blk_read` keeps its signature; the backend picks `fast_read` when the probe succeeded and the screen/IRQ rules below are met.
   - Constraints inherited from fastboot1541: interrupts off for the transfer; raster-sync for the window (we own the interrupt entry, so a raster IRQ is possible later; for now `sei`, wait for a safe raster line, and accept that the jiffy clock stalls for ~25 ms per block, which is the same trade the stock loaders make); screen blanking is optional if we stay on safe raster lines.
   - Write: the mirror, after read has proven out on hardware.
4. **JiffyDOS send/receive** (B), only if there is an appetite after 3: detection by the 400 us ATN side channel; `bus_acptr_j`/`bus_ciout_j` selected per device, by the same probe. Clean-room, verified against the VICE reference device.
5. **Compaction (M0-7).** Fold `iec_fast_*` and the JiffyDOS routines into the shared bit-banging helpers where they overlap with `iec.s`; the drive-side blob can be generated at assemble time from a `.s` file with `.org` in the drive's address space (the pattern fastboot1541 already uses with segments).

Budget (estimates, no builds): C read about 160 bytes + 170 RODATA blob; C write +120/+130; B about 250 per direction + 60 detection. All inside the 6,079 bytes even before the space pass; none is on the critical path.

## 6. Timing and platform rules (all paths)

- 1 MHz CPU: turbo must be off around any of these transfers (`$D031` exists only if enabled in the menu; `WP4` measures it).
- Interrupts off and, for B and C, a raster-aware window; REU DMA must not run at the same time (it steals cycles).
- Ultimate: the emulated 1541 and UCI Software IEC behave differently from real drives; B and C each need hardware confirmation on (a) the real 1541, (b) the Ultimate's emulated 1541, (c) JiffyDOS ROM drives. Fast paths are disabled automatically on a failed probe or on a mid-transfer timeout, falling back to the plain protocol.

## 7. Test plan

Per `docs/testing.md` policy: targeted in the story, milestone for the full set.

1. **Host:** a small Python model of the drive-side protocol (bit order, parity of the transfer, EOI) used in `make test-host` to check the byte/bit packing in both directions against vectors taken from cbmbus_doc (no emulator needed).
2. **VICE, stock ROM:** C read of a known file / the root dir; compare checksum against the standard path; time per block.
3. **VICE, JiffyDOS ROMs** (`BREADBIN_VICE_ARGS`): same, plus the detection probe returning positive; B bus-trace comparison (sections 4/5).
4. **Hardware** (WP2, then the milestone list): real 1541, Ultimate emulated 1541, JiffyDOS drive. Record: works, bytes per second, whether the screen must be blank, whether the C64's IRQ can be on.
5. **Negative tests:** drive absent, drive not 1541-class (probe fails, plain path used), disconnect mid-transfer (timeout, recover), disk error.

## 8. Open questions

1. Is `$D586` (the read-sector routine `fastboot1541` calls) the same in the JiffyDOS drive ROM? (WP2.)
2. Can we make the drive routine position-independent enough for both ROMs, or does it need two variants selected by the probe?
3. Fast **write**: any job queue side effects (BAM, directory buffer, error-LED, GCR conversion time)? Writing sector-level bypasses DOS validation; `format`/`dd`-style uses only, with the filesystem layer owning the BAM.
4. Do we accept the ~25 ms interrupt gap per block? (It breaks the keyboard scan during a read; the alternative is a raster IRQ that suspends the transfer.)
5. **Licensing decisions for the user:** (a) email the fastboot1541 author as he asks; (b) confirm the clean-room policy for JiffyDOS and the no-copy policy for sd2iec (GPLv2 vs the repo's MIT).

## 9. Sources

- Michael Steil, `cbmbus_doc` ("6 Fast Serial", "7 JiffyDOS"), <https://github.com/mist64/cbmbus_doc>.
- MEGA65 open-roms, `Protocol-JiffyDOS.md` (clean-room description from bus logs).
- Michael Steil, `fastboot1541`, <https://github.com/mist64/fastboot1541>; blog post pagetable.com/?p=568.
- `sd2iec` (GPLv2), read-only reference.
- Ultimate documentation, <https://github.com/GideonZ/1541u-documentation> (`uci/`).

## 10. Revised order (user preference, 2026-10-31) and what the first step found

Order: (1) clean-room JiffyDOS if open-roms has no adoptable literal code; (2) a scoped research pass over demoscene loaders; (3) `fastboot1541` and a matching fastsave, with the email to Michael Steil only if it ships and is not just a POC; (4) from-scratch work last, since we are unlikely to beat decades of community work.

### 10.1 Step 1 result: open-roms does have literal JiffyDOS code

`MEGA65/open-roms` (cloned for reading to `/home/user/mega65/open-roms`, outside the repo) has `src/kernal/iec_fast/jiffydos_{tx_byte,rx_byte,load,detect,prepare,wait_line,bittable,preserve_bits}.s`, 752 lines in acme assembler syntax with `#LAYOUT#` tags, hooked into `src/kernal/iec/iec_{tx,rx}_byte.s`. It was written from VICE bus logs and Steil's analysis (the file comments cite both), not from a disassembly.

- **Licence:** the package `LICENSE` says **GNU LGPL v3 or later** (Gardner-Stephen 2019, Standzikowski 2019-2021), with `COPYING` holding the GPLv3 text that the LGPL refers to. It is not GPL proper, and it is not MIT.
- **What that means for us:** a port to ca65 is a derivative work. The ported files would stay LGPLv3 with the notices intact and the credit lines, while the rest of Breadbin stays MIT. The LGPL requires that users can modify and relink the LGPL part; for a source-distributed 6502 image in one public repo that is satisfied, but a mixed MIT/LGPL kernel binary is the kind of thing a lawyer would want to look at. **This is the user's decision**; the alternative is to write our own routines from the description (an afternoon of work for tx/rx; the code is ~110 and ~120 lines).
- **Technical shape (useful either way):**
  - tx: `sei`; wait for DATA release; wait for a safe raster line (`jiffydos_wait_line`); release both lines to say "go"; four writes to `$DD00` carry the nibbles (high nibble pair, then low pair, with a lookup table `jiffydos_bittable` for the low nibble's bit shuffle); EOI by a delay before the last step. Sprites are turned off (`jiffydos_prepare`) and restored. About 24 + 21 cycles between writes.
  - rx: wait for CLK release, "go", then four samples of `$DD00` with the inversion; the window is about 55 us.
  - detect: the 400 us side channel as above, done at each command; DATA going low during the delay means a JiffyDOS device.
  - `jiffydos_load.s` (340 lines) is the file-level LOAD, which we do not need since our reads are blocks.
- **Estimated size in our kernel:** tx + rx + detect + bit table is about 300 to 400 bytes in ca65, less than the LOAD stub. It fits easily; the squash pass can share `$DD00` helpers with `iec.s`.
- **A caution that came in from the hardware session:** the bench has seen *all devices answer ATN whether connected or not* (a bench behaviour, not our code). Both `bus_listen` presence detection and the JiffyDOS probe (DATA pulled during the long delay) depend on a clean DATA line. Until that is understood, a JiffyDOS probe on the bench could report a device that is not there. Design rule: the probe is only made after the device has already answered the ATN and delivered the first real byte.

### 10.2 Step 2: scope of the demoscene research pass

A pass over demoscene code is large, so this scopes it and does not do it. What the scene offers and what we need do not match perfectly, and that must be decided first:

- **Our need:** block (sector) reads and block writes on a 1541-class drive, usable from a multitasking kernel with a periodic IRQ, uploaded at run time or resident in the drive, stock and JiffyDOS ROMs, with the plain protocol as a fallback.
- **The scene's habit:** whole-file loading with an IRQ-friendly bit protocol, designed to run in a demo with the screen on, often with a built-in decompressor and a custom disk format (which we must not use: we want normal 1541 DOS disks).
- **Candidates to look at first** (from a quick search; licences not yet verified from the repositories):
  - **Spindle** (Linus Akesson, lft): v3, "fully open source"; the stated licence is informal ("go ahead and use this in your demos", credit "Loader by lft"); the formal terms are in a `COPYING` file not yet read. Loader plus a linker; loads whole files from custom-format disks.
  - **Krill's Loader** (Krill / Plush): supports 1541 and relatives, widely used; described as "no strings attached" on one distribution page, no formal licence found; saving is listed as planned in v146 and not confirmed in later versions (v194, CSDb release 226124).
  - **Bitfire** (Bitbreaker / Performers; fork at `iszell/bitfire`): fixed-interleave loader with depacker; licence not yet read.
  - **Sparkle** (Sparta / Maurizio; `spartaomg/SparkleCPP` holds the tooling): licence not yet read; custom disk format.
  - Not yet looked at: Doynax's loader work, Dreamload, the turbo-disk family; none verified.
- **Questions for the pass, in priority order:**
  1. Which of them can read or write *arbitrary* sectors of a normal-format disk? (A custom-format loader would still teach the bit protocol but not give us code.)
  2. Which has a save? Is it documented?
  3. Per candidate: licence text read from the repository, the size of the host side, whether it is IRQ-safe, and which drive ROMs it was tested on (JiffyDOS in particular).
  4. What is the transfer rate with the screen on vs. blanked?
- **Cost to scope:** read the licences and READMEs of the four candidates first (half a day of agent time); stop there unless one of them answers question 1 with a yes. A full survey is a task for a separate research agent and is not committed to by this document.

### 10.3 Step 3 (later): `fastboot1541` and a fastsave

As in section 3.1. It stays POC-grade until the plan is committed to shipping; at that point the email to the author goes out.

### 10.4 Decisions made (2026-10-31)

- Licence policy (now in `CLAUDE.md`): MIT upstream, our code informal/PD; **no LGPL/GPL** (so no port of open-roms or sd2iec code; clean-room only for JiffyDOS); demoscene code is adoptable on community norms (stated intent or evident reuse), with credit and greetings, and the evidence recorded.
- Research is approved: four Haiku agents with empty context, each with a narrow question (Krill's Loader; Spindle/Bitfire/Sparkle; DolphinDOS and other documented protocols; fast-write prior art). Results land in the scratchpad and are summarised in section 11. `csdb.dk` (releases and comments, dated) is the best source for reuse evidence.
- Clean-room JiffyDOS, and other well-studied protocols (DolphinDOS among them) are to be sketched in parallel with the research, so the plan survives either outcome.

### 10.5 Superseded questions

1. LGPLv3 open-roms code: port with the files kept LGPL, or reimplement clean-room from the description?
2. Is the demoscene survey approved at the half-day scoping level above?

## 11. Research results so far (Haiku agents, 2026-10-31)

Raw notes are in the session scratchpad (`research/*.md`), not in the repo. **Network limits:** the session allowlist blocked `csdb.dk`, `codebase64.net`, `plus4world.powweb.com`, `www.pagetable.com`, `svn.icomp.de`, `forum.6502.org`, `lemon64.com`, `mega65.github.io`, `c64-wiki.com` and others, so most findings are from search snippets and are marked unverified. `github.com` works. The user must add the hosts under Allowed domains before the reuse-evidence work (csdb comments) can be done.

| Topic | Result | Status |
|---|---|---|
| Krill's Loader | No verified source URL or licence text. Snippets: distributed as source ("no strings attached"), C64 Wiki marks it open source; versions 146 (2013) to 194 (2022); 1541 and relatives supported; save not confirmed. | unverified; blocked |
| Fast-save prior art | No readable public fast-save source found. `fastboot1541` reads only (track 18, sectors 0 to 3, via ROM `$D586`). Leads needing blocked hosts: 15 Second Copy (pagetable.com/?p=656), Chaco eload `drive_1541_write.s` (svn.icomp.de), 1541 Fast Format (Mike J. Henry). | unverified; blocked |
| DolphinDOS | Needs the **parallel cable** (user port to the drive's VIA) and a drive ROM swap on a physical 1541; the Ultimate can emulate it with "parallel drive connection" enabled. Not a Classic-tier option. `donnchawp/DolphinDOS2` is Unlicense on its face, but ships ROM-derived `kernal.asm`/`1541.asm` and ROM images, so the provenance of the code is unclear: **do not adopt**. The open-roms protocol doc was written from VICE logs and says it may be incomplete. | partly verified |
| Epyx FastLoad, WarpSpeed | Drive-code disassemblies exist (an archeobits mirror of zimmers.net); no licence found; treat as copyrighted. | unverified |
| Bitfire (`bboxy/bitfire`) | **BSD-3-Clause**, (c) 2021 Tobias Bindhammer (raw LICENSE read). Compatible with our MIT if the notice is kept. Own disk format only (no t/s links; chain computed from the start sector, fixed interleave 4); resident C64 side `$7B` to `$1FE` bytes by configuration; a dotscha fork adds a save routine and names a "2-bit ATN method" that forbids a second drive on the bus. Fork `iszell/bitfire` has no LICENSE file. | licence verified; rest partly |
| Sparkle (`spartaomg/SparkleCPP`) | **BSD-3-Clause**, (c) 2019-2026 Sparta/OMG (raw LICENSE read); `Sparkle2` licence not seen. File-level loading; "limited file saving capability" per both READMEs; own format. | licence verified; rest unverified |
| Spindle (lft) | `linusakesson.net` blocked; only snippets: "D64-compatible storage format", formal terms in a `COPYING` file not read. | unverified; blocked |

Take-aways for the plan: nothing found changes the order. The clean-room JiffyDOS sketch (`jiffydos-cleanroom.md`) stays the known-good path; the fastboot1541 read path stays adoptable (permissive); a fast **write** has no adoptable prior art yet, so it is likely our own work built on the job queue, with the pitfalls listed above (write protect, BAM consistency, verify).

Bitfire and Sparkle are the first demoscene candidates with a verified permissive licence. Both use custom disk formats, so what we would take from them is the **drive-side GCR/bit-transfer technique and the protocol shape**, not a drop-in sector API; a quick source read of Bitfire's drive code (GitHub is reachable, so this needs no allowlist change) is the next cheap step and would answer the sector-access, save and JiffyDOS questions. Spindle needs `linusakesson.net` allowed.

## 12. Candidate matrix after the source reads (2026-10-31)

Network note: after the allowlist change, WebFetch still could not resolve some hosts but `curl` through the proxy worked, so later agents used curl. Every row below was read from source archives or repository files unless marked unverified. Raw notes stay in the session scratchpad (`research2/`).

| | Krill's Loader v194 | Spindle 3.1 | Bitfire (bboxy, dotscha fork for save) | SparkleCPP 3.4 | ELoad (Chaco) write | JiffyDOS (clean-room) |
|---|---|---|---|---|---|---|
| Licence | BSD-style, 3 clauses, credit "Loader by Krill" (v146: "no strings attached") | MIT (src); credit "Loader by lft" | BSD-3 (Bindhammer 2021); dotscha fork has no licence file of its own | BSD-3 (Sparta/OMG). `Sparkle2` repo: no licence, all rights reserved | zlib-style permissive, attribution | n/a (ours, from the spec) |
| Disk | **normal DOS disk, by filename** | own layout on whole tracks, coexists with DOS | own chain format | custom GCR, nonstandard sector order | raw sector write on a formatted disk | normal DOS, any |
| Sector API | none in v194 (v146 had a TRACK_SECTOR option) | none | sector write (save) in the fork; read side is chain-based | none (file-level) | write only | whatever `blk.s` asks |
| Save | limited: overwrite an existing file in place | none | **one sector per call** (T/S + 256 bytes), WPS check, read-back verify | hi-score file only, fixed chain | one sector, WPS check, no verify | yes (send protocol), drive's own DOS writes |
| Host resident | `$1F9` (ZX0), `$E0` raw | 1 page + 5 zero-page bytes | `$7B` to `$1FE` by config | about `$1A0` | n/a | about 300 (est.) |
| Speed (author) | 7.7 KB/s max, ~7 typical | ~6.8 KB/s at full raster, ~1.85 at 20% | 4.5 KB/s incl. spin-up (forum) | ~13.7 KB/s bus ceiling (derived) | not stated | ~4.2 KB/s (c64-wiki) |
| Transfer | 2 bits + ATN, 72 cycles/byte | 18 cycles per bit pair | 2-bit ATN method | 2 bits + ATN, 72 cycles/byte | n/a | 2 bits per 11-13 cycles, no ATN, windowed |
| IRQs / screen on | IRQ, NMI, sprites, badlines allowed | yes (raster-time budget) | base IRQ and safe-load hooks | IRQs off during load | n/a | no: interrupts off per byte |
| Multi-drive | ok (sd2iec "proper support") | silences others | forbidden by the ATN method | **refused** | n/a | yes (device-by-device) |
| JiffyDOS drive | unverified; unknown ROM treated as 1541-II | unverified | unverified | not mentioned | n/a | the point |

### What the evidence says

- **The 7 KB/s class is the same trick everywhere** (2 bits per step with ATN as a clock, 72 cycles per byte); Krill's, Sparkle and Bitfire differ in packaging, not in speed. Spindle's 18 cycles per bit pair is the same family. Breadbin does not need to choose among them on speed.
- **The differentiators are the constraints:** normal-DOS disks and by-name loading (only Krill's), multi-drive (not Sparkle, not Bitfire's ATN method), interrupts allowed (Krill, Spindle), a real single-sector write (the Bitfire fork and ELoad).
- **Transwarp** (Krill of Plush, 2020) is the "50x" claim, but needs custom-interleave images (`cc1541`); another custom-format design, so ruled out by our "normal disks" requirement. The 25 to 31 KB/s figure for the GCR ceiling is derived, not measured.
- **No ground for cutting JiffyDOS:** it is the only candidate that works unchanged on the JiffyDOS-drive bench and on every device regardless of disk layout. It is slower than the 2-bit+ATN family, but it needs no upload.
- **ELoad's write** is the clearest model of "write one already-formatted sector from custom drive code": WPS check (`$1C00` bit 4), motor and LED, search the header, skip nine header bytes, write mode (`$1C0C=$CE`), five sync bytes then 325 GCR bytes, back to read mode. Its job codes are its own (`$04`/`$0E`/`$0F` in zero page), not the DOS `$90` job; **no source found uses the DOS job queue for writes**. No verify; add a read-back. Not hardware-verified for us.
- **Cut (no differentiator for us):** DolphinDOS (parallel cable), cartridge loaders (Epyx, AR, FC III), Sparkle2 (no licence), Sparkle (custom format, multi-drive refused, IRQs off), Spindle (custom layout, no sector access, no save), Transwarp, MafioDOS. Keep for reference only.

### Leading plan, pending the remaining reports

1. REU cache and UCI backend as decided.
2. Per-byte **JiffyDOS clean-room** on detected JiffyDOS devices (the bench has them; no upload; any disk).
3. A **Krill-style drive-side loader reading raw sectors** for stock drives: port the transfer idea (72 cycle/byte 2-bit+ATN, documented in Krill's `docs/Protocol.txt`) with Krill's BSD-style credit, adding the sector-granular entry point that v194 lacks; the drive code can be adapted from Krill/Bitfire under their licences. The write is ELoad-style or Bitfire-fork-style.
4. All of it probed at run time, with the plain protocol as the fallback.

Open: the Bitfire source report (drive-side detail), the loader comparison and the modern-speeds report are still coming; the Ultimate behaviour of the 2-bit+ATN family is untested (an Ultimate II+ firmware 3.10 issue was reported against some loaders).

## 13. Speed comparison from published tables (comparison agent, 2026-10-31)

Baseline is the 64'er test table as reproduced on c64-wiki (LOAD, 202 blocks): standard serial 407 B/s (124 s). Multipliers are the table's; B/s are derived unless noted. Cartridge and ROM products are proprietary and listed only to calibrate.

| Method | B/s (LOAD) | Needs | Save speed-up |
|---|---|---|---|
| Standard serial | 407 | nothing | 1.0x |
| Epyx FastLoad | ~2,500 (vendor claim) | cartridge | none |
| Warp Speed 2.0 | ~3,350 | cartridge | 7.2x |
| Final Cartridge III | ~3,800 | cartridge | 5.4x |
| JiffyDOS | ~4,280 (124 s to 12 s) | ROMs both sides | 75 s to 24 s |
| Krill's Loader | 4,000 raw, ~8,500 with decrunch (author page, v146); 7.7 KB/s max in the v194 README | nothing | in-place file overwrite only |
| Action Replay 7.5 | ~5,700 to 6,200 | cartridge | 7.0x |
| Dolphin DOS 2 | ~10,500 | parallel cable | 14.9x |
| Transwarp | ~19,000 (c64-wiki; 50x in the 64'er table) | custom-interleave disks | cannot be saved by standard copiers |

Ceilings (from a pagetable.com commenter and `?p=1107`; derived, not measured by us):
- two-bit software protocol: host at about 80 cycles per byte (~12.5 KB/s), drive at about 130 cycles per byte (~7.8 KB/s); the 72-cycle host loops of Krill's and Sparkle sit at this edge;
- the media itself: 26 to 32 us per raw byte, so roughly 25 to 31 KB/s of payload after GCR decoding. The limit for IRQ-friendly loaders is the protocol and the decode, not the platter. Only the custom-format designs (Transwarp) approach the media.

Derived 10 KB and 40 KB load times: standard 25 s / 101 s; JiffyDOS 2.4 / 9.6 s; Krill 2.6 / 10.2 s (4 KB/s) or about 1.3 / 5.2 s (7.7 KB/s); Dolphin 1.0 / 3.9 s; Transwarp 0.5 / 2.2 s.

What this settles. For stock drives on normal disks, **JiffyDOS-class and Krill-class land within a factor of 2 of each other** (4.3 vs 4 to 7.7 KB/s), and everything faster needs a custom disk format (Transwarp), a parallel cable (Dolphin) or a cartridge. That supports the plan in section 12: the speed class we can reach with normal disks is about 4 to 8 KB/s, 10 to 19 times the baseline; beyond that the cost is a format change, which is a different decision (see the roadmap's note on the REU cache, which beats all of these on repeat reads).

## 14. Bitfire, read from source (bboxy v1.2, dotscha save fork, iszell beta)

Byte counts not measured (nothing assembled); the rest is from the repositories.

- **Licence:** `bboxy/bitfire` is BSD-3-Clause (Bindhammer 2021). The `dotscha` (save, Plus/4) and `iszell` (2024 beta) forks have no licence file; they derive from the BSD-3 base, so the base licence is the best evidence of intent, and the demoscene-norms clause of our policy applies. The iszell tree contains files built from sd2iec (GPL): **do not take those**.
- **Drive side:** calls no ROM routine except the reset vector (`$FFFC`); the one-time bootstrap uses the DOS job queue at `$04/$0E/$0F`. Image: zero-page tables at `$00`, code at `$0200`, cache `$0600`, directory `$0700`, stack page as the sector buffer. Upload: `M-W` of a bootstrap to `$0600`, `M-E`, then the bootstrap receives the rest bit-serially (`installer.asm`, `drivecode.asm`). GCR decode is a 4-step table loop reading `$1C01` with byte-ready sync (8 nibbles per 5 bytes).
- **Host side:** resident at `$F000` by default (readme recommends `$0200`), zero page `$02` to `$0C`; the receive loop reads `$DD00` four times per byte, 2 bits per step, **74 cycles per byte** (about 13 KB/s on the link by arithmetic); benchmark sheet: 98,719 packed bytes in 18.2 s PAL (v1.x) vs 22.6 s (old). "2-bit ATN": the two bits ride DATA and CLK, ATN polled as the bus lock. Base IRQ/NMI are documented as usable during loads (the mechanism is not verified); no I/O-area loading.
- **Disk:** own format. Fixed interleave 4 on tracks 1 to 17 and 3 elsewhere; files contiguous with no link bytes; 63 four-byte directory entries per sector on track 18. API is file-level (file number, load-next, skip, side, reset): **no arbitrary track/sector read**.
- **Save (dotscha):** `save(track, sector, 256 bytes)`, tracks 1 to 40: raw GCR written through `$1C01` with the existing header untouched, a 325-byte GCR block, verify by raw read-back, three write and three verify retries, status codes 0 to 3; uses stock ROM tables (`$F77F`, `$F8C0`, `$F8A0`); drive code limit `$0500`; "no second drive on the bus". This is the same raw-write approach as ELoad, plus the verify that ELoad lacks.
- **Multi-drive:** the installer places an ATN responder on every other present drive (devices 8 to 11) so the bus lock works; the fork's author says a second drive is not supported.
- **Known problems:** wobble and 300 rpm sensitivity, the 72-cycle loop failing with some cables, 1541-II stepping, SX-64 bus lock. **JiffyDOS: not mentioned anywhere**; the stock-ROM table reads and the job-queue bootstrap are the risks on the bench's JiffyDOS drives.

Consequences for the plan: the block-read side should be a Krill/Bitfire-style drive loader written for **normal-format sector reads** (our own drive code, borrowing the bit-serial installer, the 4-step GCR table loop and the 2-bit+ATN host loop), and the write side is the dotscha/ELoad raw-GCR write plus read-back verify. The drive code does not need the ROM except for the reset vector and (on first upload) the `M-E` entry; that matters for JiffyDOS drives, whose ROM differs.

## 15. Measured speeds and the shortlist (modern-speeds agent, 2026-10-31)

Independent measurements (Obliterator918's DTB table, updated 2026, https://www.obliterator918.com/comparison-of-commodore-64-speed-loaders/), B/s for a 177-block file: stock 403; Epyx 2,121; Warp Speed 3,017; **JiffyDOS (1541-II) 3,746**; Super Snapshot 4,163; Action Replay 5,352; **Transwarp 0.84 16,056**; Ultimate II+ Hyperspeed 64,223 (not applicable). The benchmark cannot test loaders that unload themselves, so Krill's, Bitfire, Sparkle and Spindle are absent from it. Author and archive figures: Krill's v194 7.7 KB/s max, 7 typical (method not stated; inferred ceiling 6.7 to 9.0); Bitfire 1.1 raw load 5.29 KiB/s (98,719 bytes in 17.94 M cycles, PAL); Sparkle and Spindle publish no throughput.

Physical ceiling at 300 rpm with 223 payload bytes per sector (Transwarp docs): **23.4 KB/s on tracks 1 to 17 falling to 19.0 KB/s on 31 to 35**. Transwarp's "just under 20 KB/s" is that outer-track ceiling; end-to-end it measured 16 KB/s.

Corrections to earlier sections:
- **Transwarp is GPLv3** (`transwarp.s`): excluded by policy, and it also needs pre-encoded files, a blanked screen, sprites and IRQs off, cannot save, and hangs with a second drive on the bus.
- **Krill's v194 is permissive** (copyright 2022 Gunnar Ruthenberg, attribution requested), supports DMA, sprites and badlines, standard DOS format, and tolerates other drives on the bus.
- Spindle 3.1 and Sparkle 2.2/3.4 specs: Sparkle resident `$2A0`, three zero-page bytes, 124-cycle drive GCR loop, 269 to 314 rpm tolerance; Spindle 18 cycles per bit pair; neither measured.

### Shortlist (what survives the cuts)

| Rank | Method | Why it survives | Differentiator it keeps |
|---|---|---|---|
| 1 | REU block cache | Zero protocol risk; repeat reads at DMA speed | Beats every loader on repeats; fixes the bench |
| 2 | UCI file backend | Removes the bus | Recommended-tier answer |
| 3 | JiffyDOS-class per-byte protocol, clean-room | ~4 KB/s (3.7 KB/s measured on a 1541-II), any disk, any device, no upload, ~300 bytes | Works on the bench drives unchanged; smallest |
| 4 | Krill/Bitfire-style drive loader for normal sectors, with a raw-GCR write plus verify | 7 to 8 KB/s class, permissive licences, IRQs allowed (Krill), normal disks | Roughly twice JiffyDOS on stock drives; the only route to a fast write |
| cut | Transwarp (GPL, custom disks), Sparkle (no licence for v2, custom format, multi-drive refused), Spindle (custom layout, no sector API, no save), DolphinDOS (cable), all cartridge loaders, MafioDOS, Epyx/Warp/AR/FC | no differentiator for the platform tiers or a licence we cannot use | |

Within rank 4 the pieces to take: the bit-serial installer and the 4-step GCR table loop (Bitfire, BSD-3), the 72-cycle 2-bit+ATN host loop (Krill/Bitfire; documented in Krill's `docs/Protocol.txt`), and the raw write with read-back verify (dotscha fork over ELoad's zlib-style code). What we write: the sector-granular entry point and the glue to `blk.s`. Estimated cost in the kernel: host receive and send loops about 150 bytes, glue 60, drive blob about 600 bytes in RODATA (Bitfire's drive image runs `$0200` to `$0500`).

### Decisions needed

1. **Licence handling for BSD-3 sources** (Bitfire, Krill's, Spindle MIT, ELoad zlib-style): keep each author's notice in the file header and in `docs/design/fast-io.md`; this satisfies BSD-3 and fits "credit and greetings". The forks without licence files (dotscha, iszell) are treated as BSD-3 derivatives with the evidence recorded.
2. **Order of rank 3 vs rank 4.** Rank 4 gets roughly twice the speed and the only write, but costs a drive blob, a probe, and a hardware validation of the 2-bit+ATN family on the Ultimate (open). Rank 3 is smaller and safer and fits the hardware we have. Recommendation: build rank 3 first as the proof of the "fast byte" seam in `iec.s` (a per-device protocol hook), then rank 4 behind the same seam once the hardware agent has confirmed the Ultimate behaviour with a POC (WP2).
3. Whether to ask the hardware session to run a **Krill's Loader v194 and Bitfire POC** on the bench: unmodified, from a normal disk image, on the Ultimate with a JiffyDOS drive ROM and with a stock ROM. That would answer the open compatibility question cheaply (they use standard files, no source change needed).

## 16. POC 1: Krill's Loader v194 under VICE, unmodified (2026-10-31)

What was run: the `loadertest-c64.d64` that ships in Krill's v194 release archive (no rebuild, nothing changed), autostarted in `x64sc` with true-drive emulation and warp on, via the existing `tools/vicetest.py` harness (scratch script, not in the repo). The program loops over `LoadRaw` and `LoadCompd:ZX0` of the disk's test files and prints a rate per load. Run twice: stock drive ROM, and the JiffyDOS 6.01 ROM in the drive (`-dos1541` and `-dos1541II`; the active ROM was confirmed by reading drive memory at `$F7CE`, which holds the JiffyDOS bytes only in the second run).

| Drive ROM | Loop runs without error | LoadRaw | LoadCompd:ZX0 |
|---|---|---|---|
| stock 1541 | 95 of 95 (about 7 minutes of VICE time) | 6.0 to 6.4 kB/s | 10.2 and 13.0 kB/s |
| JiffyDOS 6.01 | 77 of 77 (about 5.5 minutes) | 6.0 to 6.4 kB/s | 10.2 and 13.0 kB/s |

Reading: **Krill's loader works unmodified on a JiffyDOS 6.01 drive ROM in the emulator, at the same rate**, and its documentation lists the 1541U ("1541 Ultimate") among natively supported drives. The measured 6.0 to 6.4 kB/s is below its 7.7 kB/s maximum because the test files are small and the numbers include directory lookup. Caveats: this is the emulator, not a drive; the C64 KERNAL here is the stock one; nothing in this test exercises interrupts during loads (the sample `test.s` does, but this was not checked); no hardware, no Ultimate. Krill's install code treats unknown ROM signatures as a 1541-II, which is the likely reason JiffyDOS needs no special case.

What it settles: rank 4's transfer scheme (2 bits plus ATN, drive code uploaded by `M-W`/`M-E`) is not obstructed by the JiffyDOS drive ROM in VICE. What it does not settle: the real JiffyDOS hardware (the bench), the Ultimate's emulated 1541, and the other open questions below.

### Hardware tasks queued (for when the hardware session has its open questions closed)

Recorded in `docs/wip.md` as WP5. Nothing here is to start before the session says it is confident of the bus quirks (phantom ATN responses and the rest).
