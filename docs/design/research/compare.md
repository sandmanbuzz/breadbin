# C64 + 1541 serial speed-up methods: evidence comparison

Scope: speed for typical 10 to 40 KB loads, and footprint. Sources are in
`/tmp/claude-0/-home-user-breadbin/ac401ab2-2ad5-5a0d-81f0-7272d9803b0d/scratchpad/research2/pages_compare/`.
No loader was run or measured here: every number is either quoted from a
source (VERIFIED = the source states it; the wording of the source is given)
or is UNVERIFIED. "Derived" means arithmetic on a quoted factor.

Baseline used for derived figures: standard C64 + 1541 LOAD = 407 B/s, SAVE = 374 B/s
(64'er Speed Test, quoted on c64-wiki "Comparison of fast loaders"). Cross-check: stock
202-block PRG load takes 124 s (c64-wiki JiffyDOS table), which is 414 B/s.

## Table

| Method | B/s (LOAD unless stated) | Resident C64 bytes | Drive bytes | IRQs and screen on | Special hardware | Save | Licence status |
|---|---|---|---|---|---|---|---|
| Standard serial (KERNAL ROM) | 407 LOAD, 374 SAVE, ~400 (VERIFIED, c64-wiki comparison; pagetable fastboot article "about 400 bytes per second") | 0 | 0 | IRQs turned off periodically by the ROM code (VERIFIED, pagetable fastboot article) | none | yes | n/a |
| JiffyDOS | ~4,280 (VERIFIED as a wiki table: 202 blocks 124 s to 12 s); 9.84x in 64'er test = ~4,000 derived | KERNAL ROM replacement, not RAM (size UNVERIFIED) | 1541 DOS ROM replacement (size UNVERIFIED) | UNVERIFIED | JiffyDOS ROMs in the C64 and in each drive (VERIFIED, c64-wiki) | yes: 100-block SAVE 75 s to 24 s (VERIFIED, wiki table) | Proprietary ROMs (Retro Innovations, c64-wiki). Never copy; clean-room only |
| Epyx FastLoad (cartridge) | ~2,500 (VERIFIED as Wikipedia claim, "2,500 bytes per second"); 5.14x in 64'er test (NTSC-scaled) = ~2,090 derived | Cartridge ROM (size UNVERIFIED) | 0 (stock drive) | UNVERIFIED | Cartridge in expansion port | none: SAVE factor 1.00 (VERIFIED, 64'er table) | Commercial cartridge. Clean-room only |
| Action Replay 7.5 (cartridge) | ~6,200 derived (LOAD factor 15.30); ARMK6 RAM loader 202 blocks in ~9 s = ~5,700 derived (VERIFIED, Wikipedia Fast loader) | Cartridge ROM (size UNVERIFIED) | 0 | UNVERIFIED | Cartridge | yes, SAVE factor 7.00 (VERIFIED, 64'er table) | Commercial. Clean-room only |
| Final Cartridge III | ~3,800 derived (LOAD factor 9.34) | Cartridge (UNVERIFIED) | 0 | UNVERIFIED | Cartridge | yes, SAVE factor 5.40 | Commercial. Clean-room only |
| Warp Speed 2.0 (cartridge) | ~3,350 derived (LOAD factor 8.23) | Cartridge (UNVERIFIED) | 0 | UNVERIFIED | Cartridge | yes, SAVE factor 7.18 | Commercial. Clean-room only |
| Dolphin DOS 2 | ~10,500 derived (LOAD factor 25.92; data transfer factor 10.29) | ROM replacement (UNVERIFIED) | Drive ROM replacement (UNVERIFIED) | UNVERIFIED | Hardware (parallel cable per task brief; not confirmed in fetched text) | yes, SAVE factor 14.89 | Commercial ROM and hardware. Clean-room only |
| Krill's Loader (type-in, Krill/Plus4World) | 4,000 uncompressed on 1541 (VERIFIED, author's page: "max. loading speed is 4.0 kB/s"); ~8,500 with Doynamite decrunch (VERIFIED, same page) | UNVERIFIED (page says size is customisable; text cut off) | UNVERIFIED | VERIFIED: "arbitrary interruptions (IRQs, sprites, badlines)" via async 2-bits+ATN protocol | none; native 1541, 1541-C, 1541-II, 1570, 1571, 1581, CMD FD (VERIFIED) | not stated | Page says "comes with no strings attached" (VERIFIED wording). Exact licence UNVERIFIED; must check before adoption |
| Spindle (Lft, v1.0 2013 to v3.1 2022) | UNVERIFIED. Primary site not reachable from this sandbox | UNVERIFIED | UNVERIFIED | VERIFIED class only: "IRQ loader ... keep their own IRQs during loading" (Wikipedia, codebase64 "fastloaders") | none stated | UNVERIFIED | UNVERIFIED (CSDb lists release history only; linusakesson.net does not resolve) |
| Bitfire | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | none stated | UNVERIFIED | UNVERIFIED |
| Sparkle | UNVERIFIED (nothing reached) | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| Transwarp (Krill/Plush, 2020) | ~19,000 (c64-wiki: "about 19 kBytes/Sec (50x the original speed)", own disk format); 50.00x "measured manually" in 64'er table | UNVERIFIED | UNVERIFIED | UNVERIFIED | none stated | Standard copiers cannot copy Transwarp files (VERIFIED, c64-wiki). Own format: 223 bytes per block, whole tracks (VERIFIED) | UNVERIFIED |
| Doynax | UNVERIFIED (nothing reached) | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| Dreamload | UNVERIFIED (c64-wiki page is an empty stub) | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| Turbo Disk (Compute!, 1985 type-in) | UNVERIFIED (c64-wiki page is an empty stub; Wikipedia confirms the magazine listing only) | UNVERIFIED | UNVERIFIED | UNVERIFIED | none | UNVERIFIED | Magazine type-in, copyright not checked. Do not adopt without evidence |
| fastboot1541 (Michael Steil, 256-byte autostart) | Ceiling only, not measured: drive side >130 cycles/byte = ~7,800 B/s at ~1 MHz (commenter on pagetable ?p=568, VERIFIED as a comment, not a measurement). Article's "50 cycles/byte, 20,000 B/s" is disputed in the same thread | 256-byte sector in total (C64 and drive halves not sized in the article) | Drive code is in the same sector (VERIFIED); not sized separately | Interrupts disabled with SEI during transfer (VERIFIED, article). Badline handling disputed (commenter; UNVERIFIED test) | none | load only (autostart boot) | Source on GitHub (mist64/fastboot1541); licence UNVERIFIED (GitHub not reachable in this session). Credit Michael Steil per repo policy |

