# Fast disk I/O

Status (2026-11-26): built, and tested under VICE only. Sections 17 and 18 describe what is in the tree. Sections 1 to 16 are the research record from the paper stage (2026-10-31); they are kept as history and their "we will" and "not yet" wording is from that date. Companion to "Disk speed" in `docs/roadmap.md`, which holds the measured baseline (standard protocol: about 1.8 ms per byte, 0.55 s per block, boot about 70 blocks).

Shipped: the JiffyDOS byte protocol in the kernel (`make JIFFY=0` leaves it out; 17.1), and `fast.km` (`mod load /lib/km/fast`), a block module for c64fs mounts on a stock 1541 that reads and writes whole blocks with its own drive code (17.2). Not yet proven on a physical drive, and the Ultimate's emulated 1541 has shown fallbacks to the standard path (17.3). Open: which path a JiffyDOS drive should use (18.7), and a faster raw-GCR path (18.9 to 18.11).

## 1. What we want

- Faster reads **and writes** on 1541-class drives (stock and JiffyDOS), without making the core depend on either.
- Code small enough to be worth it: `fast.km` costs the kernel no bytes (17.2); the JiffyDOS protocol's cost is in `iec.s`.
- Everything probed at run time (platform tiers: Classic must still boot on the plain protocol).
- Original or clean-room code under the licence policy (section 4).

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

Ranking at the paper stage: E (principal, already decided) and D (cheap, fixes the hardware bench), then C (the only adoptable code that helps stock drives), and B last and optional.

As built: D (the REU cache, shipped), B (the JiffyDOS byte protocol, shipped clean-room, 17.1), and a drive-side uploaded loader for the stock 1541 in C's role (`fast.km`, 17.2). `fastboot1541` itself was not adopted (3.1).

## 3. What is worth adopting

### 3.1 `fastboot1541` (C): studied, not adopted

Not adopted. `fast.km` (17.2) fills the same role with code written from the 1541's public documentation; the drive-side job loop idea is shared, with credit. What follows is the reading record.

`start.s` is 199 lines; the whole scheme is one sector holding both the drive code and the host receive loop. Notes from reading it:

- The host sends `M-E` through an ordinary open on channel 15 using the KERNAL `filnam`/`open` (`$FDF9`, `$F34A`): we would use our own `iec_ch_open`.
- The drive routine reuses ROM routines (`$D586` read-sector) so only the transfer loop is new. This is the compatibility risk: the JiffyDOS drive ROM moved things, and `$D586` has to be confirmed in both ROMs. Local disassembly of both is available to the hardware session; WP2 in `docs/wip.md` is the experiment that answers it.
- Transfer: 2 bits per step on CLK/DATA, raster-synchronised (waits for a good raster line so badlines do not steal cycles in the window), interrupts off, screen state matters. Bits use the same two lines as ATN-free serial.
- It is a *boot* loader (fixed track-18 table, `seccnt` sectors). For the kernel we need the generalisation: a drive routine that takes `track, sector` pairs (or reads them from the command) and streams 256 bytes per call; the host side becomes `iec_fast_read(track, sector, buf)`. Size estimate: host 120 to 160 bytes, drive 130 to 180 bytes (uploaded, so it costs *no kernel space* apart from storing the image, ~170 bytes in RODATA).
- Writes: the mirror routine (host sends 256 bytes, drive loops writing to the buffer, then calls the DOS job queue (exact ROM entry points to be confirmed in the disassembly; not checked yet)). Same size class. This must be proven on hardware; the DOS job queue protocol (job codes at `$00-$05`, track/sector at `$06+`) is documented in cbmbus_doc "3 Commodore DOS" and the 1541 ROM.

Why it is the best fit: it works for stock and JiffyDOS drives alike, needs no knowledge of JiffyDOS, and its cost is almost all in the drive. Its limits: not for 1581 or Software IEC (those take other paths; NTH), and it replaces the *block* layer, not the file layer, which matches how Breadbin uses disks (`blk.s`, b-block reads).

