# Breadbox

A small Unix-like operating system for the Commodore 64 — the "breadbin".

Breadbox is a fork of [Breadbin](https://github.com/kpatr1981/breadbin) by Konstantinos Patronas. Based on breadbin by kpatronas@gmail.com. The boot banner reads "breadbox 0.1 / based on breadbin by kpatronas@gmail.com".

- The name is temporary and may be renamed. The version number restarts at 0.1 on purpose and makes no claim of tracking upstream's numbering.
- How and why this fork differs from upstream: [docs/why-this-fork.md](docs/why-this-fork.md).
- File and command names keep the old name for now: `build/breadbin.d64`, the `BREADBIN` boot file, `include/breadbin.inc`.
- **[User Guide](docs/user-guide.md)** — building, platform options, everyday use, filesystems, commands, and design notes.

It is a real kernel, not a shell that prints canned output:

- **Preemptive multitasking.** A timer interrupt drives a round-robin scheduler, so `cmd &` keeps running in the background while you type. Up to 8 processes (`MAXPROC` in `src/kernel/k.inc`).
- **Real programs.** `ls`, `cat`, `grep` and the rest are separate relocatable executables in `/bin`. The shell asks the kernel to `spawn` them and `wait`s for them.
- **Pipes and redirection.** `cat readme | grep unix | wc`, plus `>`, `>>` and `<`. A pipe is a kernel buffer: readers block when it is empty, writers block when it is full, and writing to a closed pipe raises `SIGPIPE`.
- **A Unix filesystem on the 1541.** c64fs has inodes, real directories (`mkdir`, `cd`, `..`), files up to 35 KB, and `/dev/console` and `/dev/null` device nodes. The on-disk format is c64fs format 2 (upstream's: `docs/filesystem.md`); a 1581 volume mounts with the `d81` module.
- **Signals.** RUN/STOP sends `SIGINT` to the foreground job. `kill` sends any signal.
- **REU support.** If a RAM Expansion Unit is present, it is detected at boot, formatted, and mounted at `/tmp` as a fast RAM disk.
- **REU block cache.** With enough REU banks free, the boot drive's blocks are cached in the REU (write-through, discarded when the disk or the build changes). The `cache` command shows its state (`cache stat|on|off|flush`); `make CACHE=0|1|2` sets the default.
- **No KERNAL ROM.** This fork has its own interrupt entry, keyboard, screen driver and serial bus (IEC) driver; no Commodore ROM is used at run time.
- **Kernel modules.** `mod` loads and unloads kernel modules (root only). The CBM DOS filesystem (`/lib/km/cbm`) UCI v1 (`/lib/km/uci`), the 1581 volume driver (`/lib/km/d81`) and the block-transfer module for a stock 1541 (`/lib/km/fast`) are modules (`mod ls` lists the loaded ones); `mount uci /u` mounts an Ultimate's file storage through its Command Interface.
- **`exec`.** `exec PATH` replaces the current process with another program (same pid and descriptors); `login` execs into the shell.
- **More drives.** `mount 9 /mnt` attaches drive 9, 10 or 11. A Breadbin disk shows up with its directories. A normal C64 disk shows up as one flat directory that you can read, write (`cp`), `rm` and `mv`; the writes go through the drive's own DOS, so other C64 software can read the results.
- **Users and screen.** There's a `login` with passwords (`passwd`, `whoami`), a full-screen editor (`edit`), colour `theme`s, shell wildcards (`*.bas`) and `jobs`.
- **JiffyDOS.** The serial driver speaks the JiffyDOS byte protocol with a JiffyDOS drive (it probes at the start of each session, and stays on the standard protocol with any other drive, or with a sprite on); `make JIFFY=0` builds without it. Details and caveats: `docs/design/fast-io.md`.
- **Stock hardware.** It runs on a stock C64 with a 1541, and the same disk boots with or without an REU or an Ultimate (see Platform tiers).
- **BASIC and an assembler.** Both run *on* the C64: `basic` is an integer BASIC, and `as` is a 6502 assembler that produces new Breadbin commands (a trailing `.res` is the program's BSS, so big buffers cost no disk space). A small C-subset compiler, `tools/cc.py`, runs on the host and emits `as` source that the C64 assembles and runs; it is a host-side reference for now.

## Building

### What you need

| Tool | Used for | Tested with |
|------|----------|-------------|
| [cc65](https://cc65.github.io/) (`ca65`, `ld65`, `ar65`) | assembling and linking the kernel and programs | 2.19 |
| Python 3 (standard library only) | the disk image builder and relocation tool | 3.15 (3.8 or newer should work) |
| GNU make | the build | 3.81 |
| [VICE](https://vice-emu.sourceforge.io/) (`x64sc`, `c1541`) | running it and the automated tests | 3.9 (the CI container), 3.10 earlier |

VICE is only needed to run Breadbin and its tests. Building the disk image needs just cc65, Python and make.

Install them:

```sh
# macOS (Homebrew)
brew install cc65 vice python3

# Debian / Ubuntu
sudo apt install cc65 vice python3 make
#   (Debian's VICE package ships without the C64 ROMs; see the VICE docs
#    for where to put them)

# Windows: use WSL with the Debian/Ubuntu commands above, or install the
# cc65 and VICE Windows builds and run make from MSYS2.
```

### Build

```sh
git clone https://github.com/sandmanbuzz/breadbin.git
cd breadbin
make
```

This assembles the kernel and every program in `src/bin/`, and packs them with the files from `rootfs/` into one disk image:

| Output | What it is |
|--------|------------|
| `build/breadbin.d64` | the bootable disk: put this in drive 8 |
| `build/breadbin.prg` | the kernel alone (the disk's boot file) |
| `build/root/bin/*` | the programs, as relocatable CX executables |

`make clean` removes `build/`. To add a program, drop a new `src/bin/NAME.s` in and run `make`: it is built automatically and lands in `/bin`.

### Run

```sh
make run        # boots build/breadbin.d64 in VICE
make run-reu    # same, with a 512 KB REU (/tmp becomes a RAM disk)
x64sc -drive9type 1541 -9 other.d64 -autostart build/breadbin.d64   # with a drive 9
```

Or attach `build/breadbin.d64` to drive 8 yourself and type `LOAD"*",8,1` and then `RUN`.

**Real hardware.** Breadbox runs in VICE and on a C64 Ultimate, which is the recommended machine (`docs/hardware-notes.md`). It needs a drive that understands the 1541's sector commands (`U1`, `U2`, `B-P`): a real 1541 or 1571, or a 1541 emulation such as the Ultimate 64's. To make a real floppy, write the `.d64` with a tool such as OpenCBM's `d64copy`.

Physical 1541 (the IO release, 9d1b949, and later): the bus driver bounds its waits, and a failed transfer is retried or reported as an error; the known exceptions, and what assumes a 1541, are listed under Limits in `docs/design/iec-failed-send.md`. On a C64 Ultimate with a JiffyDOS KERNAL, a 2 MB REU and a physical JiffyDOS 1541 it passed 300 write-and-read-back cycles under Breadbin with the disk cache off (no failure, no retry) and 50 reset-and-boot cycles with the REU cache on (no failure); with the cache on, only the first of those boots read Breadbin's files from the 1541, and the other 49 tested the machine's own JiffyDOS load of the boot file (`docs/design/io-trial-protocol.md`, session 5). Not yet tested this way: a stock 1541 ROM, a boot load by the stock KERNAL, a machine without an REU. Earlier automated boots failed intermittently (hangs, a panic, LOAD errors); the test harness's own memory reads (below) reproduce all three on demand and are the likely cause of the 2026-11-07 failures (inferred: those boots were not checked). The original root-mount stall, seen also with no memory reads, is mitigated by the retries but was never root-caused.

**Do not read or write C64 memory over the Ultimate's REST API while a disk transfer may be running.** Every `readmem` is a DMA that halts the 6510: a 1000-byte read for about 1 to 2 ms, and even a 1-byte read now and then for about 680 cycles. A halt inside a serial-bus byte loses or corrupts it. A `writemem` (a key typed into the key buffer, say) goes over the same DMA path and is treated the same way, though its halt has not been measured. On the hardware this broke the machine's own `LOAD` under the stock and JiffyDOS KERNALs, not only Breadbin: a 1000-byte read every 0.5 s left a corrupted file that the load reported as good in 4 of 4 trials with JiffyDOS and hung it in 4 of 4 with the stock KERNAL, and even a 1-byte read every 0.1 s during a JiffyDOS load failed 4 of 4 (`docs/design/io-trial-protocol.md`, sessions 2 to 4). The Ultimate test backend (`tools/ultimatetest.py`) makes no request during the machine's own load, gates its screen reads and key writes on an idle bus, and reports the races it can see; its comments list the ones it cannot, and its 1-byte probes still run during Breadbin's transfers.

## Try it

Things to type at the `/ $` prompt:

```
ls /bin
cat /home/readme | grep unix | wc
mkdir /home/src ; cd /home/src ; echo hi > f ; ls -l
count > /dev/null &
ps
kill 5                      (use the pid that ps shows)
basic /home/hello.bas
as /home/hello.s /home/hello ; /home/hello
df ; free
edit /home/notes            (^O saves, ^X quits)
mount 9 /mnt ; ls /mnt      (needs a disk in drive 9)
format 9 c64fs             (or: format 9 cbm name - erases drive 9)
theme c64
```

At the `login:` prompt, type `root` or `user`; neither has a password until you set one with `passwd`.

On a C64 keyboard, `|` is **SHIFT + `-`**, and RUN/STOP interrupts the running command.

## Platform tiers

One disk boots everywhere; features are chosen by probing at run time. The core never requires an REU or an Ultimate. Details: [docs/roadmap.md](docs/roadmap.md).

| Tier | Machine | Promise |
|------|---------|---------|
| Classic | stock C64, 1541, no REU | boots to a shell; maintained and tested under VICE |
| Expanded | Classic plus an REU | adds `/tmp` on the REU and the block cache |
| Recommended | an Ultimate with UCI | everything; new work targets this tier first |

## Disks

The boot disk is mounted at `/`. More drives work too: put a disk in drive 9, 10 or 11 and `mount 9 /mnt`. A Breadbin disk keeps its directories; a normal C64 disk shows up flat and stays readable by other C64 software. To make a new disk, run `format 9 c64fs mydisk` (with directories) or `format 9 cbm mydisk` (a normal C64 disk). Both erase drive 9 and ask first. `df` shows free space, and `umount /mnt` detaches the disk.

[docs/filesystem.md](docs/filesystem.md) explains it all: the on-disk layout of c64fs (superblock, bitmap, inodes, directories), the REU RAM disk, how normal C64 disks are handled, what `format` does, and the limits.

## Commands

`sh` `init` `login` `ls [-l] [-a]` `cat` `echo` `grep [-v] [-c]` `wc` `head [-n]` `tail` `tee` `sort` `touch` `more` `edit` `cp` `mv` `rm` `mkdir` `rmdir` `pwd` `stat` `hexdump` `ps` `kill [-sig]` `sleep` `free` `df` `mount` `umount` `format` `uptime` `date` `uname [-a]` `version` `whoami` `passwd` `theme` `turbo [0-15|off|max]` `help` `clear` `count` `basic` `as` `cache` `mod` `exec`

Shell built-ins: `cd`, `exit`, `kill`, `jobs`.

## Layout

| Path | What |
|------|------|
| `src/kernel/` | the kernel (ca65): `proc.s` scheduler, IRQ, signals · `jtab.s` syscall table at `$CF00` · `exec.s` loader · `file.s` fds, pipes, file syscalls · `fs.s` c64fs · `blk.s` block devices and the REU block cache · `iec.s` serial bus driver · `kbd.s` keyboard · `con.s` console · `mem.s` page allocator · `cbm.s`, `uci.s` resident parts of CBM DOS and UCI support |
| `src/mod/` | kernel modules (`cbm.s`, `uci.s`) |
| `src/bin/` | user programs |
| `src/lib/` | the user library linked into programs |
| `include/breadbin.inc` | the system-call interface for programs |
| `tools/mkimage.py` | builds and inspects disk images (`ls`, `cat` subcommands) |
| `tools/cx.py` | makes relocatable executables |
| `tools/vicetest.py` | drives VICE for the automated tests |
| `docs/filesystem.md` | disks, mounting, `format`, and the on-disk layout |
| `docs/testing.md` | which tests to run for which change |
| `docs/roadmap.md` | where this fork is heading: limits, milestones, and the first stories |
| `docs/why-this-fork.md` | how this fork differs from upstream |
| `docs/process.md` | how sessions work together: branches, the machine lock, kickoff |
| `docs/size-ledger.tsv` | kernel bytes and headroom per landing (`make size` measures) |
| `tools/land.sh` | merges a branch into main after building and running the host tests |
| `docs/superpowers/` | original design spec and implementation plan |
| `tools/setup-vice-roms.sh` | fetches the ROMs VICE needs for `make test` |

## How it works

- **Memory.** The BASIC and KERNAL ROMs are banked out (the KERNAL is replaced; no ROM is used at run time). The kernel starts at `$A300` (`KSTART`) with the syscall table at `$CF00`, and programs get 256-byte pages from `$0800–$A2FF` (155 pages, 39,680 bytes). `KSTART` (`src/kernel/k.inc`) and `KRAM` (`src/kernel.cfg`) move together, a page at a time.
- **Context switch.** Each process has its own zero page `$02–$3F` and its slice of the stack page; both are saved and restored on every switch.
- **Kernel preemption.** The kernel itself is not preemptible, so disk I/O is a critical section. The kernel's own IEC driver is not re-entrant.
- **Executables (CX format).** Each program is linked twice, at `$0000` and at `$0100`. The bytes that differ by one are high bytes of addresses, and their offsets become the relocation table. The loader adds the load page to each of them.
- **Disk.** The `.d64` is a hybrid. Its CBM DOS directory holds only the boot file `BREADBIN` (`LOAD"*",8,1` / `RUN`). The rest of the disk is c64fs (Breadbin's filesystem), starting with its superblock at track 19 sector 0. The kernel reads and writes raw sectors with the drive's `U1`/`U2`/`B-P` commands.

## Tests

```sh
tools/ci/run.sh all test-host   # the fast gate: image tools, simulators, the assembler and compiler on the host
tools/ci/sharded.sh             # the whole VICE suite in six containers at once
tools/ci/shards.py check 6      # host only: every VICE test is in exactly one of at most six shards
make && make test-host          # the same host tests directly (build first: without build/ the tests that need the kernel skip), with cc65 and py65 installed
make test                       # boots VICE one test after another (slow)
```

The system tests start `x64sc` (windows open minimized), type commands through VICE's remote monitor, and read the screen back. They need `x64sc` and `c1541` on your `PATH` (or set `X64SC=/path/to/x64sc`). Timing: see [docs/testing.md](docs/testing.md). Don't run other VICE instances at the same time: the tests are timing-sensitive under heavy CPU load.

Extract a file from a disk image on the host:

```sh
python3 tools/mkimage.py ls  build/breadbin.d64 /home
python3 tools/mkimage.py cat build/breadbin.d64 /home/readme
```

## License

MIT - see [LICENSE](LICENSE). Copyright (c) 2026 Konstantinos Patronas <kpatronas@gmail.com>.
