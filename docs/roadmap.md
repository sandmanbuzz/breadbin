# Roadmap

Where this fork is heading, and the first stories. Written 2026-10-30 after a first-pass evaluation; expect it to change as the stories teach us things.

## Direction

- **Goal:** make Breadbin a place where real software gets written *on* the machine, starting with a small compiler. The existing `as` and `basic` show the shape; the limits below are what stop the next step.
- **Targets:** a stock C64 + 1541 keeps booting (the IEC path stays), but the design is free to assume an Ultimate 64 / Ultimate-II+ when one is detected at runtime.
- **c64fs v1 compatibility is dropped.** There are no known users. The v1 code paths and on-disk format can go. If a second filesystem returns later, it comes back as a backend behind the filesystem interface below.
- **Everything new is detected at runtime**, not assumed, so one disk still boots everywhere.

## What stops us today

| Limit | Where | Why it matters |
|---|---|---|
| ~30 KB total process memory; programs get a fixed image + BSS at spawn and cannot grow | `mem.s`, `exec.s` | A compiler needs symbol tables that scale with the source. |
| `as` caps output at 8 KB and 220 symbols | `src/bin/as.s` (`OBMAX`, `NSYM`) | Compiler output is label-heavy, so this is hit early. |
| Free zero page for a program is about 13 bytes (`$23–$2F`); hardware stack slice is 130 bytes | `include/breadbin.inc`, `kernel.cfg` | Compiled code needs a software stack and a small, fixed runtime footprint. |
| Files max 35,840 bytes; 127 files per disk; 14-character names | c64fs (`fs.s`) | Multi-file projects and long sources do not fit. |
| Disk reads run at about one block per second and stall every process | `blk.s`, KERNAL serial path | The edit, compile, run loop is painful at that speed. |
| About 1.9 KB of kernel space left (`$C795` to `$CF00`) | `kernel.cfg` | Every kernel feature has to be paid for. |
| No CI; 25-minute system tests; storage geometry duplicated in four places | repo | Refactoring the filesystem is unsafe without a net. |

## Storage model

Three kinds of storage back a mount, and the kernel should treat them uniformly through a small filesystem interface (lookup, read, write, readdir, create, unlink, rename, stat). Today the kernel branches on `dev_type` in about ten places instead.

| Backend | Granularity | Notes |
|---|---|---|
| **c64fs** on a block device (1541 sectors, REU) | blocks | Rewritten as v2 (below). |
| **CBM DOS** (`cbm.s`) | files | Already file-level. This is the natural home for the Ultimate's **Software IEC** drives, which present a host filesystem as a CBM DOS device. Needs subdirectory (`CD`) support and a way to run programs from it. |
| **UCI DOS target** (`uci.s`, new) | files, with random access | The Ultimate's own file API over cartridge-port registers: open, read, write, 32-bit seek, stat, rename, delete, mkdir, directory listing, a clock, and host-file to REU DMA. No block size, no serial bus, FAT long names, effectively unlimited files. See "The Ultimate Command Interface". |

## Platform tiers

Decided 2026-10-30. One disk boots everywhere, and features are chosen by probing at boot, not by build variant.

| Tier | Machine | What we promise |
|---|---|---|
| **Classic** | Stock C64, a 1541 or compatible, no REU | Boots to a shell. Pipes, jobs, the editor, `basic` and `as` work. Maintained and tested (VICE CI), but gets no new features and no speed promises. "It's going to suck on the thing you pulled out of the attic." |
| **Expanded** | Classic plus an REU | Everything in Classic, plus the REU RAM disk and, when built, overlays and swapping. |
| **Recommended** | Ultimate 64, C64 Ultimate, or Ultimate-II+ cartridge, UCI enabled | Everything: Ultimate file storage, a large REU, turbo, the fast paths. New work targets this tier first and degrades downward. |

Rules:

- **The core never requires the REU or an Ultimate.** The kernel, shell and base commands run on Classic. Features beyond the core are capability-gated; one that cannot degrade says what it needs and refuses (a compiler job that needs the REU says so).
- **Each capability has a probe and a fallback.** Turbo: read `$D031`, and if it is not `$FF`, set the CPU speed index. UCI: read `$DF1D` for `$C9`. REU: detect size (extend detection beyond the current 8 MB scan to 16 MB). Drive geometry per device, below.
- **CI covers Classic and Expanded with VICE** (including `-reu`), and Recommended through the hardware bench (S9). That keeps the common case automatically tested and the Ultimate paths tested on real hardware.
- **Real drives.** A physical 1541 is the validation target for the IEC driver (M0-4), alongside the Ultimate's emulated drives. A 1581 is available too, but devices other than the 1541 are nice-to-have (below).

**REU today.** It is optional and only backs `/tmp`; the system tests run both with and without one. It becomes de facto required for Expanded features that need fast backing store (overlays, swapping, REU-resident `/bin`). That is acceptable, because those are Expanded and Recommended features and Classic keeps working without them.

