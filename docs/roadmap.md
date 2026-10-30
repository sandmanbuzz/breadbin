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

### M1: Safety net

- **S1. CI.** GitHub Actions: build, `make test-host` on every push. VICE system tests are opt-in (they need ROMs; see `tools/setup-vice-roms.sh`). *Unblocks:* every later refactor. *(Started in this commit.)*
- **S2. Image checker.** `mkimage.py fsck`: verify bitmap, inode and directory consistency of a disk image. The system tests run it on the image after a VICE session. *Unblocks:* confidence in any change to `fs.s`.
- **S3. Geometry in one place.** A single definition of block size, superblock location, inode and directory formats, generating the kernel include, the format tool's constants and the Python tool's constants. Today these are separate copies in `fs.s`, `cbm.s`, `format.s` and `mkimage.py`. *Unblocks:* S6.
- **S4. Faster, split test suite.** Independent VICE sessions that can run in parallel; a smoke subset for CI.

### M2: Storage abstraction (Track A)

- **S5. Block driver table** replacing `cmp #1` in `blk.s`: read, write, block count, type per device. REU detection and sizing lifted past 8 MB and the 2048-block cap. *Depends on S1.*
- **S6. Filesystem interface**, replacing the scattered `dev_type` branches in `file.s`, `fs.s`, `exec.s`, `cbm.s`. Backends: c64fs, CBM DOS. *Depends on S2, S3.*
- **S7. c64fs scaling** (v1 removed): multi-block bitmap, wider inode numbers, geometry read from the superblock instead of fixed at block 376, a file layout that goes past 35 KB. Image tools updated to match. Scope is set by the REU RAM disk and future block devices, so keep it small. *Depends on S2, S3, S6.*
- **S8. REU-resident `/bin`:** copy commands to the REU RAM disk at boot, so command loads stop costing seconds. `exec.s` appears to run programs from any c64fs device already; confirm. *Depends on S5. Unblocks:* a tolerable dev loop on the Ultimate without further storage work.

### M3: Ultimate storage (Track A, needs hardware)

- **S9. Hardware test bench:** `tools/ultimatetest.py` with the same interface as `vicetest.py` (`screen()`, `type()`, `wait_for()`, `run()`), built on the REST API: mount or upload the image, `run_prg`, read screen RAM with `readmem`, type with `machine:input`. The existing system tests then run against real hardware unchanged. *Needs an Ultimate 64 on the network. Can start immediately and runs in parallel with everything else.*
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

The shortest route to *a compiler exists* is **S12, S13, S14**, and it does not need any filesystem work. The storage stories decide how pleasant and scalable it is. The Ultimate path (S6, then S10 and S11) makes the dev loop fast and the file limits disappear, and the REU path (S5, S8) does the same for a stock machine with an REU. A sensible order is S1 first, then S12 to S14 in parallel with S2, S3, S5 and S6, and S9 as soon as hardware is reachable. S11 lands before the dev-loop milestone; S7 is the least urgent.

## Open questions

- **Nothing has run on hardware.** The UCI facts above come from the documentation, not from a test. The first hardware session should confirm: the `$DF1D` probe, the command-interface menu setting, DOS-target read and write throughput, and what happens to the existing 1541 path with the cartridge-port registers enabled.
- **Which products and firmware.** The documentation covers the Ultimate-II+, Ultimate 64 and C64 Ultimate; input injection is Ultimate 64 only, the interrupt option needs firmware 3.15, and `LOAD_REU` assumes a 16 MB REU. Which machine and firmware you have decides what we can rely on.
- **Kernel space.** S5, S6, S10 and S11 all add kernel code with 1.9 KB free. Plan for moving rarely used code out (overlay, or into REU) before S11, or accept deleting v1 code and the CBM DOS write path to pay for it.
- **Emulation gap.** VICE does not emulate UCI, so S10 and S11 have no automated test in CI. Options: a small fake UCI in the test harness (VICE cannot do it, so it would have to be a unit-level model), or hardware-only tests via S9.
- **Language choice for S14.** A small C subset is the current assumption. A Forth-style language or compiling `basic` are cheaper alternatives if memory proves too tight.
