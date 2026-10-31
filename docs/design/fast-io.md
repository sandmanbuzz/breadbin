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