**Turbo.** On the Ultimate 64, `$D031` exists only when the Turbo Mode setting in the Ultimate's menu is "U64 Turbo Registers" or "Turbo Enable Bit"; otherwise it reads `$FF`, as does a stock C64's unused VIC register space, so the probe and the write are harmless everywhere. Bits 0 to 3 are the speed index. Index 15 is the maximum on both models: 48 MHz (Ultimate 64) and 64 MHz (Ultimate 64 Elite-II). Two cautions:

- The CIAs, VIC and the serial bus stay at 1 MHz. Any cycle-counted loop, including the KERNAL's IEC routines, runs far too fast under turbo, so the IEC driver (M0-4) must switch turbo off around bus transfers, or time by CIA timer. Turbo must not be enabled before then.
- Bad-line behaviour is configurable (`$D031` bit 7). Leave the default.

Enabling turbo is a one-line story once M0-4 lands, and it should be a runtime setting (a `turbo` command) as well as a boot default.

## Block devices and the filesystem

**Decision (2026-10-30): 1581 and other non-1541 devices are nice-to-have, not milestone deliverables.** Do not design around them; do not buy a later milestone's problems now. Leave a clean campsite:

- The IEC driver (M0-4) takes the drive number as a parameter and does not hard-code device 8 beyond what the code already does.
- Per-device geometry stays in the one existing table in `blk.s`.
- No new abstractions for devices we are not supporting.

For when the decision is revisited: the c64fs bitmap is one block and addresses 2048 blocks, so a 1581 (3200 blocks), a 16 MB REU RAM disk or an IEC hard drive does not fit without a scoped v2 (multi-block bitmap, wider inode numbers, geometry from the superblock). A 1571 (1366 blocks) fits as is. Block commands (`U1`, `U2`, `B-P`) are known to work on the 1541; other drives need checking on real hardware. The file-level paths (CBM DOS backend, UCI DOS) do not have this problem.

## Memory budget

Measured 2026-10-31, after M0-1 to M0-4. The takeover cost the kernel 1.9 KB (18.3 KB to 20.2 KB: keyboard 747, bus and channels about 590 more than the ROM calls they replaced, screen about 290, the rest vectors) and freed 8186 bytes of ROM space, which is the net 6 KB predicted when M0 was planned.

| What | Bytes |
|---|---|
| Kernel image now: code 13,444, read-only data 745, BSS 6,002 | 20,191 |
| Where it lives: `$8000–$CEFF` | 20,224 (33 spare) |
| Free and unused: `$E000–$FFF9` (the dead ROM shadow) | 8,186 |
| Free and unused: `$CF5D–$CFFF` (past the syscall table) | 163 |
| User process pool: `$0800–$7FFF` | 30,720 (120 pages) |

Where the kernel's bytes go: `proc` 4321 (3315 BSS, of which 2304 are the per-process save areas), `file` 2986, `fs` 2847, `blk` 2682 (1536 BSS is the block cache), `cbm` 1956, `exec` 1373, `con` 1363, `iec` 780, `kbd` 747.

**Levers, biggest first** (all are independent):

1. **M0-5, use `$E000–$FFF9`: +8186 bytes, almost free.** Either as room for kernel growth (the UCI driver, the filesystem interface) or, by moving the pool's upper edge from `$8000` to `$A000`, as 8 KB more for user programs (30 to 38 KB). All the kernel fits below `$A000` and `$E000` together with about 190 bytes to spare, so the second choice leaves no growth room until the space pass has run. The boundary is one constant, so decide it last: build for growth first, and move the boundary when the kernel's real size is known.
2. **Make the block cache and the save areas dynamic: about 2.6 KB.** The 1.5 KB block cache and the 2.3 KB of per-process save areas are fixed BSS whether or not they are needed. Cache buffers can come from the free end of the page pool (idle memory becomes cache, and processes take it back), and a process's save area can be sized to the zero page and stack it actually uses.
3. **Overlays for rarely used kernel code: about 2 KB now, more later.** The CBM DOS layer (`cbm`, 1.9 KB) is used only when a CBM disk is mounted. A loadable-module facility is wanted anyway for program overlays and text paging.
4. **The space pass (M0-7): about 1 KB.** Syscall stubs 248, shifted and control key tables about 150, factoring in `file` and `fs`, working-directory strings (12 x 48 = 576 bytes, could be an inode and rebuilt on demand).
5. **Small and free: `$CF5D–$CFFF` (163 bytes)**, one more linker region.
6. **For user programs, not the kernel:** each program carries about 1.2 KB of library (the smallest, `clear`, is 1229 bytes). A shared resident library would save that per running program. Program overlays and REU staging help the big ones (`as` 6.4 KB, `basic` 5.6 KB).
7. **Not worth it yet:** page `$03` (about 256 bytes of dead tape buffer and vectors) and the 4 KB under the I/O area (reachable only with I/O switched out).

## Disk speed

