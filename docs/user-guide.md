# Breadbox User Guide

*A practical guide to building, booting, and using Breadbox on the Commodore 64*

Breadbox is a small, Unix-like operating system for the Commodore 64. It is designed to make the machine a place where you can run real programs, work with files, connect commands together, and write software on the computer itself.

The source repository and several on-disk names still say **breadbin**. The current boot banner says **breadbox**. Those names refer to this same project.

This guide is for people using Breadbox, not just people hacking on its kernel. It covers the supported machine configurations, everyday operation, storage, commands, and the design choices that shape the system. For implementation detail, see the linked documents in `docs/`.

> **Status and compatibility.** Breadbox is active software. Features depend on the hardware and modules present, and some capabilities are still experimental or have known limits. The Classic configuration remains the baseline; an Ultimate with UCI is the recommended platform for current development.

## 1. Getting to know Breadbox

### A small computer with a real operating system

Breadbox is not a BASIC program pretending to be a shell. It has a kernel, independent programs, a filesystem, and a preemptive process scheduler.

The main ideas are familiar if you have used a Unix-like system:

- **Commands are programs.** Utilities such as `ls`, `cat`, `grep`, and `wc` are separate executables. The shell starts them as processes.
- **Commands compose.** Pipes pass data between programs; redirection connects programs to files.
- **Programs can run concurrently.** Add `&` to run a command in the background, inspect it with `jobs` or `ps`, and stop it with `kill` or RUN/STOP.
- **Directories are real.** The native filesystem supports directories, pathnames, and a working directory.
- **The machine is the development environment.** A full-screen editor and a 6502 assembler run on the C64. BASIC is included too.

Breadbox replaces the normal KERNAL at run time. It supplies its own interrupt entry, keyboard and screen handling, and serial-bus driver. It does not depend on Commodore's KERNAL ROM while running.

### First boot

Build or obtain a bootable `.d64` image, attach it as drive 8, and boot it with the normal C64 disk-load sequence:

```basic
LOAD"*",8,1
RUN
```

The system starts its login program. The initial accounts are `root` and `user`; neither has a password until one is set with `passwd`. Use `root` for administration such as loading kernel modules and formatting disks. Use `user` for ordinary work.

At the shell prompt, try:

```sh
help
ls /
cat /etc/motd
```

The exact startup text may vary by build. The `help` command displays the command-help file installed on that disk.

**Keyboard note:** on a C64 keyboard, the pipe character `|` is typed with **SHIFT + -**. RUN/STOP sends an interrupt to the foreground command.

### A first taste

These examples are intended to be typed at the Breadbox prompt:

```sh
ls /bin
cat /home/readme | grep unix | wc
mkdir /home/work
cd /home/work
echo hello > greeting
cat greeting
count &
jobs
ps
```

The shell supports command sequencing with `;`, conditional sequencing with `&&` and `||`, background execution with `&`, history, TAB completion, wildcards, and the usual input/output redirection operators. Pipes connect the output of one process to the input of the next.

## 2. Building Breadbox

### What you need

The normal image build is performed on a development computer. You do not need VICE merely to assemble and link the system.

| Tool | Purpose |
|---|---|
| cc65 (`ca65`, `ld65`, `ar65`) | Assemble and link the kernel and C64 programs |
| Python 3.8 or newer | Build disk images and relocatable executables |
| GNU make | Run the build |
| VICE (`x64sc`, `c1541`) | Emulation, running the system, and automated tests |

The project has been tested with cc65 2.19, GNU make 3.81, Python 3.15, and VICE 3.9/3.10.

Typical installation:

```sh
# macOS
brew install cc65 vice python3

# Debian or Ubuntu
sudo apt install cc65 vice python3 make
```

On Windows, use WSL with the Debian/Ubuntu instructions, or use the Windows cc65 and VICE builds from an MSYS2 environment.

### Build the standard disk

```sh
git clone https://github.com/sandmanbuzz/breadbin.git
cd breadbin
make
```

The default build creates:

| Output | Contents |
|---|---|
| `build/breadbin.d64` | Bootable 1541 disk image |
| `build/breadbin.prg` | Kernel/boot program |
| `build/root/bin/*` | Built relocatable command executables |

The disk image is assembled from the kernel, programs in `src/bin/`, and the files in `rootfs/`. A new assembly command placed in `src/bin/NAME.s` is picked up by the build and installed as `/bin/NAME`.

To remove generated output and start clean:

