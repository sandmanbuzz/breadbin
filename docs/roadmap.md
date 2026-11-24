# Roadmap

Where this fork is heading. Realigned 2026-11-18 after the owner's direction on languages; the plan of 2026-10-30 and the product push of 2026-11-04 are in git history. Sections this rewrite removed, which other notes still cite (Memory budget, Memory strategy, KERNAL takeover, the M0 story notes including "What the JiffyDOS drive ROM taught us", Open questions, and line numbers into the old file): read them with `git show 8fc1150:docs/roadmap.md`. `docs/wip.md` says who is doing what right now; `docs/size-ledger.tsv` has the size figures per landed commit, so this file quotes as few numbers as it can.

## Direction

- **Goal:** make Breadbin a place where real software gets written *on* the machine, and pleasant to use while doing it. Platform work serves that; platform for its own sake is not the point.
- **Resources, in order:** memory first (every byte of the user pool matters), I/O second (the bus is slow and stalls). Kernel bytes are the scarcest of all.
- **Targets:** one disk boots everywhere; everything beyond a stock C64 and 1541 is found by probing at run time ("Platform tiers").
- **Contract drift:** internal behaviour may improve if the call looks the same and does not violate least surprise. The user-facing contract matters more than the vintage one.
- **Never buy the next milestone's problems.**

## Where we are (2026-11-24)

Since 2026-11-18, on `main`: the VM runs as a shared library (L1 and L1s: `/lib/pvm`, two processes share one copy, `SharedVM`); the BASIC compiler's first slices (L3a, L3b, `docs/design/basic.md`) and compile to file; `SYS_LSEEK` (the `$CF00` page is now full); an opt-in 80-column console module (`con80`); the `fast.km` write path; `cut`, `uniq` and `calc`.

Built and on `main`:

