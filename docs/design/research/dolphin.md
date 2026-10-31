# DolphinDOS and C64 fast serial/parallel protocols: research notes

Scope: read-only web research. Nothing was executed; downloaded text was treated as data. Nothing was written inside /home/user/breadbin.

## Network limits

Blocked (DNS failed, sites not reachable from this session): csdb.dk, ar.c64.org (ReplayResources/c64.org wiki), mega65.github.io (open-roms rendered docs), odd.blog. Not attempted after those failures: codebase64.net, c64.com, lemon64, forum.6502.org, sta.c64.org. github.com fetches worked. Direct `curl` to github.com returned 403 (proxy).

Status tags: VERIFIED = page or file fetched and quoted. UNVERIFIED = seen only in search snippets, or not checked.

## 1. Who reverse-engineered or re-released DolphinDOS

- Open ROMs protocol doc (MEGA65), "Protocol-DolphinDOS": https://mega65.github.io/open-roms/doc/Protocol-DolphinDOS.html . Search snippet says the protocol was reverse engineered from IEC logs produced by the VICE emulator, and that it is "AFAIK ... the first attempt to document the protocol". Author not named; date not found. The page itself was NOT fetched (blocked). Only a summary from a search-result page and a GitHub-hosted copy's summary were seen. UNVERIFIED.
- Open ROMs source tree: https://github.com/MEGA65/open-roms/tree/master/src/kernal/iec_fast contains dolphindos_detect.s and dolphindos_load.s (file listing VERIFIED).
- donnchawp/DolphinDOS2 (GitHub, Unlicense): https://github.com/donnchawp/DolphinDOS2 . README says DolphinDOS 2 "is a kernal ROM replacement for the C64 and 1541 disk drive to speed up disk operations", contains kernal.asm and 1541.asm, ships ROM images dd2_kernal.rom and dd2_1541.rom, and that the images "can be installed in an Ultimate64 or Commodore 64 Ultimate without any extra hardware" (VERIFIED as fetched). Repo says "Version 1" tagged 1.0 with 36 commits; no date seen. Authorship of the code and whether it is a clean-room re-implementation or a dump of commercial ROMs is NOT established. Treat with care.
- csdb.dk entries (search snippets only, csdb blocked): release id 146652 (DolphinDOS 3 for 1541-II, Silver Dream, 2016) and id 137270 (JiffyDOS mod of the DolphinDOS kernal, LogicDeLuxe, 2015). Snippets do not show source code. UNVERIFIED.
- odd.blog "DolphinDOS 2: Fixing a 35-Year-Old Bug That Never Was": https://odd.blog/?p=89592600 . Search snippet only; page blocked. Date and content UNVERIFIED.
- Not found: any recent published RE of the parallel-cable transfer protocol beyond the MEGA65 doc.

## 2. Is the protocol documented?

Open ROMs doc (summary of the page as fetched through a GitHub-hosted copy; the rendered page itself was blocked, so treat as UNVERIFIED for exact wording):
- Byte transfer: sending reuses the standard IEC byte mechanism. The C64 puts the byte on CIA2 port B (set to output) and signals validity. Receiving: after the talker pulls CLK, the C64 reads the byte from CIA2 port B and then acknowledges.
- Handshake: standard IEC CLK and DATA used for busy/ack.
- Mode detection: after OPEN (0xF0-0xFF) or REOPEN (0x60-0x6F) under ATN, the controller polls CIA2 ICR and port B until ICR reads $10, before turnaround to listener.
- Speed: no figures given. The page says timing is no stricter than standard IEC; the ROM only masks interrupts and does not touch VIC-II registers.
- Caveat in the page: "the information provided here might be incomplete or not fully accurate!"

Open ROMs build options (search snippet, UNVERIFIED): an IEC option adds "DolphinDOS fast protocol to the IEC bus, using UserPort cable", plus a faster LOAD loop for the DolphinDOS protocol. Source: https://github.com/MEGA65/open-roms/ (search result). The source file dolphindos_load.s begins with "DolphinDOS protocol support for IEC - optimized load loop" and has `sei` at the top of the loop (VERIFIED from fetched copy).

## 3. Parallel cable and hardware modification

