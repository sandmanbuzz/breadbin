# Lens F: on-disk formats, the executable format, and the boot/load path

Measured on a copy of the footprint worktree (working tree, including its uncommitted edits), built in the scratchpad. Measurement scripts: `scratchpad/next/Ftools/{sim.py,sim2.py,cxstat.py}`. Tags: V = verified (read or ran it), U = unverified (inferred).

## 1. Executive summary

1. **The cost per block is the problem, not the format.** On Classic, ~0.55 s/block is the bus floor (281 bus bytes per `U1` read) and ~1 s/block is the effective rate. No format change gets close to the 10-1000x from the REU cache (on the footprint branch already), UCI, or a drive-side reader. Format work matters because it lets those paths stream.
2. **A boot reads 59 sectors (the kernel PRG) plus ~62 c64fs blocks** (simulated against the real image). On stock ROMs that is 122 s: 52 s for the PRG and ~70 s for the rest.
3. **Cheapest big win on disk: the shared error-string table.** 24 of 40 programs link `err.o` (609 B, 494 of them strings). That is about 47 of the 230 `/bin` blocks. It is a user-library change and costs the kernel 0 bytes.
4. **CX v2: delta-coded relocations** (1 B instead of 2) save 4.3 KB (17 blocks). Moving the header to a trailer puts the image on block boundaries, so exec can read straight into the process pages.
5. **Exec currently runs every program block through the 6-buffer cache.** That evicts the metadata, so each command re-reads the root and `/bin`. Bypassing the cache: boot 62 to 52 blocks, `clear` 4 to 1.
6. **The boot PRG and every c64fs file are laid out at interleave 1** (`mkimage`). That doesn't matter for the standard protocol. It is fatal for any fast reader: at 7 KB/s with in-order reads it caps at ~1.3 KB/s. The fast path needs out-of-order (rotational-order) sector reads, or an allocator that knows about interleave.
7. **Warm boot from the REU** (the stub stashes the kernel image, a tiny stage 1 brings it back by DMA), together with the existing cache: an Expanded warm boot goes from 122 s to an estimated 5–10 s. This is the best boot-contract change per byte.
8. **c64fs v2** (extents, 16-bit inode numbers in the same 16-byte dirent, mode/uid, multi-block bitmap) is medium work. It removes the indirect block, the 35 KB and 127-file caps, and gives a program one extent, which is what a streaming reader wants.
9. **Compression:** worth it for the kernel PRG (59 to ~40 sectors, decompressor in the INIT segment so no resident cost). Not worth it for CX now: it helps only Classic, and the 267 bytes of code room can't spare ~200 for a resident decoder.
10. **No package bundle.** The REU cache *is* the bundle (block-for-block like a D64). Fill it in one UCI read on Recommended. Every proposal here keeps the disk a valid CBM disk.

## 2. Current-state findings that matter

