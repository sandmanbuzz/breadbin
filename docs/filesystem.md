# Disks and the filesystem

This explains how Breadbin stores files, how to use more than one disk, and how to make new disks.

## The short version

| You want to… | Do this |
|---|---|
| Use the boot disk | It is mounted at `/` automatically. |
| Use a second disk | Put it in drive 9 (or 10, 11), then `mount 9 /mnt`. |
| Stop using it | `umount /mnt`. Close files and `cd` off it first. |
| Make a new Breadbin disk | `format 9 c64fs mydisk`, then `mount 9 /mnt`. |
| Make a normal C64 disk | `format 9 cbm mydisk`, then `mount 9 /mnt`. |
| See free space | `df` |
| See what is mounted | `mount` |

`format` erases the whole disk and asks first. It only works on drives 9, 10 and 11: drive 8 holds the running system.

## Two kinds of disk

Breadbin understands two disk formats.

**c64fs**, Breadbin's own filesystem. It has real directories (`mkdir`, `cd`, `..`), and programs on it can be run. The boot disk is c64fs. Other C64 software sees a c64fs disk as one file (the boot file) plus a full disk, and can't read the files on it.

**CBM DOS**, the normal C64 disk format. Every C64 program, and tools like `c1541`, can read it. Breadbin shows it as one flat directory: you can `ls`, `cat`, `cp` to and from it, `rm` and `mv`, but not `mkdir`, and programs can't be run from it. Use it to swap files with the rest of the C64 world.

`mount` tells them apart by itself, and `mount` with no arguments shows which kind each drive is:

```
/ $ mount
drive 8 on / (c64fs)
drive 9 on /mnt (cbm dos)
```

## Devices and mount points

| Device | What | Where |
|---|---|---|
| 0 | drive 8, the boot disk | `/` |
| 1 | the REU RAM disk, if an REU is fitted | `/tmp` |
| 2, 3, 4 | drives 9, 10 and 11 | wherever you `mount` them |

Mount points are ordinary directories (the boot disk has an empty `/mnt` for this). Up to four mounts can be active at once, `/tmp` included. Path lookup crosses into a mounted disk when it reaches the mount point, and `..` from the top of a mounted disk leads back out, so `cd /mnt/src; cd ../..` ends up at `/`.

`umount` refuses with "device busy" while any process has a file open on that disk or has its working directory there.

## c64fs on disk

The on-disk format is **format 2**, the one upstream Breadbin uses (kpatr1981/breadbin, MIT, Copyright (c) 2026 Konstantinos Patronas; commits 2ff35e5 and 5f2a9ec, and bf712c2 for the 1581): disks made by either side's tools mount under the other's. Format 1 (magic `C64FS`, 32-byte inodes, one bitmap block) is no longer mounted: a format 1 disk in drive 9–11 shows up as a CBM DOS disk (its BAM marks everything used), and on drive 8 or the REU it does not mount. `tools/mkimage.py upgrade` converts one (below).

A 1541 disk has 683 sectors of 256 bytes: 35 tracks with 17 to 21 sectors each. c64fs numbers them as **blocks 0 to 682** in the usual `.d64` order: track 1 sector 0 is block 0, track 18 sector 0 is block 357, and track 19 sector 0 is block 376.

| Blocks | Contents |
|---|---|
| 357 – 375 (track 18) | the CBM DOS directory and BAM, left for the drive's DOS |
| 376 | c64fs superblock |
| 377 | block bitmap |
| 378 – 409 | inode table (32 blocks, 128 inodes) |
| everything else | file and directory data |

On the boot disk, the CBM directory on track 18 lists a single file, `BREADBIN`: the kernel, which `LOAD"*",8,1` loads. Its sectors start at block 0. Every sector of the disk is marked used in the CBM BAM, so the drive's own DOS never writes over c64fs. That's why other C64 software sees the disk as full.

### Superblock (block 376)

| Offset | Size | Field |
|---|---|---|
| 0 | 5 | magic `C64F2` |
| 5 | 1 | version (2) |
| 6 | 2 | number of blocks (683; 3200 on a 1581) |
| 8 | 1 | number of inodes (128) |
| 9 | 2 | first bitmap block (377) |
| 11 | 2 | first inode block (378; 379 on a 1581) |
| 13 | 1 | inode blocks (32) |
| 14 | 1 | root directory inode (1) |
| 15 | 4 | upstream's `last_time`: written 0 here |
| 252 | 4 | the build id the REU block cache keys on (`SB_BUILD_ID`, `src/kernel/blk.s`); 0 on disks without a boot file |