```sh
make clean
make
```

### Build-time options

The normal build defaults are intended to be useful without extra configuration. These make variables are available when you want a particular kernel configuration:

| Variable | Default | Example | Effect |
|---|---:|---|---|
| `CACHE` | `1` | `make CACHE=0` | Selects the boot-drive REU block-cache default. `0` leaves it off until enabled with `cache on`; `1` enables the normal default. |
| `JIFFY` | `1` | `make JIFFY=0` | Includes or omits the JiffyDOS byte protocol. With `0`, the standard serial protocol is used. |
| `NBUF` | `6` | `make NBUF=3` | Sets the number of kernel block-cache buffers. This is an implementation/build tuning option. |
| `IOSTAT` | `1` | `make IOSTAT=0` | Includes or omits block-read counters used for diagnostics. |
| `STKWATCH` | unset | `make STKWATCH=1` | Builds stack high-water instrumentation for development. |

These are build configuration knobs, not a menu of hardware tiers. The system probes for optional hardware at boot and enables the facilities it can actually use. If you change build variables, use a clean build when in doubt.

### Run in VICE

```sh
make run
make run-reu
```

The first command starts the standard disk in VICE. The second starts it with a 512 KB REU. To attach another disk as drive 9:

```sh
x64sc -drive9type 1541 -9 other.d64 -autostart build/breadbin.d64
```

You can also attach the image manually and enter `LOAD"*",8,1` followed by `RUN`.

### Running on real hardware

Breadbox is designed to run on a stock C64 with a 1541-class drive, and on expanded systems. A C64 Ultimate is the recommended platform for current development, especially when its Command Interface (UCI) is enabled.

The boot drive must understand the 1541 sector commands used by the system (`U1`, `U2`, and `B-P`): a real 1541 or 1571, or a compatible 1541 emulation. A normal CBM DOS disk image can be written to floppy with a tool such as OpenCBM's `d64copy`.

**Important Ultimate caution:** do not use the Ultimate REST memory-read or memory-write API while a disk transfer may be in progress. These operations use DMA and halt the 6510 long enough to disturb serial-bus transfers. The project's hardware notes and test protocol document the measured failure modes and safe test procedure.

## 3. Choosing a platform

One disk image is intended to boot across the supported tiers. Optional capabilities are detected at run time; an REU or Ultimate is not required by the core.

| Tier | Typical setup | What to expect |
|---|---|---|
| **Classic** | Stock C64 + 1541, no REU | Core OS, shell, programs, and native disk filesystem |
| **Expanded** | Classic plus an REU | REU-backed `/tmp` and boot-drive block caching; single-drive disk swapping can use the cache |
| **Recommended** | C64 Ultimate with UCI enabled | Adds Ultimate file storage through the UCI module; this is the preferred target for new platform work |

A physical 1541 is substantially slower than modern storage. JiffyDOS support improves the host-side serial transfer when a compatible JiffyDOS drive is detected. The `JIFFY=0` build option disables that protocol.

The optional stock-1541 fast block-transfer module is separate from JiffyDOS. It is not a general-purpose fast path for every drive type; consult the module and fast-I/O design notes before expecting it to apply to a particular device.

## 4. Using the system

### Files and paths

The boot volume is mounted at `/`. Paths may be absolute (starting with `/`) or relative to the current working directory. Use `pwd` to see where you are and `cd` to change directories.

```sh
pwd
cd /home
ls -la
mkdir projects
cd projects
touch notes
```

The native filesystem is case-sensitive. Names can be up to 14 characters. The current working-directory path limit is 47 characters.

### Pipes, redirection, and background jobs

A pipe sends one command's standard output to the next command's standard input:

```sh
cat /home/readme | grep unix | wc
```

Redirection sends output to a file (`>` creates or replaces; `>>` appends) or supplies a file as standard input (`<`):

```sh
echo first > notes
echo second >> notes
cat < notes
```

A pipeline is made of processes and kernel pipe buffers. A reader waits while the pipe is empty; a writer waits while it is full. If every reader closes its end, a writer receives `SIGPIPE`.

Add `&` to start a command in the background. Use `jobs` for the shell's job list and `ps` for the process table. RUN/STOP interrupts the foreground job. `kill` can send a selected signal to a process.

### Processes and signals

Breadbox supports preemptive round-robin multitasking, with up to eight processes. The shell can start jobs in the background while you continue typing. The kernel supports signals; RUN/STOP sends `SIGINT` to the foreground job, and `kill` sends a signal to a process by PID.