| # | Finding | Cite |
|---|---|---|
| a | The kernel is one PRG at `$0801`, loaded with `LOAD"*",8,1`. The stub copies CODE/RODATA/JUMPTAB/CODEHI up; INIT runs in place and is released. | `src/kernel/main.s:30-95,112-116`, `src/kernel.cfg` (V) |
| b | PRG = 14,916 B = **59 CBM sectors**, written on consecutive sectors from 1/0 (interleave 1). | `tools/mkimage.py:101-113` (V, ran) |
| c | `make size`: 267 B of code room below `$CF00`, 183 B below `$FFFA`, INIT 1,140 B. Pool edge `KSTART=$A100`. | `make size` output; `src/kernel/k.inc:4` (V) |
| d | A block read is `U1:2 0 t s` (~12 B) + error-channel read (~13 B) + 256 B data = ~281 bytes at 1.8 ms/byte = **0.51 s on the bus**. | `src/kernel/blk.s:426-447,470-515` (V); 1.8 ms/byte from `docs/roadmap.md:96` |
| e | Measured: stock ROMs, stage 2, 122 s to the shell, 52 s of it the PRG. JiffyDOS on the Ultimate 75.5 s. Physical 1541 + JiffyDOS: PRG in 25 s (0.42 s/sector, slow for JiffyDOS). | `docs/hardware-notes.md:117-125,145` (V, read) |
| f | Boot after the kernel: mount 3, init 10, theme 9, motd 5, login 9, passwd 5, sh 21 = **62 block reads**, 6-buffer LRU modelled. That gives an effective ~1.1 s/block (70 s / 62), against roadmap's "~70 blocks". | `Ftools/sim.py` (V, ran; the model is U) |
| g | `fs_read` copies byte by byte from a cache buffer (~30 cycles/byte, ~7.7k cycles per block). Exec loads the image and the relocations through it, so program data evicts the inode and directory blocks. | `src/kernel/fs.s:686-756`, `exec.s:188-209,226-279` (V) |
| h | CX v1: 9-byte header (`CX`, ver 1, img, bss, nrel), image, 2 B per relocation. Entry offset fixed at 0. Only c64fs devices can exec. | `tools/cx.py:11-34`, `exec.s:107-111,139-151,539-544` (V) |
| i | `/bin`: 40 programs, 54,683 B, 230 blocks. Relocations 8,686 B (**16 %** of the bytes). | `Ftools/cxstat.py` (V, ran) |
| j | `err.o` = 115 B code + 494 B strings, in 24 of 40 programs (11.9 KB of strings in total). | link maps of `rm`, `sh`, `as` (V, ran) |
| k | Allocation is first-free in block order (mkimage and `balloc`). mkimage files are contiguous, but the indirect block lands in the middle of the run (sh: data on 12/15–13/5, indirect at 13/6, data again from 13/7). | `mkimage.py:221-226,264-283`, `fs.s:329-402` (V) |
| l | Inode: 32 B, 12 direct + 1 indirect, 1-byte inode numbers in 16-byte dirents (1 + 15 name, 14 chars max). Bitmap: one block (2048 blocks). | `docs/filesystem.md:61-95`, `mkimage.py:55-68` (V) |
| m | REU cache: banks 8–18 (11 banks) above `/tmp`, so it needs a ≥1.2 MB REU. Keyed by build id; the first write of a boot re-stamps the id. A cold miss is counted (`c_miss`). | `src/kernel/blk.s:21-33,851,931` (V) |
| n | CBM side: directory chain ends at 18/1, BAM marks every sector used. | `mkimage.py:115-135` (V) |

Derived (U): the 52 s for 59 sectors is 0.88 s/sector, about 287 B/s against ~400 B/s for a normal stock LOAD. The 0.42 s/sector under JiffyDOS on the physical drive is 4–6x worse than JiffyDOS's normal ~3.7 KB/s. The interleave-1 layout (b) is the likely cause. That is a hypothesis to measure, not a finding.

## 3. Proposals

### LOW (days, clear win)