Measured on the real C64 Ultimate by the hardware session: with our own bus code (standard protocol only) boot takes about 75.5 s against 46.5 s for the stage-1 build, and `clear` 6.7 s against 3.3 s. Stage 1 was riding on the ROM's JiffyDOS fast protocol. At the bus, a standard talker sends a byte in about 1.8 ms (the drive sets that pace, so our receive side cannot go faster), a block read is about 0.55 s, and booting reads about 70 blocks.

Options, with what each costs and which machines it helps:

| Option | Helps | Cost and risk |
|---|---|---|
| **REU-backed block cache**, validated by a build id in the superblock | Anything with an REU (the Ultimate has 2 MB): repeat boots and every repeated command load become near-instant, whatever the drive | Moderate, no bus work, no ROM or protocol dependency. Write-through keeps it consistent; the build id guards against a rebuilt image. First boot after a rebuild is still slow. |
| **Ultimate file backend (UCI DOS)** (S10, S11) | The Recommended tier, and removes the bus altogether | Larger; needs kernel room (M0-5) and the filesystem interface (S6). The real answer for the Ultimate. |
| **Fast loader code uploaded to the drive** (M0-8, `fastboot1541`) | Any 1541-class drive, stock or JiffyDOS: faster boot, optionally faster reads | Moderate; the drive routines it calls must be checked against the JiffyDOS ROM; not for the 1581 or Software IEC. |
| **JiffyDOS host protocol** | Machines and drives that have JiffyDOS, which includes the hardware bench | Proprietary and reverse-engineered; the only reference is the ROM images (kept outside the repo) or third-party drive code, which raises the licensing question we have deferred. Does nothing for stock drives. Under VICE the JiffyDOS ROMs are a working reference to observe at the bus level. |
| Skip the status read after each block read | Every drive: about 10 to 15 percent | Small, but it removes error detection per block. |

**Requirements for the REU cache (from the hardware session, 2026-10-31).** It must never hide bus problems or lock out Classic. So: (1) it is optional at run time and absent without an REU (the core never requires one); (2) it has an off switch that does not need a rebuild of the image: a `cache off|on|stat|flush` command, plus a build-time default (`make CACHE=0` always hits the bus; `make CACHE=2` uses the cache but starts every boot cold, for non-interactive bench boots on an REU that keeps its contents); (3) bus errors are counted and reported even when most reads are cache hits (`cache stat` shows hits, misses, bus errors), and a miss path is exercised on every boot by the first read of each block; (4) the cache is write-through and keyed by the build id, so a stale REU image after a rebuild is discarded. The IEC research uses the cache-off image.

Order of work, agreed: REU cache, then the UCI file backend (it also removes the reset-and-lose-the-REU-image penalty on the hardware iteration loop), then the IEC fast paths, with the IEC research on the bench continuing in parallel with the cache off.

Recommendation: do the REU cache first (it fixes the test-run time on the hardware we have, with no protocol work), then the UCI file backend as the principal fast path, and treat JiffyDOS and drive-side loaders as optional extras for later. Deferring JiffyDOS is reasonable because the platform we are building toward does not need it.

## Memory strategy

**Where we are.** BASIC is already out: the boot stub sets `$01=$36` (`src/kernel/main.s`), and the kernel image runs from `$8000` and is about 18.3 KB, so it already occupies `$A000–$BFFF`, the old BASIC ROM space. Process pages come from `$0800–$7FFF` (120 pages, 30 KB). The only ROM left in the CPU's map is the KERNAL at `$E000–$FFFF` (8 KB) plus the I/O area at `$D000–$DFFF`.

**How much the kernel leans on the KERNAL.** Measured by grep over `src/`:

| Group | Calls | Where |
|---|---|---|
| Screen editor | `CHROUT` (9 sites), `PLOT` (`$FFF0`) | `con.s` |
| Keyboard | `SCNKEY`, `GETIN` (2), `UDTIM`; also the KERNAL's key buffer (`$C6`, `$0276`) and stop-key flag (`$91`) | `proc.s` IRQ, `con.s` |
| IEC and file channels | `OPEN` (3), `CLOSE` (4), `CHKIN` (2), `CHKOUT` (3), `CHRIN` (4), `CLRCHN` (14), `SETLFS` (3), `SETNAM` (3) | `blk.s`, `cbm.s` |
| Interrupt plumbing | `jmp $EA81` (IRQ exit), vectors `$0314`, `$0316`, `$0318` | `proc.s`, `main.s` |

That is a thin surface: console, keyboard, and an IEC driver. No tape, RS-232, BASIC or floating-point routines are called.

**Spike (not committed).** The KERNAL was copied onto itself in `kmain`, the machine switched to `$01=$35` (RAM at `$E000–$FFFF`, I/O visible), and the first 1 KB (`$E000–$E3FF`, the tail of BASIC that lives at the start of the KERNAL ROM) was filled with `BRK`. Six system tests passed unchanged under VICE: banner, echo, a three-stage pipe, Ctrl-C on a blocked reader, the assembler, and the full-screen editor. This shows a RAM-resident KERNAL works and that BASIC's tail is not used. It is not a proof of reachability for the rest of the ROM.