Everything else is 0. The build id was at 15 before format 2; it moved to 252 because upstream's kernel rewrites bytes 15–18 (its clock) and its `format` writes them.

### Bitmap (blocks 377 to the first inode block)

There is one bit per block, and a set bit means used: block b is bit b mod 8 of byte (b / 8) mod 256 of the bitmap's block b / 2048. A 1541 disk needs one bitmap block, so bits 683 to 2047 are always set; a 1581 needs two, with bits 3200 to 4095 set. Block 0 is always used too, because block number 0 inside an inode means "no block here".

### Inodes (blocks 378–409)

An inode is 64 bytes, 4 per block. Inode 0 is reserved and inode 1 is the root directory. Bytes 0–31 are below; 32–35 and 36–39 are upstream's modification and change times, and 40–63 are reserved.

**Times are not kept here (yet).** Breadbin's tools and kernel write 0 where upstream writes times, and the kernel writes bytes 32–63 as 0 whenever it rewrites an inode, so a file changed under Breadbin has "no time" rather than a stale one; inodes it does not change keep what upstream wrote. With a time of 0, upstream's `ls -l` leaves the date blank, and its `mkimage.py ls` prints `70-01-01 00:00`.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | type: 0 free, 1 file, 2 directory, 3 device |
| 1 | 1 | link count |
| 2 | 3 | size in bytes |
| 5 | 1 | device major number (0 = `/dev/null`, 1 = `/dev/console`) |
| 6 | 24 | 12 direct block numbers, 2 bytes each |
| 30 | 2 | indirect block: a block holding 128 more block numbers |

12 direct blocks plus 128 through the indirect block give a largest file of 140 × 256 = 35,840 bytes, more than a C64 can hold in memory anyway.

### Directories

A directory is a file of 16-byte entries: 1 byte for the inode number (0 = unused slot) and 15 bytes for the name (up to 14 characters, NUL-padded). Every directory starts with `.` (itself) and `..` (its parent). Names are ASCII and case-sensitive; `/`, `.` and `..` are special.

### How the kernel reaches the disk

The kernel reads and writes whole sectors with the 1541's sector commands: `U1` reads a block, `B-P` with `U2` writes one. Those go through the KERNAL's serial routines on the command channel (15) and a data channel with a drive buffer (`#`). A cache of 6 blocks sits in front of the drive. It is write-through: every change goes to the disk at once, so nothing is lost if you switch off between commands.

While the disk is busy, every other process waits: the kernel's own IEC driver is not re-entrant (it holds interrupts off while it is the talker, `src/kernel/iec.s`). A stock 1541 reads roughly one block per second through these commands, so loading a 1–3 KB command takes a few seconds.

## The REU RAM disk (`/tmp`)

With a RAM Expansion Unit, the kernel formats the REU as c64fs at every boot and mounts it at `/tmp`. The layout is the same idea with different block numbers: superblock at block 0, bitmap at 1, inodes at 2–33 (format 2, 128 inodes). Its size is that of the REU, up to 2048 blocks (512 KB): the banks above hold the boot drive's block cache, so the RAM disk keeps one bitmap block (upstream's grows with the REU). It is fast, and it is **empty after every reboot**. Without an REU, `/tmp` is an ordinary directory on the boot disk.

## Normal C64 disks (CBM DOS)

When drive 9–11 holds a normal C64 disk, Breadbin handles it like this:

- **Reading** goes straight to the sectors: the directory chain on track 18, then each file's chain of track/sector links. PRG, SEQ and USR files are shown, by name: PETSCII names appear in lowercase, and names longer than 14 characters are cut short.
- **Writing, deleting and renaming** go through the drive's own DOS (`0:name,S,W`, `S0:`, `R0:`), so the BAM stays correct and the disk stays readable everywhere. New files are SEQ files. Writing to an existing name replaces that file. Only one file per drive can be open for writing at a time.
- `ls -l` sizes are estimates (blocks × 254), because the true length is only known after reading the whole file.
- `mkdir` and `rmdir` are refused (the format has no directories), and so is running programs from the disk.