- Protocol uses CIA2 port B. On a C64 that is the user port, so the transfer path is the user port, not the serial IEC connector. The fetched summary calls this "standard IEC" timing, which is in tension with that; this is UNRESOLVED and needs the rendered Open ROMs doc.
- Open ROMs build text says "UserPort cable" (search snippet). A parallel cable is therefore very probably required.
- Drive side: the parallel cable connects the user port to the 1541's unused VIA #1 port A. Generic pinout from 64Copy Central (search snippet, pages not fetched): VIA pins 2-9 (PA0-PA7) to user port C, D, E, F, H, J, K, L (PB0-PB7); PA2 to user port E. Handshake: CA2 (VIA pin 39) to user port B (FLAG2); CB1 (VIA pin 18) to pin 8 (PC2). Source: https://sta.c64.org/cbmpar41c.html (blocked) and https://ist.uwaterloo.ca/~schepers/1541par.html (search result). UNVERIFIED. DolphinDOS-specific pinout was NOT found.
- A physical 1541 needs DolphinDOS drive ROM (EPROM swap) plus the cable. This is an ROM change, not a board mod, per the search snippets. UNVERIFIED.
- Ultimate 64: the DolphinDOS2 README says the ROM images run on Ultimate64 with "parallel drive connection" enabled in its settings, and no extra hardware. VERIFIED from README text; hardware behavior not checked.
- 1541 Ultimate docs (https://github.com/GideonZ/1541u-documentation, readthedocs hardware/userport page seen in search: https://1541u-documentation.readthedocs.io/en/latest/hardware/userport.html ): not fetched in detail; no fast-path/DolphinDOS statement seen. UNVERIFIED.

## 4. Licence statements (verbatim)

- MEGA65/open-roms root LICENSE, https://github.com/MEGA65/open-roms/blob/master/LICENSE (VERIFIED):
  "The following copyright notices apply to the entirety of this package, ... including each source file, unless otherwise noted in each file or directory."
  "Copyright Paul Gardner-Stephen, 2019."
  "Copyright Roman Standzikowski (FeralChild64), 2019-2021."
  "This program is free software: you can redistribute it and/or modify ... it under the terms of the GNU Lesser General Public License as published by ... the Free Software Foundation, either version 3 of the License, or ... (at your option) any later version."
  Some BASIC files are MIT, Copyright Microsoft Corporation (per fetched summary).
- dolphindos_load.s: no per-file license header (VERIFIED from fetched copy). The root LICENSE applies by its "unless otherwise noted" wording.
- donnchawp/DolphinDOS2 LICENSE, https://github.com/donnchawp/DolphinDOS2/blob/master/LICENSE (VERIFIED): "This is free and unencumbered software released into the public domain." (The Unlicense.) Note that this does not clear any third-party DolphinDOS copyright in the ROM images.
- mist64/fastboot1541, https://github.com/mist64/fastboot1541 (VERIFIED from fetched README): "Do anything you want with it, but giving credit and emailing me about its use is very much appreciated." Credit: Michael Steil. Not an OSI licence; attribution request.
- GideonZ/1541u-documentation: no licence statement seen in the fetched page. UNVERIFIED.

## 5. Is open-roms the only open DolphinDOS code?

No. Open ROMs is the only one with a usable, licensed source tree found here (LGPLv3-or-later, per root LICENSE). donnchawp/DolphinDOS2 is a second open source (Unlicense) with kernal.asm/1541.asm, but its provenance is unclear. Not checked: any other GitHub forks. UNVERIFIED for completeness.

## 6. Other fast protocols with public or "free to use" host-side source

- Epyx FastLoad: drive-code disassembly mirrored at https://mirrors.archeobits.com/commodore/www.zimmers.net/anonftp/pub/cbm/c64/diskutil/fastloaders/epyx_fastload_drive_code.asm (search snippet; says Dave McMurtrie, Feb 2024, credits Scott Nelson). No licence found. Copyright status UNVERIFIED; treat as copyrighted.
- WarpSpeed: source separate from ReplayResources archive (ar.c64.org, blocked). OpenC64WarpSpeed build project https://github.com/SukkoPera/OpenC64WarpSpeed seen in search, not checked. No licence found. UNVERIFIED; treat as copyrighted.
- fastboot1541 (Michael Steil): see section 4. VERIFIED. Autostart loader, uses a fast second stage (author's claim: about 10x the speed of serial for the next stage).
- Parallel-cable hardware projects (xu1541, 64Copy, XH1541/XP1541): documentation pages at https://ist.uwaterloo.ca/~schepers/MJK/parallel_cable.html and https://ist.uwaterloo.ca/~schepers/cables.html (search snippets). Not fetched; licence UNVERIFIED. The xu1541 note in search says the design cannot transfer copy-protected images.
- sd2iec (https://github.com/iszell/sd2iec) and IECFAST (https://github.com/ozw1z5rd/IECFAST): seen in search results, not checked. UNVERIFIED.
- Turbo tape / Action Replay / Final Cartridge: not researched further in this session. UNVERIFIED.

## Open questions

1. Rendered Open ROMs protocol doc (blocked): needed for exact handshake, cable pinout, and the "standard IEC" vs CIA2 port B question.
2. csdb.dk and codebase64.net (blocked/not attempted): would give release dates and any source releases.
3. Licence of the DolphinDOS ROM code itself (copyright held by the original DolphinDOS owners): unresolved.