The kernel itself is not preemptible. In particular, disk I/O occupies the kernel's serial-bus path, so other processes pause while that transfer is in progress.

### Users and administration

The system includes `login`, `passwd`, and `whoami`. The initial `root` and `user` accounts have no password until configured. Kernel module loading/unloading and destructive disk formatting require root privileges.

Set passwords before treating a machine as a shared or unattended system. Breadbox's current user and permission model is intentionally modest; it should not be mistaken for strong isolation between mutually untrusted users or programs.

### Editing and programming

The `edit` command opens the full-screen text editor. In the editor, **Ctrl-O** saves and **Ctrl-X** exits.

The on-machine assembler, `as`, assembles 6502 source into a relocatable Breadbox executable. For example:

```sh
as /home/hello.s /home/hello
/home/hello
```

The trailing `.res` directive in assembly source reserves a program's BSS space; large buffers need not occupy disk space in the executable.

The `basic` command runs Breadbox's integer BASIC interpreter:

```sh
basic /home/hello.bas
```

It is a small, integer-oriented BASIC, not a complete implementation of Commodore BASIC. The host-side `tools/cc.py` compiler is an experimental C-subset tool that emits assembler source; it is not a C compiler running on the C64.

### Screen themes and CPU speed

Use `theme` to inspect or select a screen theme (for example, `theme c64`). The `turbo` command reads or changes the C64 Ultimate's CPU-speed index when the Ultimate turbo registers are enabled in its configuration. It is not available on an ordinary C64.

## 5. Disks and filesystems

Breadbox supports several storage backends. They are not interchangeable: each has different naming, directory, compatibility, and performance characteristics.

### c64fs: the native filesystem

c64fs is Breadbox's native filesystem. It supports directories, files, pathnames, and executable programs. The boot disk uses c64fs.

A 1541 c64fs volume uses the disk's sectors directly. Its superblock, bitmap, inode table, directories, and file data are laid out in the filesystem area; the CBM DOS directory and BAM are reserved so the drive's own DOS does not overwrite the native volume. Other C64 software cannot browse the c64fs files as ordinary CBM DOS files.

Current format is **c64fs format 2**, compatible at the image-format level with upstream Breadbin's format 2. The filesystem has 128 inode slots (127 usable), a 14-character filename limit, and a maximum file size of 35,840 bytes.

### CBM DOS disks: exchange media

A normal C64 disk is mounted as a flat directory. Breadbox can list, read, copy files to and from it, delete files, and rename files. This is the format to use when exchanging files with other C64 software or host-side disk tools.

Because CBM DOS has no directory hierarchy, `mkdir` and `rmdir` are not supported on such a mount, and programs cannot be executed from it. New files written to a CBM DOS disk are SEQ files. Only one file per drive may be open for writing at a time.

### REU RAM disk: `/tmp`

When an REU is detected, Breadbox formats it at boot as a temporary c64fs volume and mounts it at `/tmp`. It is fast, but its contents are **not persistent**: the RAM disk is empty after every reboot. Without an REU, `/tmp` is simply a directory on the boot disk.

The REU is also used for the boot-drive block cache when enough memory is available. The cache occupies the upper REU banks; the remaining banks provide the RAM disk.

### Ultimate storage: UCI

On a C64 Ultimate with the Command Interface enabled, the UCI kernel module exposes the Ultimate's file storage. Load the module and mount it:

```sh
mod load /lib/km/uci
mount uci /u
```

UCI is useful for moving larger files between the C64 and the Ultimate's host-side storage. It has different semantics and capabilities from a 1541 volume, including support for long names and larger files. UCI v1 is an Ultimate-specific facility; it is not available on a stock C64.

### 1581 c64fs volumes

The `d81` module provides 1581 block geometry for c64fs volumes. Load it before mounting a 1581 c64fs disk:

```sh
mod load /lib/km/d81
mount 9 /mnt
```

A 1581 volume is a c64fs data volume, not a boot disk. Normal 1581 CBM DOS disks are not supported by this driver. Unload the module only after unmounting the 1581 volume.

### Mounting and unmounting disks

Insert a disk in drive 9, 10, or 11 and mount it on an existing directory:

```sh
mount 9 /mnt
mount
ls /mnt
umount /mnt
```