**Approach.** Copy-and-patch gets us the shadow, but it does not free memory by itself: the leftover ROM routines sit at fixed addresses with holes between them that nothing can use. The memory comes from *replacing* the KERNAL dependencies one group at a time, and finally dropping the shadow so all of `$E000–$FFFF` belongs to us. The shadow copy is the safe scaffolding for that, and every step is individually testable.

**What it is worth** (estimates, to be confirmed as each step lands):

- **About 6 KB net of RAM** at the top of memory (8 KB freed, less about 1.5–2 KB for our own keyboard, screen and IEC code). With the kernel's code moved up there, the process pool can grow from 30 KB to roughly 36–38 KB.
- **A little zero page, by policy not wholesale** (see "Zero page policy"). A compiler is short of it: a program has about 13 free bytes now. The first source is the 48 bytes at `$60–$8F` that nothing uses today; poaching retired KERNAL locations (tape, RS-232) is the second.
- About 512 bytes at `$0200–$03FF` (KERNAL and BASIC variables, tape buffer), and the hardware vectors become ours.
- **Control over the IRQ and the bus.** Our own IRQ entry skips the KERNAL's indirection, and an own IEC driver is the precondition for making disk I/O less of a stall later.

**What it costs.**

- The IEC driver must be correct on real hardware, not just under VICE. VICE emulates the bus well, and an Ultimate's emulated drive is forgiving, but a real 1541 is the final judge.
- JiffyDOS acceleration of the KERNAL's serial routines is lost, since we would no longer call them. On an Ultimate this is moot because file access goes over the UCI. On a stock machine with JiffyDOS it is a regression unless we later implement a fast protocol.
- The reset path still maps ROM, so a reset always lands in the KERNAL and then reboots from disk. That is fine for us.

**LOAD and SAVE as a primitive.** They are memory-to-file block moves, and a kernel primitive that streams a run of pages to or from an open channel serves `exec`, overlays and swapping alike. The speed gain depends on the transport: modest on a stock 1541, large through the REU and the Ultimate (`LOAD_REU`, DMA `LOAD`). It is cheap to add once the IEC driver is ours.

## Zero page policy

Decided 2026-10-30: **keep zero page stock-shaped.** The layout is part of what developers expect from the hardware, and we do not turn it into foreign territory except as a last-resort architectural refactor.