- **The KERNAL is gone** (M0): our own interrupt entry, keyboard, screen, serial bus and channels, with the JiffyDOS host protocol (clean room) and the standard one. The ROM is not used at run time. Runs on the real Ultimate and the physical 1541.
- **Memory:** the user pool is **155 pages (39,680 bytes)**, more than a stock C64's 38,911 BASIC bytes; it was 120 pages at the fork. Boot-only code is released to the pool, cold code lives above the BSS, the per-process save areas live under the I/O area, and the syscall entry fills the `$CF00` page (which is now full).
- **Storage:** c64fs format 2; the REU block cache for the boot drive (`cache`); `eject` and `reattach` (single-drive swap served from the cache); kernel modules (`mod`) carrying the CBM DOS filesystem (`cbm`), the 1581 (`d81`), the stock-1541 fast reader (`fast`), `eject`, and **UCI v1** (`mount uci /u`: the Ultimate's file API, long names, big files).
- **Processes:** `exec` (`login` execs into `sh`); a BRK in user code kills the process, not the machine; up to eight processes.
- **Shell:** `$?`, `&&`, `||`, `&`, command history, TAB completion.
- **Tools:** `edit`, `as` (on the machine), `basic` (a TinyBASIC-grade toy), `tools/cc.py` (a host-side C subset emitting `as` source), `tools/webdemo.py` (bundle built locally; nothing hosted).
- **Safety net:** containerised VICE, a sharded suite, host simulators (py65) for the kernel paths VICE cannot reach, the Ultimate test backend, `make size` and the size ledger.

What still hurts:

- **Programming on the machine is assembly or a toy.** There is no compiler on the C64 and `basic` is not a BASIC a C64 user recognises.
- **Every program carries its own copy of the library**, about half of `/bin` by bytes (`docs/design/research/next/SYNTHESIS.md`), on disk and in memory.
- **The `$CF00` syscall page is full** (`SYS_LSEEK` took the last slot): a new syscall needs entries re-shaped first (one multiplexed control call, `docs/design/next/cp3-spec.md`).
- **The physical 1541 is slow** even with the JiffyDOS protocol (on by default, `make JIFFY=0` turns it off; the standard protocol is about 0.55 s a block) and the drive-side fast reader does not yet run on it. Its old root-mount stall is closed: it was the test harness halting the CPU with DMA mid-transfer (`docs/design/io-attack-log.md`, closing entry).
- **Daily use is still rough at the edges**: no `2>`, no job control, slow first loads on a stock machine.

## Epics

In priority order. Each epic has stories; each story is done when its acceptance passes and a hater review finds nothing it cannot rebut. Kernel bytes are measured with `make size` in every story.

### E1. Languages: a p-code machine, BASIC and a small C

**Why.** One compact virtual machine serves three needs at once. A stack machine gives the compiler recursion for free (`cc.py` has no stack frames today); a compiled BASIC is both faster and easier to grow than an interpreter that re-reads source; and p-code is typically two to three times denser than 6502 code (SWEET16, UCSD p-code, PLASMA), which is memory we keep. The VM is a user program and needs no kernel bytes. The model is SWEET16 and PLASMA scaled to our use, not a large compiler framework scaled down.

**Decided (owner, 2026-11-18):**

- Front ends: **BASIC** and **the C subset**. FORTH is not planned (appealing, little demand).
- **BASIC is compiled**, even when it is invoked as an interpreter with an immediate mode. The dialect is **congruent with Microsoft BASIC**: BASIC 2.0 is the floor, old listings should mostly work, but source compatibility is not promised. BBC BASIC is the model for what to add beyond that (named procedures, structured loops, long variable names); BASIC 7.0, late CP/M and Model 100 BASICs are stretch, not MVP.
- **Numbers:** BASIC needs decimals. **Fixed point** for the MVP; **floating point** is allowed for in the instruction set (reserved opcodes) but not committed.
- `basic.s` is replaced, not grown.

**Sources to mine.** MIT code may be used literally or adapted (licence policy in `CLAUDE.md`): keep its copyright notice, link the source, and record source, author, licence and evidence in the file header and in `docs/design/fast-io.md`.

- **Microsoft BASIC for 6502**, version 1.1 (1978), released by Microsoft under the **MIT** licence (`github.com/microsoft/BASIC-M6502`); it includes the PET configuration and the floating-point package. Take what beats our own code on size; it is unlikely to meet our compactness bar unchanged. **Only that source**: Commodore's BASIC ROM is proprietary and is never copied or disassembled for this.
- **PLASMA** (David Schmenk, **MIT**, `github.com/dschmenk/PLASMA`): a 6502 bytecode VM and language with a module system; the closest prior art for the VM, the calling convention and relocatable modules. Base PLASMA may be adopted if it is the solution L0 selects.
- **UCSD p-System** (the p-machine of UCSD Pascal and Apple Pascal): proven, documented in great depth, and with a long 6502 history (Apple II, and the C64's own ports). A **design reference only**: the released source (versions I.4 and I.5, 2006) is for non-commercial use, so no UCSD code or derived code comes in; we learn from the published descriptions of the p-machine, as for any clean room. It may be ruled out early in L0.
- **Lawless Legends** (`github.com/badvision/lawless-legends`, **Apache-2.0**): a large game built on PLASMA with its own extensions and module-based memory management. Apache-2.0 is the outer limit of what we take: ideas only, code only if backed into a corner (owner's call), and we do not ask for a re-licence.

**Stories:**

- **L0. VM spec.** Instruction set (stack machine, 16-bit cells; 32-bit fixed point; floating point opcodes reserved), calling convention and frames, how p-code relocates and links (fits CX), how a program finds the VM, the zero page it uses (within the program's own area; see "Zero page policy"), and how it calls syscalls. A host assembler and a host simulator for the VM in `tools/`. The lesson of earlier attempts at a compiled BASIC, which produced nothing: prove the whole path with one tiny program end to end before widening anything. *Acceptance:* a review of the spec, and the host simulator running hand-assembled p-code for a loop, a call with recursion and a syscall.
- **L1. The VM on the machine.** The interpreter in 6502 assembly, measured: bytes of the interpreter, and size and speed of the same programs as `cc.py`'s native output. *Acceptance:* the L0 programs run under VICE with identical output to the host simulator; the ratio table is in the design note. **Gate:** if the density or speed is far from the claim, stop and rethink before L2.
- **L1s. One VM for every p-code process** (owner, 2026-11-18: the first binfmt variant, a foundation for shared libraries and for the kernel handling other binfmts). The VM becomes a library image, `/lib/pvm`, loaded once at the top of the pool and reference-counted by the processes that import it; a p-code program carries only its bytecode and a header naming the library. The CX version byte is the format: 1 a native program, 2 a program importing one library (its library relocations add the library's page, as the CX ones add the program's), 3 a library. *Acceptance:* two p-code processes in a pipeline share one copy (`free` before, during and after); a missing or mismatched library gives `ENOEXEC`; the smallest p-code program's size on disk, measured.
- **L2. C on the VM.** `cc.py` emits p-code, with real recursion and stack frames; its existing tests pass under the VM. *Done 2026-11-19:* `cc.py --pcode`; measurements and limits in `docs/design/pvm.md` §3 and §6.
- **L3. BASIC MVP.** A compiler from the MS-congruent dialect to p-code: numbered lines, `PRINT`, `INPUT`, `LET`, `IF`/`THEN`, `GOTO`, `GOSUB`, `FOR`/`NEXT`, `DIM` arrays, strings with `LEFT$`, `MID$`, `RIGHT$`, `LEN`, `CHR$`, `ASC`, `STR$`, `VAL`, fixed-point decimals, `LOAD`, `SAVE`, `LIST`, `RUN`, and an immediate mode. *Acceptance:* a set of period-style listings (written for this, not copied) that run unchanged or with stated edits; a user manual, a reference manual and a developer guide (SDK) in `docs/manual/`, their examples run by tests (owner, 2026-11-19); and a run on the real Ultimate. Slices in `docs/design/basic.md` §5.
- **L4. BASIC beyond 2.0.** BBC-style procedures and loops, long names, file I/O through Breadbin's files and pipes.
- **L5. Self-hosting.** The C compiler, written in its own subset and compiled to p-code, runs on the machine (this replaces S17's "self-host decision"). Floating point, if wanted, lands here or later.

### E2. Shared library and CX v2

**Why.** Programs carry duplicated library code; a resident shared library gives that memory back to every running program and is halfway to what a C runtime start-up (`crt0`) needs. The VM (E1) is its first big client. Builds on the research in `docs/design/research/next/` (SYNTHESIS, REV2) and `docs/design/next/cx2-abi2.md`.

- **SL1.** Error strings out of the binaries (read from a file on error).
- **SL2.** CX v2: one-byte relocation deltas; old binaries get `ENOEXEC`. (The version bytes 2 and 3 went to L1s's program-importing-a-library and library formats: the delta encoding takes another.)
- **SL3.** A resident shared library loaded once, linked by programs; then `crt0` for the C subset. The loader half exists since L1s (`/lib/pvm`): one imported library per program, two resident at once.

### E3. UCI v2 (ship milestone for the Recommended tier)

UCI v1 was the unlock: without it the filesystem limits make anything beyond toy projects impossible. v2 makes it the shipping storage for the Ultimate. The seam and what goes are in `docs/design/next/uci-v1.md`, section 6: an operations table instead of branches in the core (the core still has about twenty `dev_type` references), full-length names, sizes past 24 bits, the fast byte loop, and loading a file straight into the REU for program loading and overlays. Needs the hardware lock; suits a hardware-lane session.

### E4. Quality of life, differentiators, upstream parity

An epic of its own, not a backlog: what a user meets in the first ten minutes decides whether the rest is ever seen. Candidates, to be ranked when the epic starts (`docs/design/upstream-survey.md` has the upstream side):

- `2>` and `2>&1`; job control (Ctrl-Z, `fg`, `bg`); line-editor polish.
- The web demo hosted (hosting is an owner call), which needs the root filesystem served from a preloaded REU, and doubles as a benchmark. The emulator (EmulatorJS with the libretro VICE core) is GPL: its parts are never committed here, and any hosted copy ships LICENSES and a source offer.
- An Ultimate showcase over the UCI network target (fetch a file, a telnet client).
- A write-back cache with `sync`; the jiffy-clock fix from upstream.
- A tagged 0.x and a short "why this fork" page (`docs/why-this-fork.md`); upstream PRs in useful chunks.

### E5. Kernel room and the I/O path

Enablers, done when an epic needs them, not for their own sake.

- **The control call** (CP3): one multiplexed syscall so the full `$CF00` page can take new operations.
- **A space pass, research first** (owner intent, 2026-11-16): demoscene-grade, measured before and after, the pool staying at 155 pages; `docs/design/size-spike.md` has the findings so far.
- **`brk`** (S12, `docs/design/s12-brk.md`): programs grow at run time. Wanted by `as` and by the compilers.
- **Stock-1541 speed:** make `fast` (built and verified under VICE) work on the bench's physical 1541, which refuses it at the buffer probe (`docs/design/fast-io.md` 17.2-17.3, where the fallbacks on the emulated drive are also open), then the fast reader at boot (M0-8), and the stream primitive (M0-6) for `exec` and overlays.
- **The block driver table** (S5) and REU sizing past 8 MB, when the large-REU ideas (`docs/design/large-reu.md`) are scheduled.

## Platform tiers

Decided 2026-10-30. One disk boots everywhere, and features are chosen by probing at boot, not by build variant.

| Tier | Machine | What we promise |
|---|---|---|
| **Classic** | Stock C64, a 1541 or compatible, no REU | Boots to a shell. Pipes, jobs, the editor, `basic` and `as` work. Maintained and tested (VICE CI), but gets no new features and no speed promises. |
| **Expanded** | Classic plus an REU | Everything in Classic, plus the REU RAM disk, the block cache and, when built, overlays and swapping. |
| **Recommended** | Ultimate 64, C64 Ultimate, or Ultimate-II+ cartridge, UCI enabled | Everything: Ultimate file storage, a large REU, turbo, the fast paths. New work targets this tier first and degrades downward. |

Rules:

- **The core never requires the REU or an Ultimate.** The kernel, shell and base commands run on Classic. Features beyond the core are capability-gated; one that cannot degrade says what it needs and refuses.
- **Each capability has a probe and a fallback.** Turbo: read `$D031`, and if it is not `$FF`, set the CPU speed index. UCI: read `$DF1D` for `$C9`. REU: detect the size.
- **CI covers Classic and Expanded with VICE** (including `-reu`), and Recommended through the hardware bench.
- **Real drives.** A physical 1541 validates the IEC driver alongside the Ultimate's emulated drives.

**Turbo.** On the Ultimate 64, `$D031` exists only when the Turbo Mode setting in the Ultimate's menu is "U64 Turbo Registers" or "Turbo Enable Bit"; otherwise it reads `$FF`, as does a stock C64's unused VIC register space, so the probe and the write are harmless everywhere. Bits 0 to 3 are the speed index; index 15 is the maximum (48 MHz on the Ultimate 64, 64 MHz on the Elite-II). The CIAs, VIC and the serial bus stay at 1 MHz, so every cycle-counted bus loop runs with turbo off. Bad-line behaviour (`$D031` bit 7) keeps its default. `turbo` sets it at run time.

## Block devices and the filesystem

**Decision (2026-10-30): 1581 and other non-1541 devices are nice-to-have, not milestone deliverables.** Do not design around them; leave a clean campsite: the IEC driver takes the drive number as a parameter, per-device geometry stays in the one table in `blk.s`, and there are no abstractions for devices we do not support. (`d81` exists because format 2 made it cheap, not because it was scheduled.)

Format 2 (upstream's, `docs/filesystem.md`) has the multi-block bitmap, so a 1581 fits. Still open for a 16 MB REU RAM disk (capped at 2048 blocks by the drive cache's banks) or an IEC hard drive: wider inode numbers and geometry read from the superblock. The file-level paths (CBM DOS, UCI DOS) do not have this problem. **c64fs v1 compatibility is dropped.**

## Disk speed

Measured on the real C64 Ultimate with the standard protocol: a talker sends a byte in about 1.8 ms (the drive sets that pace), a block read is about 0.55 s, and booting reads about 70 blocks. What we have and what is left:

| Path | Helps | State |
|---|---|---|
| **REU block cache**, keyed by a build id | Anything with an REU: repeat boots and repeated loads | Built (`cache`, `make CACHE=0\|1\|2`). Never call it a stall fix: it hides bus reads, it does not repair them. |
| **UCI DOS** | The Recommended tier: no serial bus at all | v1 built; v2 is E3. |
| **JiffyDOS host protocol** | Drives with JiffyDOS, including the hardware bench | Built in `iec.s`, clean room (`docs/design/fast-io.md`). |
| **Drive-side fast reader** (`mist64/fastboot1541`, credit Michael Steil) | Stock 1541s | Run-time reads built (`fast`) and verified under VICE; refused by the bench's physical 1541; boot-time loader open (E5). |

**Requirements for the REU cache** (hardware session, 2026-10-31): it must never hide bus problems or lock out Classic. It is optional and absent without an REU; it has an off switch that needs no rebuild (`cache off|on|stat|flush`) and build-time defaults; bus errors are counted even when most reads hit; it is write-through and keyed by the build id, so a stale REU image after a rebuild is discarded.

## Zero page policy

Decided 2026-10-30: **keep zero page stock-shaped.** The layout is part of what developers expect from the hardware.

- **Familiar means the stock address keeps its stock meaning.** Where a replacement still provides the service, it keeps the well-known locations: `ST` (`$90`), the stop-key flag (`$91`), the jiffy clock (`$A0–$A2`), the keyboard buffer count (`$C6`) and buffer (`$0277`), and the cursor position and line pointer (`$D1–$D3`, `$D6`).
- **We may poach locations whose service we removed** (tape and RS-232 variables), once nothing reads them, each recorded with its stock meaning and our use. Never one with a live meaning.
- **Zero page is not kernel room** (owner, 2026-11-16): no zero page for kernel space or convenience, only when backed into a corner.
- **The free zero page for programs is not KERNAL-owned.** `$60–$8F` (48 bytes, BASIC's old area) is unused by the kernel: the first place to look for more program zero page (the VM included), with no stock address changing meaning.
- **`$FB–$FE` stays free** for the boot stub and programs, as in stock. Programs see a per-process area (`$02–$3F`, saved and restored per process, argv at `$20`); the VM (E1) lives within a program's own area.

**Stock behaviour retired so far:** SHIFT+C= no longer switches the character set; the key-decode state at `$F5–$F6` and `$028E–$0290` is not maintained; RUN/STOP, SHIFT, CTRL and C= never enter the key buffer, and SHIFT+RUN/STOP does not expand to a load command; the colour pointer at `$F3–$F4` and the insert, quote and line-link state (`$D4`, `$D8`, `$D9–$F1`) are gone (colour is global, no 80-column logical lines). The stock meanings above come from the standard C64 memory map and have not been checked against a ROM image.

## The Ultimate Command Interface

From the [1541 Ultimate documentation source](https://github.com/GideonZ/1541u-documentation) (`uci/*.rst`, `api/api_calls.rst`) and our own measurements (`docs/hardware-notes.md`, `docs/design/next/uci-v1.md`).

- **Transport.** Registers at `$DF1B–$DF1F`, over the last five REU registers, enabled in the Ultimate's "Command Interface" menu. `$DF1D` reads `$C9`, the probe. A command is written byte by byte to `$DF1D` and pushed with `PUSH_CMD` in `$DF1C`; the response (`$DF1E`) and status (`$DF1F`) queues are read back.
- **Targets.** `$01` and `$02`: two independent Ultimate DOS instances. `$03`: network. `$04`: control. `$05`: Software IEC.
- **DOS target.** Open, close, read, write, 32-bit seek, stat, delete, rename, copy, change directory, create directory, read directory, load a file range into the REU and save an REU range to a file, mount disk images, the clock. One open file and one open directory per instance.
- **REST bench.** The Ultimate exposes `readmem` and `writemem` by DMA, `run_prg` and drive mounting; this C64 Ultimate has no key injection, so the test backend types through the key buffer by DMA (`tools/ultimatetest.py`).

## Story history

The stories of the 2026-10-30 plan, and where they went:

| Story | State |
|---|---|
| M0-1 to M0-5 (shadow, keyboard, screen, IEC, relayout) | Done |
| M0-6 stream primitive | Open, E5 |
| M0-7 space pass | Footprint pass and size research done; a research-first pass is E5 |
| M0-8 fast 1541 | Run-time reader built (`fast`); boot-time open, E5 |
| S1 CI, S4 split suite | Done (container, shards) |
| S2 image checker, S3 geometry in one place | Not done; geometry has host simulators (`tools/test_geometry_sim.py`) |
| S5 block driver table | Open, E5 |
| S6 filesystem interface | Partly: CBM and UCI are modules; the core still branches on `dev_type`. E3 finishes it |
| S7 c64fs scaling | Format 2 landed; the rest is nice-to-have |
| S8 REU-resident `/bin` | Superseded by the REU block cache |
| S9 hardware bench, S10 UCI core, S11 UCI DOS backend | Done (UCI v1) |
| S11b load into REU | E3 |
| S11c Software IEC mount | Dropped unless wanted: it keeps serial-bus speed |
| S12 `brk` | Designed, not built; E5 |
| S13 `as` limits | Symbol table raised; the rest waits for `brk` |
| S14 compiler v0 | Host-side `cc.py`, slice 3; becomes L2 |
| S15 edit-compile-run, S16 multi-file, S17 self-host | Folded into E1 (L3 to L5) |
| P1 QoL bundle | Done (history, TAB, `$?`, `&&`, `\|\|`) |
| P2 web demo | Bundle tool built; hosting and the REU root open, E4 |
| P3 Ultimate showcase, P4 soft launch | E4 |