### 3.2 JiffyDOS (B): studied, then implemented clean-room (17.1)

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
| **PLASMA** VM (David Schmenk, <https://github.com/dschmenk/PLASMA>, `src/vmsrc/c64/plvmc64.s` at `f209e30`) | **Yes: MIT.** Ported as `src/pvm/pvm.s`, notice, URL and commit in its header (`docs/design/pvm.md`). `src/pvm/test/bench.s` is upstream's compiler output | yes |
| **BASIC-M6502** (Microsoft, <https://github.com/microsoft/BASIC-M6502>) | **Yes: MIT**, literal or derived (the owner, 2026-11-18); for the BASIC (E1 L3). Commodore's BASIC ROM is not this and stays out | yes |
| Lawless Legends (Apache-2.0), UCSD p-System (non-commercial) | **No** (Apache only if backed into a corner, the owner's call; UCSD's licence does not allow it) | yes |

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

`MEGA65/open-roms` (cloned for reading to `a scratch directory`, outside the repo) has `src/kernal/iec_fast/jiffydos_{tx_byte,rx_byte,load,detect,prepare,wait_line,bittable,preserve_bits}.s`, 752 lines in acme assembler syntax with `#LAYOUT#` tags, hooked into `src/kernal/iec/iec_{tx,rx}_byte.s`. It was written from VICE bus logs and Steil's analysis (the file comments cite both), not from a disassembly.

- **Licence:** the package `LICENSE` says **GNU LGPL v3 or later** (Gardner-Stephen 2019, Standzikowski 2019-2021), with `COPYING` holding the GPLv3 text that the LGPL refers to. It is not GPL proper, and it is not MIT.
- **What that means for us:** a port to ca65 is a derivative work. The ported files would stay LGPLv3 with the notices intact and the credit lines, while the rest of Breadbin stays MIT. The LGPL requires that users can modify and relink the LGPL part; for a source-distributed 6502 image in one public repo that is satisfied, but a mixed MIT/LGPL kernel binary is the kind of thing a lawyer would want to look at. **This is the user's decision**; the alternative is to write our own routines from the description (an afternoon of work for tx/rx; the code is ~110 and ~120 lines).
- **Technical shape (useful either way):**
  - tx: `sei`; wait for DATA release; wait for a safe raster line (`jiffydos_wait_line`); release both lines to say "go"; four writes to `$DD00` carry the nibbles (high nibble pair, then low pair, with a lookup table `jiffydos_bittable` for the low nibble's bit shuffle); EOI by a delay before the last step. Sprites are turned off (`jiffydos_prepare`) and restored. About 24 + 21 cycles between writes.
  - rx: wait for CLK release, "go", then four samples of `$DD00` with the inversion; the window is about 55 us.
  - detect: the 400 us side channel as above, done at each command; DATA going low during the delay means a JiffyDOS device.
  - `jiffydos_load.s` (340 lines) is the file-level LOAD, which we do not need since our reads are blocks.
- **Estimated size in our kernel:** tx + rx + detect + bit table is about 300 to 400 bytes in ca65, less than the LOAD stub. It fits easily; the squash pass can share `$DD00` helpers with `iec.s`.
- **Correction (hardware session, 2026-10-31):** the earlier report that all devices answer ATN whether connected or not was a mistake of the test (`OPEN n,dev,15` with no filename sends nothing on the bus); the bus is clean. The real open item is a stall of the root mount on the **physical 1541** (5 of 7 boots), not yet localised (our receive code, or the drive/bus; a stock-KERNAL control run is in progress). Design rule kept: a JiffyDOS probe result counts only after the device has acknowledged the command byte normally.

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

Recorded in `docs/wip.md` as WP5. Nothing here is to start before the session says it is confident of the bus quirks (the physical-1541 root-mount stall and the rest).

The sub-agent research reports (raw, with VERIFIED/UNVERIFIED marks and URLs) are kept in `docs/design/research/`; the POC scripts are in `experiments/loader-poc/`.

## 17. What was built (2026-11-16): the JiffyDOS byte protocol in the kernel, and `fast.km`

Two pieces, both on by default and both switchable.

### 17.1 The JiffyDOS byte protocol in `iec.s` (`make JIFFY=0` builds without it)

- **Source.** Michael Steil, *Commodore Peripheral Bus, Part 7: JiffyDOS* (`mist64/cbmbus_doc`): the detection handshake, the byte send and receive state machines and their C64 cycle tables. The routines were written from that text alone, in a session that had no JiffyDOS ROM listing and no open-roms or sd2iec source in front of it (the LGPL reading recorded in `jiffydos-cleanroom.md` was another session's, for scoping). No ROM bytes are in the repo; the JiffyDOS drive ROM is only ever a test fixture (`BREADBIN_CI_JIFFY`).
- **Shape.** The probe is in the first byte under ATN of every session (`jif_first`: seven bits, a 400 us hold, the eighth bit); `io_jif` bit 7 clear means the addressed device answered, and is good for that session only. A stock drive does not answer and sees a slightly long bit. `bus_acptr` leaves for `jif_rx` and data bytes go through `io_txd`; LOAD is not implemented (we do not use it).
- **Cycle counts** are checked on the host by `tools/test_jiffy_timing.py` from the built kernel, with the bad-line avoidance (`jif_safe`).
- **Emulated speed** (VICE, JiffyDOS 1541 ROM, `JIFFY=1` against `JIFFY=0`, real speed): `wc /bin/as` 20.7 s against 40.2 s; `cp /bin/basic` 106.0 s against 197.7 s. Per block (`tests/prof_blockio.py`): read 410 ms against 959 ms, write 698 ms against 1437 ms. What is left of a read is the `U1` command and the wait for its status, not the bytes.

### 17.2 `fast.km`: block transfer for a stock 1541 (`mod load /lib/km/fast`)

For the drive without a JiffyDOS ROM. A kernel module, so it costs the kernel no bytes: three call sites in `blk.s` are named (`bread_io`, `bwrite_io`, `iclose_io`) and the module points them at itself while it is loaded.

- **Licence and source.** Original work for this repo, written from the public description of the 1541 (its job queue at `$00`-`$05`, the header table at `$06`, the buffers at `$0300`-`$07FF`, VIA port B at `$1800`) and from the same byte protocol as 17.1 turned around: the drive side sends and receives the 2-bit pairs at the times the host's routines expect. No loader was copied or adapted: not Krill's, not Bitfire, not `fastboot1541` (whose idea of a drive-side job loop it shares; credit to Michael Steil for the documentation of both the protocol and the drive).
- **Drive memory.** On a stock 1541 the kernel's `#` channel (secondary 2) gets buffer 2 (`$0500`; checked under VICE: the drive's channel table at `$022B` gives the channel, `$A7`+ its buffer). The drive code takes that buffer and its job slot (`$02`, header `$0A`/`$0B`) for the sector, and lives in buffers 0 and 1 (`$0300`-`$04FF`), which the module reserves with `#0` and `#1` on secondaries 4 and 5 so the DOS keeps them. Before uploading it checks that the drive is a 1541 (IRQ vector `$FE67`) and that the kernel's channel really has buffer 2. Any other answer and the drive is left alone (the standard path). The first layout assumed buffer 0 for the kernel's channel and never installed; the probe refused it as designed. **Hardware, 2026-11-18 (physical 1541, `experiments/iec-stall/drvdump.s`): the kernel's `#` channel got buffer 3 (`$0600`), not 2: `$A7` = 3, `$022D` = `$40`, and `U1:2 0 18 0` filled page `$0600`.** The DOS takes the highest free buffer first, so VICE's buffer 2 means 3 was busy there. A check that insists on buffer 2 refuses on this drive; derive the page from `$A7` instead (and expect `#0`..`#2` to be the free ones).
- **Per block:** one `M-E` with the operation, track and sector behind it. The drive code runs the read job itself and sends status, 256 bytes and a checksum; for a write it takes 256 bytes and a checksum, writes only if they agree, verifies, and sends the status. No `U1`/`B-P`/`U2` command text, no status text, no second session.
- **Failure rule.** Anything that goes wrong (the code does not answer, a job error, a checksum, a timeout) ends the fast try and the block is done again on the standard path, with the DOS's own retries and its error text. Three in a row and the drive is left alone until it is mounted again. ATN makes the drive code return to the DOS at any point.
- **Timing.** The drive finds the host's "go" with a 7-cycle loop, so each of its port accesses lands in a window 7 cycles wide, and the clocks differ (PAL host 1.015 us per cycle, NTSC 0.978, drive 1.000). Send (the drive writes at 6, 17, 27, 38, 49 after it sees go; the host reads at its cycles 16, 26, 37, 48, 59): the previous pair is on the wire at least 1.4 us before each read and the next at least 0.28 us (PAL) after it. Line delay moves both the go and the drive's writes later, which is why the schedule sits on the early side. Receive (the host writes at 11, 24, 35, 48, 61; the drive reads at 13, 26, 37, 50): at least 1.2 us on both sides. `tools/test_fast_timing.py` checks the counts from the built module; `make MODFLAGS="-D SK2=18"` shifts a point for margin tests.
- **Results under VICE (2026-11-16, `tests.test_fast`).** Stock 1541 ROM: installed, 607 blocks carried by the drive code with 0 fallbacks over a copy of `/bin/basic` written, re-read and rewritten (after an `rm`); the copies are byte-identical on the host, and after `mod unload` the standard path copies again. JiffyDOS 1541-II ROM: the probe accepts the drive too (same IRQ vector, same buffer), and the same test gives 607 carried, 0 fallbacks. Timing (`BREADBIN_FAST_BENCH=1`, stock ROMs, emulated seconds, one run each): `wc /bin/as` 46.9 standard, 27.3 with the module (x1.7); `cp /bin/basic` 231.5 and 140.4 (x1.65). Not yet done: the margin sweep (PAL and NTSC, `MODFLAGS`), a real drive, the JiffyDOS-ROM figures with the module against the in-kernel protocol.

### 17.3 Decisions and caveats (2026-11-17, owner)

- **Clean room is process-only, and accepted.** The sketch author read the LGPL open-roms JiffyDOS routines (`jiffydos-cleanroom.md`); the implementing session saw only the sketch and cbmbus_doc and says so in `iec.s`. The separation is by process, not provable from the repo. The owner has accepted that under the licence policy. Any later doubt about the JiffyDOS routines is settled by rewriting them from cbmbus_doc and a bus trace by someone who has seen neither.
- **Sprites.** A sprite on at the start of a session makes `jif_first` stay on the standard protocol for that session (follow-up commit after the landing). A sprite turned on mid-session, a RESTORE (NMI) in a byte window, or Ultimate DMA mid-byte can still shift a byte on the JiffyDOS path, which carries no checksum. Known, accepted risk; only `fast.km` checks its blocks.
- **fast.km fallbacks on hardware: open thread.** On the Ultimate's emulated 1541-II with the JiffyDOS ROM (c64fs, drive 8), one `wc /bin/as` carried 45 blocks and fell back on 3 (`ft_ng` 142 to 187, `ft_nf` 6 to 9), against 0 fallbacks in 607 under VICE (stock and JiffyDOS ROMs). Reads were still correct and faster (16 to 17.5 s against 21.4 s). The cause is unknown (emulation timing, or a real margin problem: the receive margin is about 2 cycles). If a fallback count above zero shows up again, on hardware or in a test, pull on this thread first: capture which of the failure rule's causes fired (no answer, job error, checksum, timeout) before changing anything. fast.km does not engage on a CBM DOS mount (the real drive 9 in this run), by design; it was never exercised on the physical drive (needs a writable c64fs disk).

## 18. The TFR v0.8 image: what it teaches (2026-11-20)

### 18.1 Source and licence record

- **What:** a 32 KB cartridge image whose banner reads "THE FINAL REPLAY V0.8" (four 8 KB banks, each at `$8000`), sha256 `f194fad1098e47442b61a937b3b432de6f5e0aed4a7fb3648857eef88243ebbe`. Supplied by the owner, who attributes it to **Oxyron**: a ground-up clean-room implementation of Final Replay / Retro Replay I/O routines, released in a community super-ROM. The image itself carries no credit, licence or provenance text; the attribution is the owner's.
- **Basis:** the owner classes it under the **demoscene standard** (no licence stated; open use by custom; the polite return is a greeting). That is the "stated intent or evident reuse" case of the licence policy in `CLAUDE.md`. Anything adapted from it names Oxyron in the file header and points here. **Greetings to Oxyron.**
- **Kept out of the repo:** the image and any disassembly of it. This section records findings, not code.

### 18.2 What is in it (read from a disassembly; roles marked "believed" are not confirmed)

- **Three stages.** (1) A few `M-W`/`M-E` commands put a small stub in the drive. (2) The stub is a **generic RAM uploader at `$0300`**: wait for the host, then repeat { receive address low, address high; if the high byte has bit 7 set, clear it and jump to the address; else receive 128 bytes into it } at the fast 2-bit rate. The host side sends every byte as four writes to `$DD00` with no per-pair handshake. (3) The large drive routines arrive through (2).
- **Receive primitive (drive).** One byte is four steps of "wait DATA/CLK edge, sample `$1800`, shift in"; the host's mirror is four back-to-back reads of `$DD00`, two bits each, with fixed `nop` spacing and interrupts off.
- **Reader routine.** Does not use the DOS job queue for the data: it finds the header with a ROM routine, then reads the whole raw GCR data block from VIA2 (`$1C01`, byte-ready on the V flag, 256 bytes into the sector buffer and the rest into the stack page), and sends it from the drive after two further ROM calls (roles believed to be GCR conversion and the job-completion path). It works through eight 5-bit groups per five bytes and **sends them through two 24-entry lookup tables**, so the bit pattern for `$1800` is a table fetch per step rather than shifts. A per-sector table at `$0624` marks what has been read.
- **Writer routine.** Real: sets VIA2 to write mode (`$1C0C`, `$1C03`), writes sync (`$FF`) and data through `$1C01` under the same V-flag byte-ready wait. Next to it is a **head-step and track-write routine** (settle timer loops on `$1805`, density bits, a long `$55` run) whose purpose is not identified; it is the likely track format or test pattern and is out of scope until read further.
- **Not the loader:** the `M-R`/`M-W`/`M-E` strings belong to the disk monitor, and bank 2 and 3 go through the KERNAL.

### 18.3 What it means for us

| Our state | What TFR does differently | Worth building? |
|---|---|---|
| `fast.km` runs DOS jobs per block, one `M-E` per block (17.2) | Reads GCR straight from VIA2, no job queue per block; table-driven sender | **Yes, as an experiment:** a drive routine that reads the next wanted sector as it passes, with `fast.km`'s checksum and fallback rule kept. Expect more than the 1.65x of 17.2, and more risk |
| Upload by `M-W` in 32-byte chunks | Generic fast uploader (address, 128-byte pages, execute flag) | **Maybe, later:** only helps if the drive code grows; today's upload is small and once per mount |
| `fast.km` refuses the physical 1541 at the buffer probe (`docs/wip.md`) | Does not rely on the DOS buffer map; takes memory by fixed address | **Yes, in the experiment:** it removes the probe |
| Writes go through the DOS job queue and verify | Direct GCR write | **Not first.** Direct writes can destroy a disk; only with a read-back verify, on a scratch disk, after the read path is proven |

### 18.4 Order proposed

1. Document the protocol and timing from the disassembly in our own words (the host windows in cycles, the drive loop cycle counts), and check them against `tools/test_fast_timing.py` style host checks.
2. New drive routine for GCR reads, written in our ca65 for the existing `fast.km` framing, tested under VICE (stock and JiffyDOS drive ROMs) and then on the physical 1541 under the `ultimate`/bench locks.
3. Fast uploader and direct writes only if step 2 shows the gain.

Not run: nothing here was executed on a drive; the cycle figures and the roles marked "believed" above are hypotheses until step 1 and 2.

### 18.5 Where a `fast.km` block's time goes (measured 2026-11-20, VICE, stock 1541 ROM)

Method: a throwaway patch to `ft_read` stamped the kernel's `ticks` (100 per second here, calibrated against the emulated cycle counter) at six points and summed the differences per phase; read back after `wc` of a 12-block file with the module loaded. 44 blocks were carried by that command (the file, its inode and indirect block, and the command's own binary). Real speed, host VICE; warp mode changes the cycle count and is not usable for timing. Resolution is 10 ms per stamp, so read each figure as plus or minus about 10 ms; two runs agree within 15 ms.

| per block carried | ms (blocks of the file 1 apart / 5 apart) |
|---|---|
| probe (`ft_ready`) | 0 / 0 |
| `M-E` sent, drive code started, handshake | 24 / 23 |
| **job wait (drive reads the sector)** | **226 / 209** |
| status byte | 0 / 0 |
| 256 bytes and checksum | 57 / 56 |
| total inside `ft_read` | 306 / 288 |

- **The job wait is about 70% of a block**, and about a full revolution (200 ms) on average. Sequential blocks are physical neighbours (the kernel maps block n to consecutive sectors), so the sector after the one just read has passed under the head by the time the next request arrives.
- The 5-apart file barely helped because only 12 of the 44 blocks were the strided file; the rest were sequential misses. An earlier stride sweep (1 to 13) gave 346 to 522 ms per block for the whole command and had the same flaw. Do not quote it as a floor.
- **Consequence for the plan:** the transfer (57 ms) and the command (24 ms) are small beside the wait. The first lever is therefore **read-ahead**: have the drive start the job for the next block into the spare buffer while the current one crosses the bus, so a sequential block pays the transfer, not the revolution. A direct-GCR reader (18.2) matters second: it lets the drive catch the next header at once instead of waiting for the job queue's next pass, which decides whether read-ahead gets close to the transfer time or stays near one revolution per block. A faster bus helps last.
- Not measured: writes (verify doubles the job time), the JiffyDOS drive ROM, the physical 1541, and the host's own time outside `ft_read` (about 50 ms per block by difference).

### 18.6 Steady state, and what read-ahead must be (measured 2026-11-20)

The per-block series for `wc /bin/as` (62 blocks, same stamps, per block job wait and full cycle in 10 ms ticks) corrects 18.5: the average there (about 210 ms of job wait) was inflated by blocks that needed a seek (job waits of 400 to 740 ms). Where blocks run consecutively, which is most of them:

- job wait 140 to 150 ms; full cycle 240 to 250 ms. The host chain (command, transfer, the host's own work) is about 100 ms, so each block is **locked to one revolution plus about 45 ms**: the request arrives after the next sector has passed.
- Consequence: reading **one** block ahead through the job queue only moves the wait (about 217 ms a block, an 11% gain). A real gain needs **two or more sectors read in one pass** (jobs posted into drive buffers 2 and 3 together, so the controller does them back to back), then served from the drive's buffers with no job wait. The floor is the host chain, about 100 ms a block (2.4 times today), then the transfer (57 ms) and the command (24 ms).
- The drive cannot read and send at once (the job queue runs in the drive's interrupt, and the transfer needs interrupts off), so the sectors have to be read first, then sent. If the job queue does not run two jobs back to back inside one pass, a direct-GCR reader (18.2) is what lets the drive take consecutive sectors without the queue's latency. That is the first thing to test.

### 18.7 Which path wins on a 1541 (decision rule, owner 2026-11-20)

The aim is the fastest path for anything we touch. If the drive-code path with batch reads beats JiffyDOS on 1541s, 1541s stop using the JiffyDOS path and it stays for non-1541 drives only. That is to be decided by measurement: the same operation on the same build, a JiffyDOS-ROM drive with the JiffyDOS kernel path against `fast.km`, both under VICE at real speed (the JiffyDOS ROMs are outside the repo, `BREADBIN_CI_JIFFY`). The earlier figures (`wc /bin/as` 20.7 s JiffyDOS against 28.3 s `fast.km` today) come from different sessions and drive ROMs and do not settle it. Non-1541 drives (1571, 1581) keep the JiffyDOS path where the drive has it and the standard path otherwise; a 1581 drive-code path would be bespoke work, since the TFR image has nothing for it.

### 18.8 The job queue does not chain (measured 2026-11-20)

Experiment: with the 18.6 stamps, the drive code posted extra read jobs in buffer slots 3 (and 4) next to the requested sector in slot 2, and waited for all of them before sending. `wc /bin/as`, VICE at real speed, stock 1541 ROM, steady-state job wait per command:

| jobs posted | job wait |
|---|---|
| 1 (as shipped) | 145 ms |
| 2: n, n+1 | 265 ms |
| 3: n, n+2, n+4 | 380 ms |

Each extra job costs about 115 ms (about half a revolution) whatever sector it targets: the DOS does not start the next job in time for even the next-but-one sector, so a batch through the stock job queue gives about 227 ms a block against 245 today (about 8%), and slot 4 is the BAM buffer, which a batch would have to treat as dirty. **Batching through the job queue is dead.** What is left is reading the sectors ourselves from the raw GCR stream (18.2), where consecutive sectors follow each other 10 ms apart: a pass reads two or three, then the drive sends them. Raw GCR is 325 bytes a sector, so the free buffers (2, 3 and 4, 768 bytes) hold two raw sectors, decoded while sending.

### 18.9 A raw GCR reader works, and chains sectors (measured 2026-11-20)

Experiment (drive code only, host unchanged, reverted): after the normal DOS read job, with interrupts off, the drive code waits for sync, captures the next sector header (10 raw bytes) and the first 256 raw bytes of its data block, then the same again for the sector after it. VICE, stock 1541 ROM, `wc /bin/passwd`; `fast.km` carried all 42 blocks, no fallbacks. Decoded from the dumps and compared with the disk image:

- header A = track 12 sector 0, header B = track 12 sector 1, checksums and disk id right; both data blocks carry marker `07` and their first 203 bytes match the image. **Two consecutive sectors come in one pass**, which the job queue could not do (18.8).
- **The DOS job lags.** The first header caught after a job completes was the job's sector plus 4 on a 21-sector track (job sector 10, header 14), about 3 ms into our wait: the DOS decodes the block and reports on its own schedule, so three or four sectors go by after the data has been read. A reader that rides behind a DOS job misses the next sector. The raw reader has to read the wanted sector itself and use the DOS only to seek.
- **Sync alignment is a trap.** The only deterministic sequence is the DOS's own (`$F556`): `bit $1c00` until sync, then at once `lda $1c01 : clv`, then `bvc`, `clv`, `lda $1c01` per byte; any store between the sync and that first read (or waiting for the sync to end) moved the first captured byte by one in some syncs and not others. Do bookkeeping after the `clv`. The byte loop (about 19 cycles a byte) is under the 26-cycle byte time of the fastest zone.
- **The stack page is not ours.** The DOS keeps its overflow buffer at `$01BB`, but `rts` back into the DOS needs the frames above the stack pointer, so a reader that returns cannot use it (TFR does not return). The 69 overflow bytes a sector needs have to go elsewhere (buffers 3 and 4 give room for two raw sectors).
- **Room.** The blob is exactly full at `$0500` with the write path removed; a raw reader plus a write path will not fit in two buffers. The kernel's `#0`/`#1` reservation, the data buffer and the BAM page (`$0700`, which the DOS rewrites on any initialize) all need a plan.

Not shown yet: the full 325-byte capture and decode of all 256 bytes, selecting a wanted sector by header, seeking, reading a track change, error handling, the JiffyDOS drive ROM, the physical 1541, hardware timing, and speed (this run measured correctness, not time).

### 18.10 Single-block prefetch is dead; the unit is a pass of two sectors (measured 2026-11-20)

Experiment (`src/mod/fast.s`, red: writes removed, drive code in two parts at `$0300` and `$0650`, raw blocks decoded on the host, not shippable): after the drive has sent a block it captures the next one raw (header found by its sector, 325 bytes, kept in the `#` buffer) so the host's next request can be served from it. Two things the measurement settled:

- **c64fs data blocks carry no track/sector link** (the filesystem finds blocks through the inode's list), so the drive cannot read the next block from the block it holds. The host guesses by stride (the next block as far past this one as this one is past the last, same track only) and passes the sector in the `M-E` command.
- **The prefetch never completes.** `wc /bin/as` and `wc /bin/passwd`, host VICE at real speed, stock 1541 ROM: 48 prefetch attempts, 0 blocks served from one, 0 header timeouts. The host's next command (ATN) arrives before the wanted header has gone round: the sector after the one just read has already passed while the previous block crossed the bus (57 ms), and the next pass is a revolution (200 ms) away, longer than the host chain (about 100 ms). Times were 20.6 s and 29.2 s against 19.6 s and 27.3 s without it (the longer command, no hits).

So a read that starts only after the current block has been sent cannot hide the revolution (the same lock as 18.6). The raw reader has to take the next sector **in the same pass** as the wanted one (18.9 showed that works), then send both. Estimate per pair: command 24 ms, about half a revolution to the first header, 20 ms to capture two, then two transfers of about 72 ms (325 raw bytes) and about 26 ms host decode each: about 170 ms a block against 245 ms today, a 30% gain, and 3 sectors a pass would do better.

Room is the constraint: two raw sectors are 650 bytes of buffer, leaving about 630 bytes of the 1280 for code, with a write path out of the question in that budget. The drive code can shrink: the host can send the header codes (no `d_enc` and table on the drive), and only the first block of a track needs the DOS job.

Run: `wc /bin/passwd`, `wc /bin/as` with the experimental module, host VICE real speed. Not run: a two-sector pass, writes, JiffyDOS drive ROM, 1541-II, hardware, `make test-host`, smoke, suite.

### 18.11 The two-sector pass works; strides 1 to 8 (measured 2026-11-20)

`src/mod/fast.s` (red: no write path, drive code in two parts at `$0300` and `$078A`, raw buffers at `$0500` and `$0645`): for a request the host passes the wanted sector, the GCR codes of a guessed second sector (same track, the previous stride) and a mode (0 DOS job, 1 raw for the wanted sector, 2 raw for both). The drive captures the wanted sector, then the guess in the same pass, sends the first, and holds the second for one request. A later request that matches the held block is served with no head work. The host decodes the 325 raw bytes (checksum, marker, no bad codes) and falls back to the standard path on any failure.

Bug worth keeping: the host decode indexes with X, and the nibble helper `tax`es; the first version hung `mod ls` after `mod load`. Save and restore X around the helper.

Results, host VICE at real speed, stock 1541 ROM, ms per block ((N=20 file minus one block file) / 19):

| stride | standard | old fast.km (df634aa) | two-sector pass |
|---|---|---|---|
| 1 | 924 | 459 | 350 |
| 2 | 862 | 458 | 411 |
| 3 | 816 | - | 354 |
| 4 | 868 | 306 | 405 |
| 5 | 919 | - | 405 |
| 6 | 921 | - | 403 |
| 8 | 917 | - | 455 |

`wc /bin/passwd` 19.5 s, `wc /bin/as` 25.3 s, 0 fallbacks, 23 of 49 blocks served from the held sector.

Reading it: the gain is 24% at stride 1 and 10% at stride 2 against the old module, but stride 4 is 32% worse, because the old module's cycle happened to land on the revolution there (306 ms). Results depend on how the pair cycle lines up with the 200 ms revolution, not on a smooth cost per stride: 3 is as good as 1, 2/4/5/6 sit at about 405, 8 is worst. Two cheap levers follow: the allocator's stride/interleave, and a hint policy that picks the sector the head reaches first. The host chain outside the drive (about 100 to 120 ms) and the host decode (about 26 ms) are still unprofiled in detail, and 325 raw bytes cost about 15 ms more than 256.

Open: staleness of the held block (any write, disk swap or fallback must drop it), the debug counters `d_nh`/`d_nm`, reserving buffers 3/4 and the BAM page, the write path (does not fit this budget), the head-to-head against JiffyDOS on 1541, and the owner's decision rule.

Run: `wc /bin/passwd`, `wc /bin/as`, stride bench N=20 at strides 1, 2, 3, 4, 5, 6, 8, host VICE real speed, stock ROMs. Not run: JiffyDOS drive ROM, 1541-II, hardware, writes, `make test-host`, smoke, suite, the hater gate.

### 18.12 Seek-then-raw after a track change: slower, reverted

The vprof table (87bd4ed) puts DOS-job reads (mode 0, after every track change) at about 600 ms each. Try: the host marks the first request on a new track `$81`; the drive runs a job `$B0` (seek) on the DOS, then captures the sector raw. Result, `wc /bin/as` cold, 49 blocks, host VICE at real speed, stock ROMs: 440.7 ms per block baseline vs 456.4 with the seek, 21.6 s vs 22.4 s. No gain: the 1541's `$B0` job seeks and then reads a header to check the track (it is not a bare step), so the DOS path's cost is mostly the seek-and-verify and the spin-up, not the sector read. Reverted. A real saving needs the drive code to step the head itself (the stepper at `$1C00`, bits 0-1, with the DOS's own settle time), which is a bigger unit. Run: baseline and variant under tools/vprof.py. Not run: JiffyDOS drive, 1541-II, hardware, other files.

### 18.13 Faster host decode: no gain, reverted

Rewrote `hdec` (nibble tables for both halves, no per-nibble call, the group decoded in place at a stride of five over the GCR bytes it consumed, then a packing copy). Decode plus copy measured 31 ms per block (vprof, `fast:hdec` to `fast:ft_good`); the first estimate of 47 ms for the old one was from the retracted tick stamps and was not re-measured, so the saving is unknown but at most that. End to end, ms per block, old vs new: `wc /bin/passwd` 562.6 vs 561.1, `wc /bin/sh` 485.8 vs 485.2, `wc /bin/as` about 441 vs 454 (alignment noise). Nothing: the host decodes while the drive waits for the next sector, so the cycle is set by the revolution and the drive's job, not by the host's work between requests. The same reason explains 18.11 (stride matters only through alignment). Reverted: more code and risk for no latency. Lever left on the host side: none that shortens the critical path except the command send (about 54 ms, before the drive can start the pass) and the host-to-drive handshake. Run: three files, old vs new, tools/vprof.py, host VICE at real speed, stock ROMs. Not run: JiffyDOS drive, hardware, tests.test_fast on the new decode (the A/B decoded correctly, `wc` counts matched).

### 18.14 Image layout: metadata near the inode table, hot files first

The shipped image was already stride 1 for file data (first-fit), so the cost was elsewhere: directories and indirect blocks were allocated wherever was free when the tree was filled (`/bin` in four blocks on tracks 4, 9, 13 and 16; `/` on track 3) while the inodes sit on track 19, so a cold lookup thrashed the head across the disk. `tools/mkimage.py` (1541 images only) now reserves a meta zone nearest the inode table for the directories and indirect blocks of the tree (`plan_layout`; the root directory is moved into it), fills file data outward from that track one block after another (a new track: the nearest one with room), and creates `HOT` files (init, login, sh, fast, cbm, ls, cat) first, so they sit near the centre and early in their directory. Deterministic; a `.d81` and other geometries keep first-fit.

ms per block and wall seconds for the whole command, host VICE at real speed, stock ROMs, `fast.km` loaded, old vs new layout (same build otherwise): `wc /bin/as` 441.1 / 24.3 s vs 431.6 / 24.3 s (no gain: three track crossings in its own data and the far-flung directory entries of a late-alphabet name); `wc /bin/sh` 499.1 / 23.6 s vs 456.2 / 20.5 s (-13%); `wc /bin/passwd` 564.3 / 19.0 s vs 489.2 / 17.3 s (-9%). Not run: the standard (non-fast) path, JiffyDOS drive, hardware, boot-time totals, the other files. Open: a hot-file list from real use, sector-level skew between the lookup chain's blocks, `/bin/as` (a second pass on where it crosses tracks).

### 18.15 The write path is back, as an overlay; a torn spare byte broke raw reads of written sectors

**Room.** The resident drive code (buffers 0 and 1, `$0300-$04FF`) is exactly full with the raw reader, and the write path (about 120 bytes: `d_wr`, `d_recv`, `d_rtab`) does not fit beside two raw sectors in the 1,280 bytes. A write needs only the data buffer, so the write code is an **overlay at `$0650`** in the second raw sector's room (`blob3`, 192 bytes padded, to `$0710`). The host puts it up with the same M-W loop the first time a block is written to a drive (`upov`) and keeps a per-drive flag (`ovl`). A mode 2 pass (guessed second sector) would wipe it, so a write sets `ft_wq` = 8 and `hint` stays at mode 1 for the next eight reads; a mode 2 request clears the flag, and the next write puts the overlay up again. The write protocol is the old one (drive DATA low and CLK released, 256 bytes and a checksum, the DOS write job and a verify job, status). Resident cost: 5 bytes of dispatch; the drive code is still exactly `$200`.

**Staleness.** The drive drops the held sector on any write (`d_wr` clears `d_kt`). A write that goes the standard way (bus failure before the drive code ran) sets `ft_inval`; the next fast read then sends one throwaway request first (any request drops the held sector).

**The bug it exposed.** With writes back, `tests.test_fast` carried 630 blocks but three to five blocks per read fell back, deterministically, on files written at run time (by the fast path or by the standard path: not specific to our write). The raw block, captured before decoding, had exactly one bad GCR code, the very last quintet: the DOS write job's turn-off tears the end of the second spare byte. `hdec` refused any bad code and also folded the two spare bytes into the block checksum. It now requires whole codes up to the last group and leaves the spare bytes out of the sum (the data and the checksum byte are still checked; the marker as before).

Run: `tests.test_fast` (634 blocks carried, 0 fallen back, copies exact after `cp`, `rm`, `cp`), `make test-host` (786), `tools/test_fast_timing.py` (reads the overlay's labels), smoke; control reads of a standard-path-written file (0 fallen back after the fix, 3 before). Not run: JiffyDOS drive ROM, 1541-II, hardware, the full suite, timing of writes (next), the hater gate.
### 18.16 Held sector after a media swap (finding 1 of the ce02c7f hater): fixed for umount and eject; out-of-band swaps are an accepted risk

**Mechanism.** The drive keeps one held sector (RB2) between requests, and a read request clears it on entry. A channel close (umount, eject) reaches `ft_close`, which clears the drive's `state`; the next fast read re-installs the drive code, and the blob carries `d_kt` as zero, so the held sector is dropped. This was already the behaviour on cbd0d88, before this branch. A disk swap with no close never reaches `ft_close`, so the held sector survives it: that is the accepted risk below.

**Evidence.** `tests.test_fast_swap.FastClose` (VICE, container) checks that a umount clears the drive's `state` and that the next read sets it back to 1 (the re-install). It passes on the fix tree and on cbd0d88, so it guards the existing behaviour and does not discriminate. An earlier version of this branch added an `ft_inval` flag to `ft_close`; a hater review showed it was redundant with the re-install, and it was removed. No layout tried reproduced a stale hit (block counts 10 to 13, both swap orders, VICE). `tests.test_fast` gives 587 blocks carried on both trees under the same ROM settings; the earlier 634 figure came from a different setup. Track alone does not identify the held sector: `d_k2` holds no sector code on the candidates tried.

**Accepted risk (owner, 2026-11-24).** A swap with no umount and no eject gives the OS no event, so no kernel code can react. The risk is the one any UNIX system has when media is removed under a mounted filesystem: stale data or I/O errors. `eject` is the supported path for the boot disk on single-drive REU systems, and it closes the channels, so the fix covers it. The fix is not extended to serve-time checks: validating a held sector on every hit would cost up to one disk revolution per hit (about 200 ms at 300 rpm), which cancels the gain from mode-2 hits. Same-ID disks (most CBM disks share an ID byte) are not distinguished by the existing `$0209` check at capture.

**Open, not blocking.** A hardware run of a live hot mount on the Ultimate (2026-11-24, another session, with fast.km) did not hang, but its i/o errors were not separated from typing errors, so no conclusion is drawn from it. `docs/hardware-notes.md` records this.

## Novaterm 80-column font (src/mod/con80.font)

808 bytes (101 glyphs), reordered by `tools/soft80_render.py` from `misc/font80.novaterm` in Novaterm 9.6's `novaterm-source.tgz` (zimmers.net, `pub/cbm/c64/comm/Novaterm/`); the input is not in the repo. Author: Nick Rossi (Novaterm's author). Evidence: the owner's assertion of 2026-11-20 that the author released the source free and that the C64OS author includes NovaText from it; the tarball has no licence text. Dating (owner, 2026-11-20): the release is undated, estimated around 2000 from secondhand records; the zip is stamped 2013-08-17, its members run 1995 to 2000-04-08, and the stripped build outputs share 2000-02-24 12:35, so the public release is on or shortly after 2000-02-24. `misc/font80.novaterm` is dated 1995-11-05. Credit and greetings to the Novaterm scene are in the module header (`src/mod/con80.s`).