## Speed ceilings

- Bus bit rate, classic ROM protocol: about 400 B/s (VERIFIED, pagetable fastboot article and c64-wiki). This is the stock-ROM floor.
- Two-bit software protocol, C64 side: 80 cycles/byte minimum (commenter, pagetable ?p=568) gives ~12,500 B/s at 1.023 MHz. The article's 50 cycles/byte is disputed.
- Two-bit protocol, drive side: >130 cycles/byte (same comment) gives ~7,800 B/s. This is the software ceiling for a fastboot-style byte transfer, and it is not reached by any loader quoted here, since Krill's 4.0 kB/s is ~half of it.
- GCR decoding: Wikipedia says "With modern loaders the slow rate of GCR decoding proved to be the bottleneck". No number is given in the sources. Krill and Bitfire decode mostly on the fly (codebase64 "fastloaders", VERIFIED).
- Raw media rate: fastest zone 26 us/byte (~38 kB/s raw), slowest zone 32 us/byte (~31 kB/s raw) (VERIFIED, pagetable ?p=1107). Each four data bytes take five GCR bytes, so payload is ~25 to 31 kB/s (derived). Krill's 4 kB/s is therefore far below the media rate: the limit is the protocol and decode path, not the platter (derived, consistent with the author's "4+1 revolutions per track" note).
- Transwarp at ~19 kB/s is near the media-rate band for payload, which fits its own format (no GCR decode in the loader path is claimed in the wiki text; UNVERIFIED).

## Load time for typical sizes (derived from the B/s column)

| Method | 10 KB (10,240 B) | 40 KB (40,960 B) |
|---|---|---|
| Standard serial (407) | 25 s | 101 s |
| JiffyDOS (~4,280) | 2.4 s | 9.6 s |
| Epyx FastLoad (2,500) | 4.1 s | 16.4 s |
| Final Cartridge III (~3,800) | 2.7 s | 10.8 s |
| Warp Speed 2.0 (~3,350) | 3.1 s | 12.2 s |
| Action Replay 7.5 (~6,200) | 1.7 s | 6.6 s |
| Krill (4,000) | 2.6 s | 10.2 s |
| Dolphin DOS 2 (~10,500) | 1.0 s | 3.9 s |
| Transwarp (~19,000) | 0.5 s | 2.2 s |
| fastboot ceiling (~7,800, not measured) | 1.3 s | 5.3 s |

## Which methods show no differentiator (evidence only)

- Cartridge loaders (Epyx FastLoad, Action Replay, Final Cartridge III, Warp Speed): all need a cartridge, which the Classic tier does not have; all are proprietary; no speed advantage over Krill or Transwarp in the quoted numbers; no measured IRQ behaviour. Clean-room would be needed for each.
- JiffyDOS and Dolphin DOS: ROM or hardware replacement, proprietary, and in conflict with "the core never requires an Ultimate or REU" only if they become required. Their speed is not a differentiator for the core; they are a compatibility target, not a method to build.
- Turbo Disk and Dreamload: no speed data reachable; magazine or commercial origin with no licence evidence. Candidate to cut unless someone finds numbers.
- Bitfire, Sparkle, Doynax, Spindle: no speed numbers reached. They cannot be cut or kept on evidence yet. Spindle's IRQ-loader design is the main reason to keep it in view. The primary sources are needed (linusakesson.net from a host that resolves, and the project repos).

Remaining differentiators on the evidence so far: Krill (only IRQ-safe method with a verified figure on stock hardware), Transwarp (fastest verified figure, but non-standard format and an unverified licence), and fastboot1541 (boot path only, interrupts off).

## Gaps

- linusakesson.net does not resolve from this sandbox (curl error 6); web.archive.org is blocked by the proxy policy (relay failure logged); forum64.de and lemon64.com return a Cloudflare challenge.
- GitHub raw and API for mist64/fastboot1541, bitfire and spindle repos: 404 or "not enabled for this session". add_repo was not called, since this is read-only research.
- codebase64 pages for loaders (base:fastloaders, base:irq, base:irq_disk_loader, base:cult_loader, base:turbo250_disassembled) describe techniques but give no B/s figures.
- Memory sizes: no source gives a resident byte count for any method except fastboot1541 (256-byte sector). All other footprint cells are UNVERIFIED.
- JiffyDOS disagreement: the 64'er factor gives LOAD 9.84x, the JiffyDOS wiki table gives 10.3x (124 s to 12 s). Both are kept.