## `format`

```
format drive [cbm|c64fs] [name]
```

`format` erases the disk in drive 9, 10 or 11 and makes a new one. `c64fs` is the default. The name defaults to `breadbin`.

- **`format 9 cbm photos`** sends the drive's own format command (`N0:PHOTOS,BB`). The result is a normal, empty C64 disk.
- **`format 9 c64fs work`** does the same DOS format first, which lays down the sector headers, and then writes a fresh format 2 c64fs on top: it marks every sector used in the CBM BAM, writes the superblock, bitmap and inode table, and creates an empty root directory (inode 1, in block 1). On a 1581 (with `/lib/km/d81` loaded) it writes the 3200-block layout and marks every block used in the 1581's BAM on track 40. A 1581 without the module is refused after the DOS format ("mod load /lib/km/d81 first"): `format` tells the drives apart by reading block 720, which is track 35 sector 54 in the 1541 numbering (no drive has it) and track 19 sector 0 in the module's, and then block 700 (35/34, there on a 1581 only).

`format` asks `erase everything on drive 9? (y/n)` first. It refuses drive 8 and any drive that is mounted. Formatting takes a while on a real 1541 (about a minute and a half), and the rest of the system pauses meanwhile. Afterwards, `mount 9 /mnt` and the disk is ready to use.

## Making disks on the computer you build on

`tools/mkimage.py` builds and inspects c64fs disk images, which is handy for preparing a data disk or checking what Breadbin wrote:

```sh
# a new disk image holding the contents of a folder
python3 tools/mkimage.py build data.d64 --boot build/breadbin.prg --root myfolder

# look inside an image
python3 tools/mkimage.py ls  build/breadbin.d64 /home
python3 tools/mkimage.py cat build/breadbin.d64 /home/readme

# a format 1 disk (.d64 or .d81) from before format 2, rewritten as format 2
python3 tools/mkimage.py upgrade old.d64 new.d64                       # keeps the boot file
python3 tools/mkimage.py upgrade old.d64 new.d64 --boot build/breadbin.prg
```

`ls` and `cat` read format 1 images too. Images built by upstream's `mkimage.py` (format 2) read and mount here, and ours under upstream's; the two differ only in the time fields and the build id. `mkimage.py` is ported from upstream's (MIT, credit above).

`make` uses the same tool to build `build/breadbin.d64` from `rootfs/` and the compiled programs.

### A 1581 volume (`.d81`)

```sh
python3 tools/mkimage.py d81 data.d81 --root myfolder      # then, on the C64:
mod load /lib/km/d81
mount 9 /mnt
```

A 1581 (80 tracks of 40 sectors) holds a c64fs volume to mount on drive 9, 10 or 11, not a disk to boot from. The kernel's block mapping is the 1541's; the module `/lib/km/d81` repoints the four calls that need to know (the track and sector of a block, for reading and for writing, and the drive open in `mount` and in `format`'s raw access) and asks each drive it opens for its geometry: a "U1" of track 1 sector 39 works on a 1581 and fails at once on a 1541. On a 1581, block n is track 1 + n / 40, sector n mod 40, which is its place in the `.d81` file. Load the module before mounting; `mod unload` refuses while a 1581 volume is mounted. The volume is the whole disk, 3200 blocks (800 KB), in upstream's layout: bitmap 377–378, inodes 379–410. Track 40 holds the 1581's own header, BAM (every block allocated) and an empty directory, so its DOS lists a full, empty disk and never writes; c64fs keeps out of it. `format` makes such a volume when the module is loaded. Upstream finds a 1581 by reading its header (track 40 sector 0); the module keeps its own probe, which costs one command and no block read, and also turns away a 1571. Normal 1581 DOS disks are not readable by `mount`.

For normal C64 disk images, use VICE's `c1541`, for example `c1541 -format "mydisk,md" d64 mydisk.d64`.

## Limits

| Limit | Value |
|---|---|
| file size | 35,840 bytes |
| files and directories per disk | 127 |
| blocks per disk | 683 (1541), 3200 (1581), 2048 (REU RAM disk) |
| name length | 14 characters |
| path length (working directory) | 47 characters |
| mounts at once | 4 (including `/tmp`) |
| open files, system-wide | 24 |
| open files per process | 8 |
| writable files on a CBM disk | 1 per drive |
