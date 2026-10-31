# Active C64 groups and 1541 / serial-bus loaders (2022 to 2026)

Scope: which loaders and drive-code techniques the scene publishes, with dates, authors and reuse statements. Sources were csdb.dk pages fetched with curl (saved under `pages_groups/`), and web search. GitHub was NOT reachable (the session's GitHub API is restricted to its own repositories, and curl to github.com returned 403), so no repository README, licence file or commit history was read. Anything depending on GitHub is UNVERIFIED.

## 1. Loaders found, with status

### Krill's Loader, repository version 194 (Plush, 2022)
- Status: VERIFIED (csdb release page read).
- Author and group: Krill of Plush; help from Bitbreaker of Nuance and Performers.
- Release: csdb release 226124, "Krill's Loader, Repository Version 194 [2022]", released 24 Nov 2022. Download is a zip hosted on csdb (loader-v194.zip, about 1340 downloads when fetched).
- Source: https://csdb.dk/release/?id=226124 (the repository itself is not reached; the csdb entry says "run make tools in the loader directory" for the packers).
- Drive support: csdb comments say it supports Dali 0.3 but not Dali 0.3.2. A comment dated 6 Oct 2026 reports a bug on a 1581: a file whose first block is on track 80 cannot be loaded. This is the only 1581 report seen, and the 1581 is out of scope for this project.
- What is new: a bitstream format change (destination pointer byte-swapped to little-endian; control bits shifted out left) announced by Krill on 14 Sep 2024 for the next release. The 194 release is not the newest; Krill said "a couple of bugfixes and a new feature or two" would come in the next release. No newer release was found.
- Reuse statement: none found on the csdb page. No licence text located. UNVERIFIED for licence.
- Other note: Krill's csdb comment points to thierer/sd2iec for SD2IEC firmware support of this loader. sd2iec is GPL (per CLAUDE.md, do not copy its code).

### Sparkle 3 (OMG / Sparta of Genesis Project, 2023; 3.1 noted Jan 2025)
- Status: VERIFIED for the csdb entry; code not read.
- Author and group: Sparta of Genesis Project, credited as OMG; Propaganda Magazine staff. Test and help credits: Loloke, Raistlin (C64GFX), Schedar and Visage (Lethargy), Soci (Singular, IDE64, VICE team), Ksubi.
- Release: csdb release 236718, "Sparkle 3 [2023]", 5 Nov 2023. Download: csdb Sparkle3.zip.
- Source: https://csdb.dk/release/?id=236718 and https://github.com/spartaomg/SparkleCPP (GitHub not reached, UNVERIFIED).
- What is new: a full rewrite in C++ (cross-platform, command-line only, Linux build confirmed by a commenter). Sparta posted "Sparkle 3.1" on 1 Jan 2025 (a csdb comment; the 3.1 file was not fetched). Commenters describe it as very fast when little CPU time is left, and easy to integrate. It is a linker and IRQ loader toolkit for multi-file projects, with sequential and index-based loading.
- Drive support and bit-protocol: not verified (no README read).
- Reuse statement: none found. UNVERIFIED for licence.
- Evidence of reuse: none found beyond the csdb comments.

### Bitfire (Bitbreaker, Oxyron, Nuance, Performers; v1.0-alpha 2021, repo maintained through 2021 and after)
- Status: VERIFIED for csdb entries; repository not reached.
- Author and group: code by Bitbreaker of Arsenic, Nuance, Oxyron, Performers; testing by The Human Code Machine (Arsenic, Masters' Design Group, MultiStyle Labs, Oxyron, Performers); help by Krill of Plush. Released under the Performers group name.
- Releases: csdb 201237, "Bitfire V1.0-Alpha [2021]", 11 Mar 2021, source https://csdb.dk/release/?id=201237 (repo https://github.com/bboxy/bitfire, not reached). Older: csdb 146211, "Bitfire 0.6 [2016]" by Oxyron, 15 Mar 2016 (a 2017 comment by Bitbreaker discourages it).
- What is new in v1.0 alpha: its own packer, with ZX0 added as a packer option (csdb comments from soci, Mar 2021). It does in-place decompression by default when the load address is known; relocated data gets an end marker and an overlap restriction, and the file grows by 18 bits. Every sector is used (Sparta's comment: "two loaders using every byte in every sector").
- Drive compatibility: a csdb commenter (Digger, 12 Mar 2021) tested it on a half-legged 1541-II. Other drives not stated. A 2019 forum post (via search) says 1541/1551 support and small resident code (at most 2 blocks after install). Not verified.
- Reuse statement: none verbatim found on csdb. UNVERIFIED for licence.
- Evidence of reuse: Plus/4 port (plus4world.powweb.com), and an unrelated fork by iszell at https://github.com/iszell/bitfire (fixed-interleave loader system). Both found via search only.

### Mafiosino Trackloader / MafioDOS V2.1 (Mafiosino and Rh70, Feb 2022)
- Status: VERIFIED (csdb read). Not an IRQ loader; a DOS and loader for cartridge and disk.
- Authors: code by Mafiosino and Rh70; idea by AW182; bug fix by GI-Joe of Arsenic, Mayday!, Master Rh70 Ultra of Orb; test by AW182.
- Release: csdb 214573, 20 Feb 2022. Downloads: Mafio-DOS_V2.1.d64, cartridge builds (Deluxe and Light), EPROM and SuperGames variants.
- Source: https://csdb.dk/release/?id=214573
- Speed: csdb comments say "as fast as DolphinDOS" for a 200-block one-file demo (KAL_123, Jan 2023), and "200 blocks in 6 seconds" (GI-Joe, Nov 2024, for Trackloader V1g inside the package).
- Reuse statement: none found.

### cc1541 V4.2 (Claus, PTV, 28 Feb 2024)
- Status: VERIFIED (csdb read). Tool, not a loader.
- Source: https://csdb.dk/release/?id=240041; project https://bitbucket.org/PTV_Claus/cc1541 and https://plus4world.powweb.com/tools/cc1541.
- Relevance: a 1541 disk-image builder with custom sector interleave; it writes Transwarp images.

### Transwarp v0.64 (Krill of Plush, 22 Nov 2020; older than the window)
- Status: VERIFIED (csdb read).
- Source: https://csdb.dk/release/?id=197710.
- Description on csdb: "50x fastload system on plain vanilla stock 1541". Krill wrote the code; testing by Map and q0w of Atlantis, SNAQZ.
- Included for context only: it is the baseline Krill's Loader and the cc1541 Transwarp option refer to.

## 2. Group-level findings (csdb group pages, fetched)

- Hokuto Force (HF), csdb group 435, https://csdb.dk/group/?id=435: members active 2022 to 2025 (coders Bugblaster, GuyGavin, Rebel 1, MP Soft, lfo). No 2022 to 2026 loader release found in the group page. UNVERIFIED for full release list (only the member listing was parsed).
- Booze Design (BD), group 505, https://csdb.dk/group/?id=505: releases 2022 to 2026 are demos and graphics ("Tabula Raster", "Partly Snowy", "Partypåg", "Saturday Night"). No loader release. Coder Pernod joined 2024.
- Oxyron (OXY), group 7, https://csdb.dk/group/?id=7: 2022 is a game ("Gleis 9 3/4"). Bitfire 0.6 is credited to Oxyron (2016). No 2022 to 2026 loader found.
- Censor Design (CEN), group 2310, https://csdb.dk/group/?id=2310: 2026 tools MagSID Editor V1, C6510 1 (a C6510 tool, not a drive loader). Members include coders psych858o, Peacemaker, Linus and Carrion (2022 onward). No 1541 loader found in the page.
- Performers, group 8937, https://csdb.dk/group/?id=8937: co-owner of Bitfire (2021). Hardware guru dEViLOCk (member since 2022). 2026 demo "Next Round"; the page does not list a 2022 to 2026 loader.
- Not checked (time): Fairlight, Triad, Resource, Nuance, Artstate, Samar, Onslaught, Bonzai, Plush (beyond Krill's entries), Cosine, Camelot, Focus, Genesis Project (beyond Sparta), Offence, Booze (beyond the page), Digital Monastery (csdb 10014).
- Note on Genesis Project and Plush: they are the source of Sparkle and Krill's Loader, so their own loader pages are the next place to look.

## 3. Community statements about the Ultimate and loaders

- The 1541 Ultimate and fast loaders: a GitHub issue on markusc64/1541ultimate2 (issue 33) reports that some fast loaders fail on firmware 3.10 and work on 3.9. A commenter says 3.10a also shows it. This is for the 1541 Ultimate II+ hardware, not the Ultimate 64. UNVERIFIED (search snippet, issue not read).
- A forum comment on a demo says the 1541 Ultimate is "more of a true 1541 emulator", so most fast loaders work, with bugs still possible. Anecdotal.
- One user reports a loader works after changing the drive ROM to a 1571 image. Single anecdote for another title.
- No csdb or loader release mentions the Ultimate 64 specifically, in what was read. Not found for JiffyDOS either (the 1581 and SD2IEC mentions are the only drive notes).
- Krill's comment on Bitfire (Mar 2021): "the current 4 popular demo IRQ loaders are all playing in the same on-the-fly decoding ballpark" (Krill, Spindle, Bitfire, Sparkle context). Spindle is by Linus Akesson (https://www.linusakesson.net/software/spindle/v3manual.pdf): an IRQ loader and linker, credited with inspiration from Krill. Not in the 2022 to 2026 window.

## 4. Gaps

- No 2022 to 2026 release found for a new 1541 IRQ loader from the listed groups beyond Krill's 194 (2022, with a 2024 format change note), Sparkle 3 (2023, 3.1 in 2025), and Mafiosino's DOS (2022). Possibly missed: releases filed under 'tools' on csdb that the group pages do not list, and GitHub repositories.
- No licence text for any of these tools was read (GitHub unreachable). Before any reuse, read each repository's LICENSE file. Per CLAUDE.md, GPL code (sd2iec, open-roms) must not be taken.
- Ultimate 64 compatibility statements for these loaders: none found.

## 5. Source list

- https://csdb.dk/release/?id=226124 (Krill's Loader 194, 2022)
- https://csdb.dk/release/?id=236718 (Sparkle 3, 2023)
- https://csdb.dk/release/?id=201237 (Bitfire V1.0-Alpha, 2021)
- https://csdb.dk/release/?id=146211 (Bitfire 0.6, 2016)
- https://csdb.dk/release/?id=214573 (Mafiosino Trackloader / MafioDOS V2.1, 2022)
- https://csdb.dk/release/?id=240041 (cc1541 V4.2, 2024)
- https://csdb.dk/release/?id=197710 (Transwarp V0.64, 2020)
- https://csdb.dk/group/?id=435 (Hokuto Force)
- https://csdb.dk/group/?id=505 (Booze Design)
- https://csdb.dk/group/?id=7 (Oxyron)
- https://csdb.dk/group/?id=2310 (Censor Design)
- https://csdb.dk/group/?id=8937 (Performers)
- https://github.com/bboxy/bitfire (not reached, UNVERIFIED)
- https://github.com/spartaomg/SparkleCPP (not reached, UNVERIFIED)
- https://github.com/iszell/bitfire (search result only, UNVERIFIED)
- https://github.com/thierer/sd2iec (GPL, do not copy)
- https://github.com/markusc64/1541ultimate2/issues/33 (search result only, UNVERIFIED)
- https://www.pagetable.com/?p=568 and https://github.com/mist64/fastboot1541 (search result only, background)