- **Familiar means the stock address keeps its stock meaning.** Where a replacement still provides the service, it keeps maintaining the well-known locations: `ST` (`$90`), the stop-key flag (`$91`), the jiffy clock (`$A0–$A2`), the keyboard buffer count (`$C6`) and buffer (`$0277`), and the cursor position and line pointer (`$D1–$D3`, `$D6`). That is cheap, and it keeps anything written against the stock map working. These locations are in the current set of direct references.
- **We may poach locations whose service we removed**, such as the tape and RS-232 variables inside `$90–$FF`, once nothing reads them. Each poached address goes in a table with its stock meaning and our use, so there are no surprises. Do not poach a location with a still-live meaning.
- **The free zero page we have today is not KERNAL-owned.** The kernel uses `$40–$5F` of the `$40–$8F` it reserves, so `$60–$8F` (48 bytes, BASIC's old area) is unused. That is the first place to look for more program zero page, and it needs no stock address to change meaning. Programs already see a custom per-process layout (`$02–$3F` is saved and restored per process, argv at `$20`), and that part is ours already.
- **`$FB–$FE` stays free** for the boot stub and programs, as in stock.
- **Who decides when it is needed.** The compiler's real zero page need is measured at S14, not guessed now.

**Stock behavior retired so far** (M0-2, M0-3): SHIFT+C= no longer switches the character set (`$0291` is ignored); the key-decode state at `$F5–$F6` and `$028E–$0290` is not maintained; RUN/STOP, SHIFT, CTRL and C= never enter the key buffer, and SHIFT+RUN/STOP does not expand to a load command. The screen editor's colour pointer at `$F3`–`$F4` is not maintained (colour is global), and the insert, quote and line-link state (`$D4`, `$D8`, `$D9`–`$F1`) is gone. Everything else the keyboard and screen touched keeps its stock meaning.

The stock meanings above are from the standard C64 memory map and have not been checked against the ROM image; `da65` is installed to do that when the poaching table is first written.

## KERNAL takeover: how the addresses work

- **Almost nothing needs a fixed address.** The fixed points are the hardware vectors (`$FFFA–$FFFF`, six bytes), the boot stub at `$0801`, and the syscall jump table at `$CF00`, which is the ABI for programs. Everything else is placed by `ld65` on every build, and internal calls are `jsr label`. A routine that grows by a byte moves its neighbours at the next `make`, and the linker reports an overflow if a region fills. There is no repacking by hand.
- **Programs never call the KERNAL.** All KERNAL calls are in `con.s`, `proc.s`, `blk.s` and `cbm.s`. The ROM's `$FFxx` jump table has no external users, so it simply goes away with the ROM.
- **Make each replacement a swap behind a name.** First give the KERNAL entry a kernel-local name (for example `key_get = $FFE4`) at every call site, which costs nothing. Then replace the definition with our routine, with the same register conventions. Each step is a small, testable diff.
- **State coupling is the real work.** The ROM routines use zero page `$90–$FF` and low memory `$0200–$03FF`, and our code reads some of it directly (`ST` at `$90` in `blk.s`, `$C6`, `$0276` and `$91` in the IRQ, `$D1` and `$D3` in `con.s`). Each replacement keeps those locations with their stock meaning for the services we still provide, as described next.
- **Order:** M0-2 keyboard (small; owns `SCNKEY`, `GETIN`, `UDTIM`, `$C6`, `$0276`, `$91`), then M0-3 screen (`CHROUT`, `PLOT`), then M0-4 IEC and channels (riskiest; needs the real 1541), then M0-5. Targeted tests plus smoke after each; full suite after M0-4 and M0-5.
- **Space during the transition.** The new code lives in the existing kernel region. It had 1.9 KB of headroom; the keyboard alone took 747 bytes of it, leaving 1109, against screen and IEC drivers that will each need several hundred more. So the region will overflow during M0-3 or M0-4. The planned relief is `$E000–$E3FF` (1 KB of the shadowed ROM that the spike showed to be dead BASIC) as a second code region loaded after the shadow copy; build it when the first link fails, not before. Run `make size` in every story and quote the numbers.
- **Optional, independent: shrink the syscall table's stubs.** Each of the 31 entries goes through an 8-byte stub (about 248 bytes). An entry of the form `jsr dispatch`, with the dispatcher recovering the syscall number from the return address, removes them and keeps the ABI. Do it only if space demands.

## The Ultimate Command Interface

Read from the [1541 Ultimate documentation source](https://github.com/GideonZ/1541u-documentation) (`uci/*.rst`, `api/api_calls.rst`). Nothing here has been run on hardware yet.

- **Transport.** Registers at `$DF1B–$DF1F`, overlaying the last five REU registers, off by default and enabled in the Ultimate's "Command Interface" menu. Identification register `$DF1D` reads `$C9` (bit 7 clears while an interrupt is pending), which gives a runtime probe. A command is written byte by byte to `$DF1D`, pushed with `PUSH_CMD` in `$DF1C`, then the response (`$DF1E`) and status (`$DF1F`) queues are read. Queues are 896 bytes for commands and responses, 256 for status. Firmware 3.15 added an interrupt on completion.
- **Targets.** `$01` and `$02`: two independent instances of Ultimate DOS. `$03`: network. `$04`: control. `$05`: Software IEC. HTTP client from firmware 3.15.
- **DOS target (`$01`).** Open (read, write, create, overwrite), close, read (up to 65,535 bytes per command, delivered in 512-byte chunks), write, **seek (32-bit)**, file info and stat (size, date, time, attributes), delete, rename, copy, change directory, get path, create directory, open and read directory, **load a file range into the REU and save an REU range to a file** (assumes a 16 MB REU), mount and unmount disk images, get and set time. Each target instance has one open file and one open directory at a time.
- **Software IEC target (`$05`).** A KERNAL-shaped channel interface (open, close, chkin, chkout) onto the emulated drive's host filesystem, with a DMA `LOAD` straight into C64 RAM and `SAVE` from it. Partitions map a number and a name onto a host path. Meant for fast loaders and replacement KERNALs.
- **REST test bench.** The Ultimate 64 exposes `readmem` and `writemem` by DMA, keyboard and joystick injection (`machine:input`), `run_prg` and drive mounting (including uploading a `.d64`). That is enough for a host script to boot an image, type, and read screen RAM, mirroring what `tools/vicetest.py` does for VICE. Input injection answers `501` on products without the Ultimate 64's input hardware.

What this means for the plan:

- The DOS target **is** a filesystem. Bridging it to the kernel's filesystem interface gives long names, big files, real directories and no 1541 assumptions at all, with no on-disk format for us to design or maintain.
- The "NFS without the N" analogy holds, with one consequence: the target keeps one open file per instance while the kernel allows 24. The backend should be stateless in spirit: open, seek, transfer, close per chunk, with at most one cached handle.
- The UCI is synchronous register I/O at CPU speed, so disk access through it should stop stalling the other processes for seconds, unlike the KERNAL serial path.
- Load-into-REU plus the existing REU DMA gives a cheap path for program loading, overlays and text paging.
- **c64fs v2 loses priority.** On a 1541 a 35 KB file limit is fine for a 170 KB disk. Its remaining jobs are the REU RAM disk beyond 512 KB and any future block device, so it shrinks to "make the bitmap and inode widths scale" instead of a full redesign.

## Milestones and stories

Dependencies are noted. Two tracks run in parallel and meet at M5.

### M0: Memory (do this before new device support)

New device code (UCI, the filesystem interface) all lands in the kernel, so the room has to exist first. M0-4 also rewrites call sites in `blk.s` and `cbm.s`, so it goes before S5 and S6, which touch the same code.

- **M0-1. Shadow the KERNAL and own the hardware vectors.** Copy the ROM into RAM at boot, run at `$01=$35`, point `$FFFA–$FFFF` at our own NMI, reset and IRQ entries, and stop jumping into the ROM's `$EA81`. No memory gain yet. The spike above is the proof of concept. *Depends on S1.*
- **M0-2. Own keyboard.** *Done.* `src/kernel/kbd.s` replaces `SCNKEY`, `GETIN` and `UDTIM`. The stock locations keep their stock meaning (key buffer at `$0277` with count `$C6`, repeat flag `$028A`, shift flags `$028D`, `$91`, jiffy clock `$A0–$A2`), so VICE's `keybuf` and anything written against the memory map still work. Internal improvements: keys are taken on press edges from the whole matrix, so a key pressed while another is held is not lost; RUN/STOP and the modifiers never enter the buffer; readers sleep until a key is waiting instead of waking every tick (`CH_KEY`); SHIFT+C= no longer switches the character set. Cost: 747 bytes (457 code, 272 tables, 18 BSS). Tested with real keystrokes (`tests/test_keyboard.py`): typing, shift and control flags, shifted symbols, rollover, key repeat, the RUN/STOP key, and the jiffy clock.
- **M0-3. Own screen driver.** *Done.* `con.s` writes ASCII straight to screen RAM in the lowercase character set and no longer calls `CHROUT` or `PLOT`. Colour is one global setting (written only by `ESC C`), so output and scrolling touch screen RAM alone and per-cell colour is gone. Contract changes: no 80-column logical lines, no ROM insert or quote modes, and DEL erases instead of shifting the rest of the line. Kept: wrapping at column 40, the `ESC =`, `K`, `R`, `r` and `C` sequences, and the stock cursor, reverse and colour locations (`$D1`–`$D3`, `$D6`, `$C7`, `$0286`). Cost: 274 bytes net; kernel headroom 1109 to 835 bytes. Tested by `tests/test_console.py` (wrapping, backspace, clear, scrolling, reverse video, cursor addressing, theme colours) and the existing screen and keyboard tests.
- **M0-4. Own IEC driver and channel handling.** *Done under VICE, with stock ROMs and with JiffyDOS ROMs; not yet run on real drives.* `src/kernel/iec.s` is the whole serial bus: the standard Commodore protocol bit-banged on CIA2, written from the published protocol and timing table (the bus description in MAME's `cbmiec.cpp`), plus a channel layer (a drive number and a secondary address) that replaces the KERNAL's file layer and open-file table. The ROM's `LISTEN`/`TALK`/`SECOND`/`TKSA`/`CIOUT`/`ACPTR`/`UNLSN`/`UNTLK` are no longer called. The root disk mounts from the drive the KERNAL booted from (`$BA`); `mount` and `format` refuse the boot drive. Behavior worth knowing: the last byte of every write goes out with EOI (one byte is held back so it can); a device that has answered attention is waited for without a limit, with interrupts off (a format stops the clock and keyboard, as it did under the ROM); other waits are bounded and set `ST` bits 0 or 1; receiving waits for a busy talker with interrupts on. Standard protocol only. It needs a 1 MHz CPU: turbo must be off around bus use. Headroom is now 33 bytes: the `$E000` second code region or the M0-7 space pass is needed before further kernel work.

  *What the JiffyDOS drive ROM taught us* (the Ultimate's drives all run JiffyDOS 6.01, which the hardware session reported). Stock ROMs hide three assumptions, because the JiffyDOS drive is faster and stricter; all are protocol-correct and now fixed:
  - **Talk turnaround is one write.** After the last attention byte, release ATN, release CLK and pull DATA low in a single store, then watch for the device taking the clock. Any pause hides the device's short clock pulse behind our own hold on CLK, and we then wait for a transition that already happened. Pulling DATA late lets the drive see a "ready" listener and wait for an EOI acknowledgement we never send.
  - **Wait without a limit** for a device that has answered attention but is busy: it takes the clock only after finishing its command (about 100 ms for a block read).
  - **A generous EOI window (about 1 ms)** when receiving: a talker doing real EOI waits for us indefinitely, so being slow to decide costs nothing.
  Two more lessons from earlier: the drive abandons a talk if its channel is not ready, and an interrupt between the listener's "ready" and our first clock edge makes the drive take the byte for the last one.
- **M0-5. Drop the shadow and relayout.** *Done.* The ROM shadow is gone (a spike that filled it with `BRK` showed nothing used it). The kernel's BSS (6,002 bytes: tables, the block cache, the process save areas) now lives at `$E000–$F771` in the old ROM region, the boot stub installs the hardware vectors and switches to `$01=$35` before the kernel starts, and `$8000–$B740` holds only code and read-only data: **6,079 bytes of room for code** below the syscall table (up from 33) and 2,184 for BSS below `$FFFA`. The user pool is unchanged (`$0800–$7FFF`); its upper edge is one constant (`KSTART`, `KRAM`) and is decided last. Zero page stays stock-shaped.
- **M0-6. Stream primitive:** move a run of pages between memory and an open channel in one call. Used first by `exec`, then by overlays. *Depends on M0-4.*
- **M0-7. Space pass.** Once all the replacements exist, a second, deliberately brutal pass over the kernel's size, driven by `make size`. Every byte freed is a byte for user programs or for new kernel and driver work. Rules: measure first, record the before and after of each saving in the commit message, and run the full suite at the end. Candidates already visible in the baseline (2026-10-30, after M0-2):

| Module | Bytes | Where the bytes are | Idea |
|---|---|---|---|
| `proc` | 4321 | 3315 BSS: per-process save areas (12 × 192 = 2304) | save only the stack and zero page a process actually uses; fewer or smaller slots |
| `file` | 2986 | 2664 code | review for shared helpers and repeated sequences |
| `fs` | 2847 | 2506 code | the same |
| `blk` | 2702 | 1628 BSS: six 256-byte cache buffers (1536) | fewer buffers, or put the cache in the REU when there is one |
| `cbm` | 1914 | 1860 code | the CBM DOS layer is rarely used: a candidate to load on demand (an overlay) |
| `kbd` | 747 | 272 tables | the shifted and control tables are largely derivable from the plain one |
| `jtab` | 371 | 248 in per-syscall stubs | `jsr dispatch` entries with the number recovered from the return address |

Programs matter as much as the kernel: `as` is 6.4 KB and `basic` 5.6 KB of the 30 KB pool. *Depends on M0-2, M0-3, M0-4.*

- **M0-8. Fast 1541 path** (from `mist64/fastboot1541`, described at pagetable.com/?p=568). Two uses of one technique, in this order:
  - *Fast boot.* Today the kernel (about 12.5 KB) loads with the ROM's `LOAD`, a few minutes of waiting on a real 1541 at best. fastboot1541 fits a loader in one sector: the C64 half is a PRG loaded over the stack so the KERNAL's `RTS` lands in it, and the drive half rides in the same sector, which the drive has already read into its own RAM, so the C64 only sends `M-E` and nothing is uploaded. The drive then reads a table of sectors itself and streams them at about ten times the standard speed, with the screen on. For us that means the boot file becomes a one-sector stage 1, the kernel is stored as raw sectors listed in a table that `tools/mkimage.py` generates (and can interleave for the fast reader), and the disk stays a valid CBM disk. It runs while the ROM is still mapped, so it does not depend on M0-1 to M0-4. VICE emulates the 1541 drive CPU, so this can be tested in the emulator.
  - *Fast block reads at run time.* The same drive-side reader, kept resident in a drive buffer reserved with a `#` channel so the drive's DOS does not hand the buffer out, answers `M-E` with a track and sector and streams the block back. Reads first; writes are harder (the drive must receive data and write the sector) and can stay on the slow path. The drive code is specific to the 1541 DOS ROM (it calls `$D586`), so every other drive keeps the standard protocol. *Depends on M0-4 (our own IEC driver), and on knowing which ROM revisions are in use.*
  - *Constraints visible in the code.* It runs with interrupts off for the duration of the transfer, uses cycle-counted reads of `$DD00`, so the CPU must be at 1 MHz (turbo off, as for any IEC bit-banging; see "Platform tiers"), waits on the VIC raster to avoid bad lines, and keeps the VIC bank bits intact when writing `$DD00`. On an Ultimate with a UCI file backend none of this is needed; it is for the real 1541 and for emulated ones that run the 1541 ROM.
  - *Licence.* The repository says to do anything with it but to give credit and, ideally, to email the author about its use. We would credit Michael Steil in the source and the README; whether to send the email is yours.

### M1: Safety net

- **S1. CI.** GitHub Actions: build, `make test-host` on every push. VICE system tests are opt-in (they need ROMs; see `tools/setup-vice-roms.sh`). *Unblocks:* every later refactor. *(Started in this commit.)*
- **S2. Image checker.** `mkimage.py fsck`: verify bitmap, inode and directory consistency of a disk image. The system tests run it on the image after a VICE session. *Unblocks:* confidence in any change to `fs.s`.
- **S3. Geometry in one place.** A single definition of block size, superblock location, inode and directory formats, generating the kernel include, the format tool's constants and the Python tool's constants. Today these are separate copies in `fs.s`, `cbm.s`, `format.s` and `mkimage.py`. *Unblocks:* S6.
- **S4. Faster, split test suite.** Independent VICE sessions that can run in parallel; a smoke subset for CI.

### M2: Storage abstraction (Track A)

- **S5. Block driver table** replacing `cmp #1` in `blk.s`: read, write, block count, type and track mapping per device (1541, REU). REU detection and sizing lifted past 8 MB and the 2048-block cap. *Depends on S1.*
- **S6. Filesystem interface**, replacing the scattered `dev_type` branches in `file.s`, `fs.s`, `exec.s`, `cbm.s`. Backends: c64fs, CBM DOS. *Depends on S2, S3.*
- **S7. c64fs scaling** (v1 removed): multi-block bitmap, wider inode numbers, geometry read from the superblock instead of fixed at block 376, a file layout that goes past 35 KB. Image tools updated to match. Nice-to-have; see "Block devices and the filesystem". Keep the scope small. *Depends on S2, S3, S6.*
- **S8. REU-resident `/bin`:** copy commands to the REU RAM disk at boot, so command loads stop costing seconds. `exec.s` appears to run programs from any c64fs device already; confirm. *Depends on S5. Unblocks:* a tolerable dev loop on the Ultimate without further storage work.

### M3: Ultimate storage (Track A, needs hardware)

- **S9. Hardware test bench:** *Written, not yet run on hardware.* `tools/ultimate.py` (REST client), `tools/fake_ultimate.py` and `tools/test_ultimate.py` (24 tests against a fake server, part of `make test-host`), and `tools/ultimatetest.py`, a backend with the same interface as `vicetest.py` (`screen()`, `type()`, `keybuf()`, `wait_for()`, `run()`, real key events). The `Boot` class, the keyboard tests and the console tests choose it with `BREADBIN_TARGET=ultimate`. What is left is verification on the real machine: the checklist in `docs/wip.md` and the questions in `docs/hardware-notes.md`.
- **S10. UCI probe and driver core** (`uci.s`): detect `$DF1D == $C9`, command push, response and status reads, error mapping. A `uci` command to identify the device and firmware, as the first smoke test on hardware. *Depends on S9 for testing. Mind the kernel space budget.*
- **S11. UCI-DOS filesystem backend:** open, read, write, seek, stat, readdir, mkdir, rename, delete behind the S6 interface, mountable like any drive (`mount uci /host`). Stateless per chunk, one cached handle. Long names and big files come for free. Run programs from it. *Depends on S6, S10. This is the story that makes the Ultimate pay off.*
- **S11b. Load into REU** (`LOAD_REU`) for program loading, overlays and text paging. *Depends on S5, S11.*
- **S11c. Software IEC mount** through the existing CBM DOS backend (`cbm.s`), as a fallback needing no UCI: add subdirectory support and run-from. Lower priority than S11, since it keeps the serial-bus speed.

### M4: Toolchain v0 (Track B, independent of Track A)

- **S12. `brk`-style syscall:** let a process grow by whole pages (the allocator already exists in `mem.s`). *Unblocks:* symbol tables that scale, a bigger `as`, the compiler.
- **S13. Lift `as` limits:** output buffer and symbol table on the grown heap, `.include`, possibly local labels. *Depends on S12.*
- **S14. Compiler v0.** A small C-like language, 16-bit `int` and `char`, pointers and arrays, functions, `if`/`while`/`for`/`return`, string literals, no structs or floats, a few bytes of zero page for a software stack pointer and temporaries, emitting assembly for `as`. Single pass, recursive descent, streaming the source. A first milestone is "hello" compiled and run on-device with the existing file system. *Depends on S12, S13.*

### M5: Dev loop and self-hosting (both tracks)

- **S15. Edit, compile, run loop** under about 15 seconds on an Ultimate: S8 or S10 plus the toolchain.
- **S16. Multi-file programs:** `#include` first, linking later.
- **S17. Self-host decision.** Rewrite the compiler in its own language, or stay in assembly. Decide once S14 shows what the language needs.

## Critical path

The shortest route to *a compiler exists* is **S12, S13, S14**, and it does not need any filesystem work. The storage stories decide how pleasant and scalable it is. The Ultimate path (S6, then S10 and S11) makes the dev loop fast and the file limits disappear, and the REU path (S5, S8) does the same for a stock machine with an REU. Memory comes before new devices: S1, then M0-1 to M0-5, with S9 as soon as hardware is reachable. The compiler track (S12 to S14) is independent and also benefits from M0-5's extra zero page and RAM, so it can run alongside. After M0, S2, S3, S5 and S6 prepare the storage interface, S10 and S11 add the Ultimate backend, and S11 lands before the dev-loop milestone. S5 and S7 are nice-to-have.

## Open questions

- **Nothing has run on hardware.** The UCI facts above come from the documentation, not from a test. The first hardware session should confirm: the `$DF1D` probe, the command-interface menu setting, DOS-target read and write throughput, and what happens to the existing 1541 path with the cartridge-port registers enabled.
- **Which products and firmware.** The documentation covers the Ultimate-II+, Ultimate 64 and C64 Ultimate; input injection is Ultimate 64 only, the interrupt option needs firmware 3.15, and `LOAD_REU` assumes a 16 MB REU. Which machine and firmware you have decides what we can rely on.
- **Kernel space.** S5, S6, S10 and S11 all add kernel code with 1.9 KB free. Plan for moving rarely used code out (overlay, or into REU) before S11, or accept deleting v1 code and the CBM DOS write path to pay for it.
- **Emulation gap.** VICE does not emulate UCI, so S10 and S11 have no automated test in CI. Options: a small fake UCI in the test harness (VICE cannot do it, so it would have to be a unit-level model), or hardware-only tests via S9.
- **Language choice for S14.** A small C subset is the current assumption. A Forth-style language or compiling `basic` are cheaper alternatives if memory proves too tight.