**[F1] Shared error strings out of every binary** | all tiers | −~47 blocks on the disk (230 to ~183, −20 %), −494 B RAM per running program that uses `perr` | `src/lib/err.s` only. Move `errtab` to `/etc/errors`, which `perr` reads on the error path (one file read, only when an error is printed), with fallback `"error N"` when the read fails (EIO from a dying disk). Or a kernel `strerror` syscall (494 B of kernel, which we can't afford). ~1 day | contract: error text lives in a file; binaries rebuilt | none | a disk read on the error path. Under `EMFILE` the open fails, so the fallback text shows | tests that compare stderr (`test_system` error cases). Check `make size` "largest programs" before and after.

**[F2] CX v2: trailer header, delta relocations, ABI stamp** | all | relocations 8,686 to 4,349 B (−17 blocks, V by measurement). The image starts at file offset 0, so file block *i* = process page *i* (enables F3). Relocation loop slightly faster (1 B read per entry) | `cx.py` +30 lines. `exec.s`: read the last block first (header + relocation tail), +~30 B for header parsing, delta loop ~same size as `relocate` (`exec.s:226-279`). Proposed 16-byte trailer: `magic "CX"`, `ver=2`, `flags` (bit0 compressed, bit1 needs REU, bit2 needs UCI, bit3 has imports, bit4 has overlays; unknown flag set → ENOEXEC), `img(2)`, `bss(2)`, `nrel(2)`, `entry(2)`, `zp_hi(1)` (highest ZP byte used: lets the save area be sized per process), `stack(1)` (max depth), `heap(1)` (pages to pre-grant for S12 `brk`), `abi(1)` (syscall-table version; mismatch → ENOEXEC instead of a crash). Delta relocations: 1 byte per gap <255, `$FF lo hi` escape | every CX binary and `docs` change; nothing outside the repo | none | low. Test: `make test-host` (add a cx round-trip test), smoke, `test_24_editor`, `as` and `basic` runs. Do **not** implement overlays or imports now: reserve the bits, don't buy M5's problems.

**[F3] Exec streams pages past the block cache** | all; biggest on Expanded | boot 62 to 52 bus blocks, `clear` 4 to 1, `cat` 7 to 4 (`sim2.py`, U model). With the REU cache warm, a program block becomes one REU→page DMA (~256 cycles) instead of DMA plus a 7.7k-cycle copy | `blk.s` `bread_to(dev, blk, page)`: cache hit → copy; REU cache → DMA straight to the page; bus → `iec_read` into the page. Leaves the 6 buffers alone. ~50–70 B kernel. The first user of M0-6 | none visible | F2 (page alignment; without it, handle a 9-byte skew, which is uglier) | the relocation pass must still read the relocation blocks, which is fine | `Cache` tests, smoke, a boot read count from `cache stat` (`c_miss`).

**[F4] Interleave-aware PRG layout in mkimage** | Classic/Expanded with JiffyDOS or a stock LOAD | U: likely little on the stock protocol (a sector is ~3 revolutions of transfer, so latency is half a revolution whatever the layout). Possibly 25 s to ~6–8 s on the physical JiffyDOS drive | `mkimage.py:101-113` places the sectors with stride N (10 is the DOS default; try 6–10). 0 kernel bytes | none; DOS follows the links | none | low | under VICE true-drive, stock and JiffyDOS ROMs, time `LOAD` at stride 1/6/10. On hardware, five each on the physical 1541. It costs a morning and tells us whether finding (e) is the layout.

**[F0] Measure before building** (prerequisite, 0 bytes): a cold-cache boot with `make CACHE=2` and `cache stat` gives the exact number of bus block reads at boot. That settles the 62-vs-70-block and 0.55-vs-1.1-s/block question that every estimate here depends on.

### MEDIUM

**[F5] Two-stage boot with a warm-REU kernel** | stage 1 all tiers; the gain is Expanded with a ≥1.2 MB REU and Recommended | Boot file `BREADBIN` = a 1–2 sector PRG. It probes the REU for `{magic, kernel hash}` at a reserved bank and DMAs the image to `$0801` (15 KB ≈ 15 ms); on a miss it `LOAD`s a second normal PRG `BREADBIN.K`. The kernel stub stashes the loaded image to the REU before INIT runs (~30 B, INIT, released). With the existing block cache, a warm Expanded boot ≈ stage 1 (~2 s stock) + one superblock read for `cache_attach` (~1 s) + DMA ≈ **5–10 s against 122 s** (U, arithmetic) | stage 1 ~150 B (its own PRG, not kernel space). mkimage stamps a hash of the *kernel PRG* (not the disk build id, which would be circular) into stage 1. ~3 days | boot contract: two CBM files. Other tools still see valid PRGs (§4 of this report) | REU cache (footprint) | stale kernel if the REU survives a disk swap; the hash guards it. A reset on the bench may clear the REU (`docs/roadmap.md:110`) | Cache-class VICE tests with `-reu`; boot with a changed kernel must miss.

**[F6] Compressed kernel PRG** | all | 59 to ~40 sectors (zlib-9 10,222 B; a simple byte-LZ estimate gives 49), so ~−17 s stock and −8 s on JiffyDOS physical (U, at 0.88 and 0.42 s/sector) | the decoder sits in STUB/INIT, decompresses straight to KRAM/JT/CODEHI and is then released: **0 resident bytes**. ZX0-class decoders are ~200 B (check licence and source per policy; or write our own LZ, ~150 B) | none visible | F5 if done together (stage 1 can be the decompressor) | low. Smoke under VICE, byte-compare KRAM against the uncompressed build.

**[F7] c64fs v2: extents and wider numbers** | all | no indirect-block read (−1 block per sh/as/basic/edit load), files up to 8×255 blocks, >127 files, an exec/mode bit, and a uid for `login` and `passwd`. Inode stays 32 B: `type, mode, uid, nlink, size(3)`, 8 extents × `(start16, len8)` = 24 B, 1 spare (`major` overlays extent 0 for devices). Dirent stays 16 B: `ino16` + 14-byte name, NUL-padded and not terminated at 14. Bitmap from the superblock, multi-block. The allocator takes the first contiguous run ≥ the needed length near track 18, as DOS does, to cut seeks between the inode track (19) and the data | `fs.s` `bmap`/`balloc`/`itrunc`/`dir_*` rewritten (~same size, U), `mkimage.py`, `format.s`, fsck (S2). ~1–2 weeks, overlaps S3/S7 | disk format; all images rebuilt; `docs/filesystem.md` | S2 (fsck), S3 | fragmentation on a busy disk degrades to many extents; fall back to "not contiguous, slower" and never fail | host tests on mkimage v2, `test_07`, `test_10`, `format` tests, the REU `/tmp` (16-bit blocks finally reach a 16 MB REU).

**[F8] UCI prefill of the REU cache** | Recommended | first boot becomes a warm boot: the cache layout is block *b* at page 4+*b* (`blk.s:21-24`), which is a D64 image shifted by 4 pages. So one UCI read of the mounted `.d64` (174,848 B) into the cache banks, plus setting the 683 valid bytes, fills it. Validate by comparing the REU copy of the superblock with the one `cache_attach` reads from the bus | ~150 B in the UCI driver | none | S10 (UCI core). `LOAD_REU` assumes a 16 MB REU (`docs/roadmap.md:178`) and the bench has 2 MB, so plan on DOS reads in 512-byte chunks and our own DMA | **coherence**: when does the Ultimate write a mounted, drive-written D64 back to its host file? If it writes lazily, the host file can carry the new build id but miss later writes. Also: how to learn the image path | hardware session (WP1): write via the drive, then read the host file over UCI, and diff.

### STRETCH

**[F9] Rotational-order sector streaming (fast-read M0-8 part 2, extent-aware)** | Classic and Expanded on 1541-class drives | arithmetic: a 7 KB/s link moves 256 B in 36 ms ≈ 3.8 sectors of rotation (200 ms/21 on tracks 1–17). Read in order at interleave 1, each block waits ~164 ms, so ~1.3 KB/s. With the drive reading the sectors of a *list* in the order they pass the head, a whole track takes 1–2 revolutions, and the link sets the pace: sh's 16 blocks go from ~9–17 s today to ~0.6 s | drive code (Krill/Bitfire-derived, per `docs/design/fast-io.md` §15), host loop ~150 B, `blk_read_list(extent)` | `blk.s` API grows a multi-block call | F7 (extents give the list), M0-6, **the physical-1541 stall understood first** (`docs/wip.md:65-67`), and the JiffyDOS 5.0 ROM's differing entry points (`docs/hardware-notes.md`, the 2865a07 note) | high, hardware-bound | VICE true drive with both ROMs, then the bench A/B. Alternative if this stays out of reach: an interleave-aware allocator (stride ~4–5 on 1–17) gets ~5.6 KB/s with in-order reads, at a fixed cost to the slow path of ~0.

**[F10] Root on UCI, exec from any backend** | Recommended | no D64 in the loop. Stage 1 probes `$DF1D=$C9`, reads `kernel` from a host directory, mounts UCI as `/`; the D64 stays the Classic fallback | `exec.s:107-111` must go through the S6 interface (open/read/seek) instead of `iget`/`fs_read`. A trailer header (F2) needs one seek, which UCI has | exec from CBM DOS too, which is free once the interface exists | S6, S10, S11 | deployment model (a USB directory versus an image) | bench.

**[F11] Lazy-loaded `cbm` module** | all | −8 of 59 PRG sectors at boot (CODEHI 1,902 B), loaded on the first CBM mount | a fixed-address module file and loader | memory-lens decision (what shares the region) | the module must match the kernel build (hash in the file) | `mount` of a CBM disk after boot.

### Package bundle (question 4): don't

A `/bin` archive adds a second namespace and its own staleness problem. What it would buy is already there. On Expanded, the REU cache keyed by build id persists across boots and is effectively the bundle. Add `cache warm /bin` (reads every `/bin` block once; ~230 × 1 s now, seconds after F9) for people who want the first load fast. On Recommended, F8 fills it in one transfer, and F10 removes the need. S8 ("copy `/bin` to the REU RAM disk at every boot", `docs/roadmap.md:242`) is superseded: it pays the whole slow read on *every* boot, where the cache pays it once per build.

### Q5: what keeps the Classic disk usable by other C64 tools

Kept by every proposal: the BAM marks every sector used, the CBM directory on 18/0–18/1 holds valid PRG entries, and the sectors are standard 256-byte GCR. F1–F3 and F7 live inside c64fs and are invisible to the DOS. F4 is still an ordinary chained PRG. F5 makes two ordinary PRGs (a file copier must copy both). F6 is still a PRG with a SYS stub. F9 reads standard sectors. **Avoid:** custom GCR or track formats (Transwarp/Sparkle-style, already cut in `fast-io.md` §12), tracks 36–40, or kernel sectors outside a CBM chain (pure fastboot1541 raw sectors: a file copier would take only stage 1). **Existing hazard, worth a line in `docs/filesystem.md`:** running the DOS `V` (validate) command on a Breadbin disk frees every c64fs block, since no CBM file owns them, and the next DOS write destroys the filesystem. U, standard DOS behaviour, not tested.

## 4. Things I'd NOT change

- **The page-granular relocation model.** Only high bytes are patched, and that is the right trade. Fixed per-slot load addresses or whole-process REU swapping cost more than a 1-byte delta table. A bitmap encoding measured worse (5,724 B against 4,349 B for deltas).
- **CX compression now.** It helps only Classic (~48 blocks with F2), costs ~200 B of resident decoder against 267 B of room, and loses to F9 and the cache. Reserve the flag bit (F2) and revisit after M0-7.
- **Hashed or B-tree directories.** `/bin` is 3 blocks, and a linear scan is fine. If anything, mkimage can sort `/bin` by use so `sh`, `ls` and `cat` sit in block 0.
- **Skipping the status read after `U1`** (`docs/roadmap.md:106`). It is ~13 of 281 bytes (~5 %), and it removes the per-block error detection that the stall research depends on.
- **Moving c64fs metadata onto track 18.** The 17 free sectors there aren't worth confusing DOS tools.

## 5. Open questions for the humans

1. Run F0. Is the post-kernel boot really ~62 bus reads at ~1.1 s each? If it's closer to 120 reads, something (init, login, theme) re-reads more than the model shows, and that's the first thing to fix.
2. F4: is the physical-drive 0.42 s/sector under JiffyDOS the interleave? (One VICE morning answers it.)
3. F8: when does the Ultimate write a drive-modified D64 back to the host file, and can UCI report the mounted image's path?
4. The REU cache needs 19 banks, so a 512 KB 1750 gets no cache at all. Should the cache shrink `/tmp` on small REUs, so Expanded on period hardware benefits too?
5. F1 moves message text to a file: acceptable for `EIO` paths (fallback `"error N"`)?
6. Order of F5 against M0-8's fastboot1541 stage 1: F5 needs no drive code and works on any drive with an REU. I'd do F5+F6 first and keep fastboot for Classic once the stall is understood.

## Recommended staged plan

| Stage | Items | Tier | Kernel bytes | Expected effect |
|---|---|---|---|---|
| 0 | F0, F4 (measurements and a mkimage tweak) | all | 0 | facts for everything else |
| 1 | F1, F2, F3 | all | ~+100 | /bin 230 to ~166 blocks; boot −10 blocks; warm command loads become DMA-to-page |
| 2 | F5 + F6 | Expanded gains; Classic −17 s | 0 resident | warm Expanded boot ~5–10 s |
| 3 | F7 (with S2/S3/S7) | all | ~0 net | no indirect reads, no 35 KB/127-file caps, single-extent programs |
| 4 | F8 (after S10), F10 (after S11) | Recommended | UCI budget | first boot fast; no bus |
| 5 | F9 (after the stall is localised) | Classic | ~150 + drive blob | Classic block reads ~15–25x faster |