With no arguments, `mount` lists active mounts and identifies their type. Up to four mounts can be active at once, including `/tmp`. A mount point must already exist. `umount` refuses to detach a device while a process has an open file on it or has its working directory there; close files and change directory first.

### One-drive operation: eject and reattach

With enough REU memory for the boot-drive cache, the `eject` module can copy the boot volume's active blocks into the cache and release the physical drive. You can then put another disk in drive 8 and mount it elsewhere. The root volume is effectively read-only while its disk is away: operations that need to change it wait until the disk returns.

After unmounting the temporary disk and putting the boot disk back, run `reattach`. The system checks the disk label and build identity against the cached volume before reconnecting it. This feature requires an REU with sufficient space; it is unavailable on a no-REU single-drive system.

### Formatting a disk

**Formatting erases the disk.** It is restricted to drives 9, 10, and 11; the running boot drive is protected. The command asks for confirmation.

```sh
format 9 c64fs work
format 9 cbm exchange
```

- `c64fs` (the default) creates a native filesystem with directories.
- `cbm` creates a normal C64 disk that other C64 software can read.
- The optional final argument supplies the disk name; the default is `breadbin`.

Formatting a 1581 c64fs volume requires the `d81` module. Formatting takes a while on a real 1541 and the system pauses while it completes. Use expendable media only.

### Preparing images on the host

The host tool `tools/mkimage.py` can build and inspect c64fs images:

```sh
python3 tools/mkimage.py build data.d64 --boot build/breadbin.prg --root myfolder
python3 tools/mkimage.py ls build/breadbin.d64 /home
python3 tools/mkimage.py cat build/breadbin.d64 /home/readme
python3 tools/mkimage.py d81 data.d81 --root myfolder
```

It can also upgrade older format-1 images to format 2. If upgrading a bootable image, supply a current boot program with `--boot`; otherwise the old boot program will remain and will not understand the new filesystem format.

## 6. Command reference

The command set is split between external programs in `/bin` and shell built-ins. The list below describes the user-facing commands currently included in the project; consult `help` on the target disk for the help text shipped with that build.

### Shell built-ins

| Command | Purpose |
|---|---|
| `cd [DIR]` | Change the current directory. |
| `exit` | Exit the current shell. |
| `kill PID` | Shell built-in form of process signalling. |
| `jobs` | List jobs known to the current shell. |

The shell also interprets pipelines, redirection, sequencing, conditionals, background execution, wildcards, command history, and TAB completion.

### File and text commands

| Command | Purpose |
|---|---|
| `ls [-l] [-a] [PATH...]` | List directory entries; long and all-entry views are available. |
| `pwd` | Print the current working directory. |
| `cat FILE...` | Write file contents to standard output. |
| `echo [TEXT...]` | Write text to standard output. |
| `grep [-v] [-c] PATTERN [FILE...]` | Search input for matching lines; invert matches or count matches. |
| `wc [FILE...]` | Count lines, words, and bytes. |
| `head [-n N] [FILE...]` | Show the beginning of input. |
| `tail [FILE...]` | Show the end of input. |
| `tee FILE` | Copy standard input to output and a file. |
| `sort [FILE...]` | Sort input lines. |
| `more FILE` | Page through a text file. |
| `touch FILE...` | Create files or update their presence. |
| `cp SOURCE DEST` | Copy a file. |
| `mv SOURCE DEST` | Move or rename a file. |
| `rm FILE...` | Remove files. |
| `mkdir DIR...` | Create directories. |
| `rmdir DIR...` | Remove empty directories. |
| `edit FILE` | Edit a text file in the full-screen editor. |
| `stat PATH` | Display file information. |
| `hexdump FILE` | Display file bytes in hexadecimal. |

### Process and system commands

| Command | Purpose |
|---|---|
| `ps` | Show processes. |
| `kill [-sig] PID` | Send a signal to a process. |
| `sleep N` | Wait for a number of seconds. |
| `free` | Show memory availability. |
| `df` | Show filesystem space. |
| `uptime` | Show time since boot. |
| `date` | Show the system date/time value. |
| `uname [-a]` | Show system identification. |
| `version` | Show the build/version information. |
| `whoami` | Show the current user. |
| `passwd` | Set or change a password. |
| `login` | Start the login flow. |
| `clear` | Clear the screen. |
| `theme [NAME]` | Show or select a screen theme. |
| `help` | Display the installed help text. |

### Storage and module commands

| Command | Purpose |
|---|---|
| `mount` | List mounted volumes. |
| `mount DRIVE DIR` | Mount drive 9–11 on an existing directory. |
| `mount uci DIR` | Mount Ultimate storage (requires UCI module and enabled interface). |
| `umount DIR` | Unmount a volume. |
| `format DRIVE [cbm\|c64fs] [NAME]` | Erase and format drive 9–11. |
| `mod ls` | List loaded kernel modules. |
| `mod load PATH` | Load a kernel module (root). |
| `mod unload SLOT` | Unload a module by slot number (root). |
| `cache [stat\|off\|on\|flush]` | Inspect or control the REU boot-drive block cache. |
| `eject` | Release the boot disk using the REU cache (requires module and REU). |
| `reattach` | Reconnect the boot disk after it is returned to the drive. |

### Programming and special-purpose commands

| Command | Purpose |
|---|---|
| `basic FILE` | Run the integer BASIC interpreter on a program file. |
| `as SOURCE OUTPUT` | Assemble 6502 source into a Breadbox executable. |
| `exec PATH` | Replace the current process with another executable. |
| `count` | Run the counter/demo workload. |
| `turbo [0-15\|off\|max]` | Read or set the Ultimate CPU-speed index when turbo registers are enabled. |

Some commands accept fewer options than their Unix namesakes. This reference is a quick guide, not a promise of full POSIX compatibility. The on-disk `/etc/help` file is the definitive short help for the build you are running.

## 7. Design notes: why Breadbox works this way

### The C64 is the whole computer

Breadbox aims to make the C64 useful as a self-contained programming machine. The host computer is used to assemble and package releases, but the shell, editor, BASIC interpreter, assembler, filesystem, and programs run on the C64.

### One disk, optional capabilities

The same boot image targets a stock C64 first. REU and Ultimate facilities are optional additions discovered at run time. This avoids making an expansion device a prerequisite for the operating system itself.

### Processes, not command emulation

A command is an executable process. The scheduler, process table, file descriptors, pipes, and signals are kernel facilities. This costs scarce memory, but makes shell composition meaningful: a pipeline is a chain of programs, not a special case in a command interpreter.

### Memory is the tightest budget

The kernel and programs share a small address space. User memory is allocated in pages, process state is saved and restored during context switches, and executable files use a compact relocatable format (CX). The build's size tools and ledger exist because kernel bytes are a first-class engineering constraint.

### Storage is block-oriented underneath

The kernel's native filesystem uses sector-sized blocks on disk. The boot disk is a hybrid image: the CBM DOS directory exposes the boot program, while c64fs owns the remaining filesystem area. The kernel talks to drives using sector commands rather than relying on the KERNAL's file layer.

### Modules keep optional drivers out of the core

CBM DOS support, UCI, 1581 geometry, stock-1541 fast block reading, and single-drive eject support are supplied as loadable kernel modules. This keeps optional functionality separate from the resident kernel and makes hardware-specific support explicit.

### Fast I/O has multiple paths

JiffyDOS is a host-side byte protocol used with compatible JiffyDOS drives. The `fast` module is a different, drive-side block-transfer path for supported 1541-class drives. UCI is a third path that accesses Ultimate storage rather than a disk drive. They solve different problems and should not be conflated.

### Deliberate limitations

Breadbox is not a modern protected multi-user OS squeezed into a C64. The kernel is not preemptible, disk transfers stall other processes, the process count and file tables are small, and the user/permission model is basic. Networking and a full C toolchain are not current user-facing capabilities. The project prefers explicit limits over implying that a familiar Unix command or facility is more complete than it is.

## 8. Further reading

The repository's other documents go deeper than this user guide:

- [README](../README.md) — project overview, quick build, and quick-start commands.
- [Filesystem notes](filesystem.md) — c64fs layout, mount behaviour, CBM DOS compatibility, REU, and 1581 details.
- [Hardware notes](hardware-notes.md) — real-machine observations and hardware test procedures.
- [Roadmap](roadmap.md) — project direction, current state, and planned work.
- [Why this fork](why-this-fork.md) — relationship to upstream Breadbin.
- [Fast I/O design](design/fast-io.md) — JiffyDOS and drive-side transfer approaches.
- [Testing guide](testing.md) — automated test suites and when to run them.
- [IEC failure handling](design/iec-failed-send.md) — serial-bus failure recovery and its limits.

---

*This guide describes the current repository state; command details, hardware support, and build options may change as Breadbox develops.*
