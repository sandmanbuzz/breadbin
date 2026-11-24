#!/usr/bin/env python3
"""Build and inspect Breadbin hybrid disk images.

A Breadbin disk is a normal 35-track .d64 whose CBM DOS directory holds a
single boot file (the kernel), and whose remaining blocks hold a c64fs
filesystem. Every block is marked allocated in the CBM BAM so the drive's
own DOS never writes over c64fs.

The c64fs written is upstream Breadbin's format 2 (magic C64F2, version 2): 64-byte
inodes, 4 a block, 32 inode blocks (128 inodes), and a bitmap of as many blocks as the
disk needs (2048 blocks each). Inode bytes 32-39 are upstream's mtime and ctime and the
superblock's bytes 15-18 its last_time: this tool writes them as zero ("unknown"; upstream's
`ls -l` shows no date for zero, its mkimage.py `ls` shows 70-01-01 00:00). Format 1 (magic
C64FS, 32-byte inodes) is read only, by `upgrade`. The format 2 layout, the multi-block
bitmap and `upgrade` are ported from upstream Breadbin (github.com/kpatr1981/breadbin,
MIT, Copyright (c) 2026 Konstantinos Patronas: commits 2ff35e5 and 5f2a9ec, and
tools/mkimage.py at 4def244).

`d81` builds a c64fs volume for a 1581 (80 tracks of 40 sectors, 3200 blocks): a disk
to mount, not to boot from (the kernel needs /lib/km/d81 loaded for the geometry). Block
n is track 1 + n // 40, sector n % 40, so the layout numbers are the 1541's (superblock
376) and the same as upstream's: 3200 blocks, bitmap 377-378, inodes 379-410. The 1581's
own header, BAM and directory on track 40 are written valid, with every block allocated,
and are reserved in the c64fs bitmap. Sources for the 1581 layout: the Commodore 1581
User's Guide and the D81 notes in the VICE manual.

Usage:
  mkimage.py build OUT.d64 --boot BOOT.prg --root DIR [--dev NAME:MAJOR ...] [--rev REV]
  mkimage.py d81 OUT.d81 [--root DIR] [--name NAME]
  mkimage.py upgrade IN OUT [--boot BOOT.prg]     (format 1 .d64 or .d81 -> format 2)
  mkimage.py reu IMG.d64 OUT.reu
  mkimage.py ls IMG PATH
  mkimage.py cat IMG PATH
"""
import argparse
import hashlib
import os
import sys

# ---- d64 geometry -------------------------------------------------------

NBLOCKS = 683
D64_SIZE = NBLOCKS * 256


def sectors_per_track(t):
    if t <= 17:
        return 21
    if t <= 24:
        return 19
    if t <= 30:
        return 18
    return 17


TRACK_START = {}
_b = 0
for _t in range(1, 36):
    TRACK_START[_t] = _b
    _b += sectors_per_track(_t)


def ts_to_block(t, s):
    return TRACK_START[t] + s


def block_to_ts(b):
    for t in range(35, 0, -1):
        if b >= TRACK_START[t]:
            return t, b - TRACK_START[t]
    raise ValueError(b)


DIR_TRACK = 18

# ---- d81 geometry -------------------------------------------------------

D81_SPT = 40
D81_BLOCKS = 80 * D81_SPT            # 3200
D81_SIZE = D81_BLOCKS * 256
D81_DIR_TRACK = 40


def d81_block(t, s):
    return (t - 1) * D81_SPT + s

# ---- c64fs layout -------------------------------------------------------


class Layout:
    def __init__(self, version, magic, inode_size, inode_blocks):
        self.version = version
        self.magic = magic
        self.inode_size = inode_size
        self.per_block = 256 // inode_size
        self.inode_blocks = inode_blocks
        self.ninodes = inode_blocks * self.per_block


LAYOUTS = {
    1: Layout(1, b"C64FS", 32, 16),   # read only (upgrade): 128 inodes
    2: Layout(2, b"C64F2", 64, 32),   # 128 inodes; bytes 32-39 upstream's times
}
VERSION = 2                          # what the kernel mounts
MAGIC = LAYOUTS[VERSION].magic
SUPER_BLOCK = ts_to_block(19, 0)     # 376, on a .d81 too
BITMAP_BLOCK = SUPER_BLOCK + 1       # 377: the first bitmap block
INODE_BLOCKS = LAYOUTS[VERSION].inode_blocks
NINODES = LAYOUTS[VERSION].ninodes   # 128, inode 0 unused
ROOT_INO = 1
INODE_SIZE = LAYOUTS[VERSION].inode_size
NDIRECT = 12
DIRENT_SIZE = 16
NAME_MAX = 14
BM_BITS = 2048                       # blocks one bitmap block covers

T_FREE, T_FILE, T_DIR, T_CHR = 0, 1, 2, 3
SB_LAST_TIME = 15                    # 4 bytes: upstream's saved clock; written 0
SB_BUILD_ID = 252                    # 4 bytes; 0 = none (the REU block cache stays off). At the
                                     # end of the block, clear of upstream's fields (0-18)


def inode_start(nblocks):
    """First inode block of a disk of nblocks: after one bitmap block per 2048 blocks."""
    return BITMAP_BLOCK + (nblocks + BM_BITS - 1) // BM_BITS


INODE_START = inode_start(NBLOCKS)   # 378 on a 1541 (379 on a 1581)


def stamp_build_id(img):
    """Key for the REU block cache: a hash of the whole image with the field zeroed,
    so any change to the image gives a new id and the same image the same one."""
    sb = bytearray(img.block(SUPER_BLOCK))
    sb[SB_BUILD_ID:SB_BUILD_ID + 4] = bytes(4)
    img.put_block(SUPER_BLOCK, sb)
    bid = hashlib.sha256(img.data).digest()[:4]
    sb[SB_BUILD_ID:SB_BUILD_ID + 4] = bid if any(bid) else b"\x01\0\0\0"
    img.put_block(SUPER_BLOCK, sb)


class Image:
    def __init__(self, data=None, size=D64_SIZE):
        self.data = bytearray(data) if data is not None else bytearray(size)
        if len(self.data) not in (D64_SIZE, D81_SIZE):
            raise ValueError(f"not a .d64 or .d81 image: {len(self.data)} bytes")
        self.nblocks = len(self.data) // 256
        self.d81 = len(self.data) == D81_SIZE

    # the CBM DOS side's geometry
    def ts_block(self, t, s):
        return d81_block(t, s) if self.d81 else ts_to_block(t, s)

    def dir_track_blocks(self):
        if self.d81:
            return set(range(d81_block(D81_DIR_TRACK, 0), d81_block(D81_DIR_TRACK + 1, 0)))
        return set(range(TRACK_START[DIR_TRACK], TRACK_START[DIR_TRACK + 1]))

    def dir_first(self):
        return (D81_DIR_TRACK, 3) if self.d81 else (DIR_TRACK, 1)

    # raw blocks
    def block(self, b):
        return self.data[b * 256:(b + 1) * 256]

    def put_block(self, b, buf):
        assert len(buf) == 256
        self.data[b * 256:(b + 1) * 256] = buf

    # ---- CBM side ----
    def write_cbm(self, boot_name, boot_data, disk_name=b"BREADBIN", disk_id=b"BB", rev=None):
        used = set(range(TRACK_START[18], TRACK_START[19]))
        # boot file: sequential sectors from track 1
        chunks = [boot_data[i:i + 254] for i in range(0, len(boot_data), 254)] or [b""]
        blocks = list(range(len(chunks)))
        if blocks[-1] >= TRACK_START[18]:
            raise SystemExit("boot file too large")
        for i, (blk, chunk) in enumerate(zip(blocks, chunks)):
            buf = bytearray(256)
            if i + 1 < len(blocks):
                buf[0], buf[1] = block_to_ts(blocks[i + 1])
            else:
                buf[0], buf[1] = 0, len(chunk) + 1
            buf[2:2 + len(chunk)] = chunk
            self.put_block(blk, buf)
            used.add(blk)
        # BAM: every block allocated (c64fs owns the rest of the disk)
        bam = bytearray(256)
        bam[0], bam[1], bam[2] = 18, 1, 0x41
        for t in range(1, 36):
            bam[4 * t:4 * t + 4] = b"\x00\x00\x00\x00"
        name = disk_name.upper()[:16].ljust(16, b"\xa0")
        bam[0x90:0xa0] = name
        bam[0xa0:0xa2] = b"\xa0\xa0"
        bam[0xa2:0xa4] = disk_id[:2]
        bam[0xa4] = 0xa0
        bam[0xa5:0xa7] = b"2A"
        bam[0xa7:0xab] = b"\xa0" * 4
        self.put_block(ts_to_block(18, 0), bam)
        d = bytearray(256)
        d[0], d[1] = 0, 0xff
        d[2] = 0x82  # PRG, closed
        d[3], d[4] = block_to_ts(blocks[0])
        d[5:21] = boot_name.upper()[:16].ljust(16, b"\xa0")
        d[30] = len(blocks) & 0xff
        d[31] = len(blocks) >> 8
        if rev:
            # Build stamp: a closed, locked DEL entry (type $C0, lists as DEL<) with 0 blocks and no chain (t/s 0/0), so it
            # lists as 0 "BUILD <rev>" DEL and DOS VALIDATE has nothing to follow or free.
            e = d[32:64]
            e[2] = 0xC0
            e[5:21] = (b"BUILD " + rev.upper().encode("ascii"))[:16].ljust(16, b"\xa0")
            d[32:64] = e
        self.put_block(ts_to_block(18, 1), d)
        return used

    def write_cbm_d81(self, disk_name=b"BREADBIN", disk_id=b"BB"):
        """The 1581's own side of a c64fs volume: header, BAM and an empty directory on
        track 40, every block allocated, so the drive's DOS lists an empty, full disk and
        never writes. Returns the blocks c64fs must not use."""
        assert len(self.data) == D81_SIZE
        hdr = bytearray(256)
        hdr[0], hdr[1], hdr[2] = D81_DIR_TRACK, 3, 0x44      # first directory block; 'D'
        hdr[0x04:0x14] = disk_name.upper()[:16].ljust(16, b"\xa0")
        hdr[0x14:0x16] = b"\xa0\xa0"
        hdr[0x16:0x18] = disk_id[:2]
        hdr[0x18] = 0xa0
        hdr[0x19:0x1b] = b"3D"
        hdr[0x1b:0x1d] = b"\xa0\xa0"
        self.put_block(d81_block(D81_DIR_TRACK, 0), hdr)
        for sec, link in ((1, (D81_DIR_TRACK, 2)), (2, (0, 0xff))):
            bam = bytearray(256)                             # 6 bytes a track from $10, all 0: nothing free
            bam[0], bam[1] = link
            bam[2], bam[3] = 0x44, 0xbb
            bam[4:6] = disk_id[:2]
            bam[6] = 0xc0                                    # verify on, header CRC check on
            self.put_block(d81_block(D81_DIR_TRACK, sec), bam)
        d = bytearray(256)
        d[1] = 0xff
        self.put_block(d81_block(D81_DIR_TRACK, 3), d)
        return set(range(d81_block(D81_DIR_TRACK, 0), d81_block(D81_DIR_TRACK + 1, 0)))

    def cbm_files(self):
        out = []
        t, s = self.dir_first()
        while t:
            d = self.block(self.ts_block(t, s))
            for e in range(8):
                ent = d[e * 32:(e + 1) * 32]
                if ent[2] & 0x07:
                    out.append((bytes(ent[5:21]).rstrip(b"\xa0"), ent[2]))
            t, s = d[0], d[1]
        return out

    def cbm_entries(self):
        """Every used directory slot as (name, type byte), including the closed, locked DEL stamp (type 0xC0)."""
        out = []
        t, s = self.dir_first()
        while t:
            d = self.block(self.ts_block(t, s))
            for e in range(8):
                ent = d[e * 32:(e + 1) * 32]
                if ent[2]:
                    out.append((bytes(ent[5:21]).rstrip(b"\xa0"), ent[2]))
            t, s = d[0], d[1]
        return out

    def cbm_blocks(self):
        """Blocks the CBM side owns: its directory track and every CBM file's sectors."""
        used = self.dir_track_blocks()
        t, s = self.dir_first()
        while t:
            d = self.block(self.ts_block(t, s))
            for e in range(8):
                ent = d[e * 32:(e + 1) * 32]
                if ent[2] & 0x07:
                    ft, fs = ent[3], ent[4]
                    while ft and len(used) < self.nblocks:
                        b = self.ts_block(ft, fs)
                        used.add(b)
                        ft, fs = self.block(b)[0], self.block(b)[1]
            t, s = d[0], d[1]
        return used

    def cbm_read(self, name):
        t, s = self.dir_first()
        while t:
            d = self.block(self.ts_block(t, s))
            for e in range(8):
                ent = d[e * 32:(e + 1) * 32]
                if ent[2] & 0x07 and bytes(ent[5:21]).rstrip(b"\xa0") == name:
                    out = bytearray()
                    ft, fs = ent[3], ent[4]
                    while ft:
                        blk = self.block(self.ts_block(ft, fs))
                        if blk[0]:
                            out += blk[2:]
                        else:
                            out += blk[2:blk[1] + 1]
                        ft, fs = blk[0], blk[1]
                    return bytes(out)
            t, s = d[0], d[1]
        raise FileNotFoundError(name)


class FS:
    """c64fs on top of an Image: the format its superblock says (1 or 2; 2 if it has no
    c64fs yet). format() always writes format 2."""

    def __init__(self, img):
        self.img = img
        sb = img.block(SUPER_BLOCK)
        known = {lay.magic: v for v, lay in LAYOUTS.items()}
        found = known.get(bytes(sb[0:5]))
        self.lay = LAYOUTS[found or VERSION]
        if found:
            self.nblocks = sb[6] | sb[7] << 8
            self.bm_start = sb[9] | sb[10] << 8
            self.istart = sb[11] | sb[12] << 8
        else:                               # not formatted yet: from the geometry
            self.nblocks = img.nblocks
            self.bm_start = BITMAP_BLOCK
            self.istart = inode_start(self.nblocks)
        if found == 1:                      # format 1: one bitmap block, whatever the size
            self.nbm = 1
        else:
            self.nbm = self.istart - self.bm_start

    @property
    def version(self):
        return self.lay.version

    # ---- format ----
    def format(self, reserved):
        """A fresh format 2 c64fs over the whole image (upstream's layout)."""
        self.lay = LAYOUTS[VERSION]
        self.nblocks = self.img.nblocks
        self.bm_start = BITMAP_BLOCK
        self.istart = inode_start(self.nblocks)
        self.nbm = self.istart - self.bm_start
        lay = self.lay
        sb = bytearray(256)
        sb[0:5] = lay.magic
        sb[5] = lay.version
        sb[6], sb[7] = self.nblocks & 0xff, self.nblocks >> 8
        sb[8] = lay.ninodes
        sb[9], sb[10] = self.bm_start & 0xff, self.bm_start >> 8
        sb[11], sb[12] = self.istart & 0xff, self.istart >> 8
        sb[13] = lay.inode_blocks
        sb[14] = ROOT_INO
        self.img.put_block(SUPER_BLOCK, sb)             # last_time (15-18): 0
        for i in range(self.nbm):
            self.img.put_block(self.bm_start + i, bytearray(256))
        for i in range(lay.inode_blocks):
            self.img.put_block(self.istart + i, bytearray(256))
        for b in set(reserved) | set(range(SUPER_BLOCK, self.istart + lay.inode_blocks)):
            self.set_used(b, True)
        for b in range(self.nblocks, self.nbm * BM_BITS):   # bitmap bits past the end of the disk
            self.set_used(b, True)
        # inode 0 is never allocated
        ino0 = self.read_inode(0)
        ino0["type"] = 0xff
        self.write_inode(0, ino0)
        root = self.alloc_inode(T_DIR)
        assert root == ROOT_INO
        self.dir_add(root, b".", root)
        self.dir_add(root, b"..", root)
        r = self.read_inode(root)
        r["nlink"] = 2
        self.write_inode(root, r)

    # ---- bitmap: block b is bit b & 7 of byte (b >> 3) & 255 of bitmap block b >> 11 ----
    def is_used(self, b):
        bm = self.img.block(self.bm_start + (b >> 11))
        return bool(bm[(b >> 3) & 255] & (1 << (b & 7)))

    def set_used(self, b, used):
        blk = self.bm_start + (b >> 11)
        bm = self.img.block(blk)
        if used:
            bm[(b >> 3) & 255] |= 1 << (b & 7)
        else:
            bm[(b >> 3) & 255] &= ~(1 << (b & 7)) & 0xff
        self.img.put_block(blk, bm)

    # ---- placement (a 1541 image only: the head's travel and the revolution decide the latency) ----
    # Directory and indirect blocks are read on every lookup, so they sit in a zone next to the
    # inode table (the head is there anyway); file data fills outward from the same track, each
    # file's blocks one after another (stride 1, which the fast reader serves best).
    def plan_layout(self, host_root, extra=4):
        """Call after format(), before filling: set the centre-out order and reserve the meta zone
        for the directories (and indirect blocks) of the host tree at host_root, plus extra."""
        self.pref = self.meta = None
        if self.nblocks != NBLOCKS:
            return
        c = block_to_ts(self.istart)[0]
        self.pref = sorted(range(self.nblocks), key=lambda b: (abs(block_to_ts(b)[0] - c), b))
        need = extra
        for d, dirs, files in os.walk(host_root):
            dirs[:] = sorted(x for x in dirs if not x.startswith("."))
            names = [f for f in files if not f.startswith(".")]
            need += max(1, (2 + len(dirs) + len(names) + 15) // 16)
            for f in names:
                if os.path.getsize(os.path.join(d, f)) > NDIRECT * 256:
                    need += 1
        free = [b for b in self.pref if not self.is_used(b)]
        self.meta = free[:need]
        self.held = set(self.meta)
        r = self.read_inode(ROOT_INO)           # format() put the root directory wherever was free
        old = r["direct"][0]
        r["direct"][0] = self.alloc_block("meta")
        self.img.put_block(r["direct"][0], self.img.block(old))
        self.write_inode(ROOT_INO, r)
        self.set_used(old, False)

    def alloc_block(self, kind="data", after=0):
        pref = getattr(self, "pref", None)
        if pref is None:
            order = range(self.nblocks)
        elif kind == "meta" and self.meta:
            b = self.meta.pop(0)
            self.held.discard(b)
            self.set_used(b, True)
            self.img.put_block(b, bytearray(256))
            return b
        else:
            order = pref
            if after:                       # on: the next sector, else the nearest track to where the head is
                t = block_to_ts(after)[0]
                order = sorted(pref, key=lambda b: (abs(block_to_ts(b)[0] - t) if block_to_ts(b)[0] != t
                                                    else -1, b < after, b))
        held = getattr(self, "held", ())
        for b in order:
            if not self.is_used(b) and b not in held:
                self.set_used(b, True)
                self.img.put_block(b, bytearray(256))
                return b
        raise OSError("ENOSPC")

    def free_blocks(self):
        return sum(1 for b in range(self.nbm * BM_BITS) if not self.is_used(b))

    # ---- inodes (format 2: bytes 32-39 mtime and ctime, written 0; 40-63 reserved) ----
    def _inode_at(self, n):
        per = self.lay.per_block
        return self.istart + n // per, (n % per) * self.lay.inode_size

    def read_inode(self, n):
        b, off = self._inode_at(n)
        r = self.img.block(b)[off:off + self.lay.inode_size]
        return {
            "type": r[0], "nlink": r[1],
            "size": r[2] | r[3] << 8 | r[4] << 16, "major": r[5],
            "direct": [r[6 + 2 * i] | r[7 + 2 * i] << 8 for i in range(NDIRECT)],
            "indirect": r[30] | r[31] << 8,
        }

    def write_inode(self, n, ino):
        r = bytearray(self.lay.inode_size)
        r[0], r[1] = ino["type"], ino["nlink"]
        r[2], r[3], r[4] = ino["size"] & 0xff, ino["size"] >> 8 & 0xff, ino["size"] >> 16
        r[5] = ino["major"]
        for i, b in enumerate(ino["direct"]):
            r[6 + 2 * i], r[7 + 2 * i] = b & 0xff, b >> 8
        r[30], r[31] = ino["indirect"] & 0xff, ino["indirect"] >> 8
        b, off = self._inode_at(n)
        blk = self.img.block(b)
        blk[off:off + self.lay.inode_size] = r
        self.img.put_block(b, blk)

    def alloc_inode(self, typ, major=0):
        for n in range(1, self.lay.ninodes):
            if self.read_inode(n)["type"] == T_FREE:
                self.write_inode(n, {"type": typ, "nlink": 1, "size": 0,
                                     "major": major, "direct": [0] * NDIRECT,
                                     "indirect": 0})
                return n
        raise OSError("no inodes")

    def bmap(self, ino, i, alloc=False):
        """Block number of file block i (0 if a hole and not allocating)."""
        if i < NDIRECT:
            if not ino["direct"][i] and alloc:
                ino["direct"][i] = self.alloc_block(
                    "meta" if ino["type"] == T_DIR else "data", ino["direct"][i - 1] if i else 0)
            return ino["direct"][i]
        i -= NDIRECT
        if i >= 128:
            raise OSError("EFBIG")
        if not ino["indirect"]:
            if not alloc:
                return 0
            ino["indirect"] = self.alloc_block("meta")
        ind = self.img.block(ino["indirect"])
        b = ind[2 * i] | ind[2 * i + 1] << 8
        if not b and alloc:
            b = self.alloc_block("meta" if ino["type"] == T_DIR else "data",
                                 (ind[2 * i - 2] | ind[2 * i - 1] << 8) if i else ino["direct"][-1])
            ind[2 * i], ind[2 * i + 1] = b & 0xff, b >> 8
            self.img.put_block(ino["indirect"], ind)
        return b

    def read_file(self, n):
        ino = self.read_inode(n)
        out = bytearray()
        for i in range((ino["size"] + 255) // 256):
            b = self.bmap(ino, i)
            out += self.img.block(b) if b else bytes(256)
        return bytes(out[:ino["size"]])

    def write_file(self, n, data):
        ino = self.read_inode(n)
        for i in range(0, len(data), 256):
            b = self.bmap(ino, i // 256, alloc=True)
            self.img.put_block(b, bytearray(data[i:i + 256].ljust(256, b"\0")))
        ino["size"] = len(data)
        self.write_inode(n, ino)

    # ---- directories ----
    def dir_entries(self, n):
        data = self.read_file(n)
        for off in range(0, len(data), DIRENT_SIZE):
            e = data[off:off + DIRENT_SIZE]
            if e[0]:
                yield e[1:].split(b"\0")[0], e[0]

    def dir_add(self, d, name, child):
        if len(name) > NAME_MAX:
            raise OSError("ENAMETOOLONG")
        data = bytearray(self.read_file(d))
        ent = bytes([child]) + name.ljust(15, b"\0")
        for off in range(0, len(data), DIRENT_SIZE):
            if data[off] == 0:
                data[off:off + DIRENT_SIZE] = ent
                break
        else:
            data += ent
        self.write_file(d, bytes(data))

    def lookup(self, path):
        n = ROOT_INO
        for part in [p for p in path.encode().split(b"/") if p]:
            for name, ino in self.dir_entries(n):
                if name == part:
                    n = ino
                    break
            else:
                raise FileNotFoundError(path)
        return n

    def mkdir(self, parent, name):
        n = self.alloc_inode(T_DIR)
        self.dir_add(n, b".", n)
        self.dir_add(n, b"..", parent)
        ino = self.read_inode(n)
        ino["nlink"] = 2
        self.write_inode(n, ino)
        self.dir_add(parent, name, n)
        p = self.read_inode(parent)
        p["nlink"] += 1
        self.write_inode(parent, p)
        return n

    def create(self, parent, name, data, typ=T_FILE, major=0):
        n = self.alloc_inode(typ, major)
        if data:
            self.write_file(n, data)
        self.dir_add(parent, name, n)
        return n

    def add_tree(self, host_dir, ino):
        for entry in sorted(os.listdir(host_dir), key=lambda e: (HOT.index(e) if e in HOT else len(HOT), e)):
            if entry.startswith("."):
                continue
            p = os.path.join(host_dir, entry)
            name = entry.encode()
            if os.path.isdir(p):
                self.add_tree(p, self.mkdir(ino, name))
            else:
                with open(p, "rb") as f:
                    self.create(ino, name, f.read())

    def copy_tree(self, src, src_dir, dst_dir):
        """Copy a directory tree from another FS (upgrade)."""
        for name, n in src.dir_entries(src_dir):
            if name in (b".", b".."):
                continue
            i = src.read_inode(n)
            if i["type"] == T_DIR:
                self.copy_tree(src, n, self.mkdir(dst_dir, name))
            elif i["type"] == T_CHR:
                self.create(dst_dir, name, b"", T_CHR, i["major"])
            else:
                self.create(dst_dir, name, src.read_file(n))


# Loaded on every boot or most sessions: created first, so they sit nearest the inode table and
# early in their directory (a lookup reads it from the front).
HOT = ["init", "login", "sh", "fast", "cbm", "ls", "cat"]


def build(out, boot, root, devs, rev=None):
    img = Image()
    with open(boot, "rb") as f:
        boot_data = f.read()
    reserved = img.write_cbm(b"BREADBIN", boot_data, rev=rev)
    fs = FS(img)
    fs.format(reserved)
    fs.plan_layout(root)
    fs.add_tree(root, ROOT_INO)
    if rev:
        try:
            etc = fs.lookup("/etc")
        except FileNotFoundError:
            etc = fs.mkdir(ROOT_INO, b"etc")
        fs.create(etc, b"build", f"breadbin {rev}\n".encode("ascii"))
    if devs:
        try:
            dev = fs.lookup("/dev")
        except FileNotFoundError:
            dev = fs.mkdir(ROOT_INO, b"dev")
        for spec in devs:
            name, major = spec.split(":")
            fs.create(dev, name.encode(), b"", T_CHR, int(major))
    stamp_build_id(img)
    with open(out, "wb") as f:
        f.write(img.data)
    return img


def build_d81(out, root=None, name=b"BREADBIN"):
    """A c64fs volume on a .d81: no boot file, no build id (the REU block cache is the
    boot drive's). Block 0 is never a file block (0 is a hole in an inode)."""
    img = Image(size=D81_SIZE)
    reserved = img.write_cbm_d81(name)
    fs = FS(img)
    fs.format(reserved | {0})
    if root:
        fs.add_tree(root, ROOT_INO)
    with open(out, "wb") as f:
        f.write(img.data)
    return img


def upgrade(src_path, out, boot=None):
    """Rewrite a format 1 image (.d64 or .d81) as format 2 (after upstream's upgrade). The
    contents are kept; times are 0 (unknown). The CBM side (boot file, directory track) is
    copied as it is, unless boot gives a new kernel (.d64 only)."""
    old_img = load(src_path)
    old = FS(old_img)
    if bytes(old_img.block(SUPER_BLOCK)[0:5]) != LAYOUTS[1].magic:
        raise SystemExit(f"{src_path}: not a format 1 c64fs image")
    img = Image(size=len(old_img.data))
    if boot:
        if img.d81:
            raise SystemExit("--boot: a .d81 is not a boot disk here")
        with open(boot, "rb") as f:
            reserved = img.write_cbm(b"BREADBIN", f.read())
    else:
        reserved = old_img.cbm_blocks()
        for b in reserved:
            img.put_block(b, old_img.block(b))
    fs = FS(img)
    fs.format(reserved | {0})                 # block 0 is never a file block
    try:
        fs.copy_tree(old, ROOT_INO, ROOT_INO)
    except OSError as e:
        raise SystemExit(f"{src_path}: does not fit in format 2 ({e})")
    if not img.d81 and img.cbm_files():
        stamp_build_id(img)
    with open(out, "wb") as f:
        f.write(img.data)
    return img


REU_SIZE = 256 * 1024     # the smallest REU image VICE takes (-reusize 256); 4 banks


def reu_image(d64):
    """The disk image as an REU image: block b at REU offset b*256 (the layout the kernel
    uses for its REU root device), zero-padded to 256 KB."""
    assert len(d64) == D64_SIZE
    return bytes(d64) + bytes(REU_SIZE - len(d64))


def load(path):
    with open(path, "rb") as f:
        return Image(f.read())


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("out")
    b.add_argument("--boot", required=True)
    b.add_argument("--root", required=True)
    b.add_argument("--dev", action="append", default=[])
    b.add_argument("--rev", default=None, help="source revision stamped on the disk (directory entry and /etc/build)")
    d = sub.add_parser("d81", help="a c64fs volume for a 1581 (mount it; /lib/km/d81)")
    d.add_argument("out")
    d.add_argument("--root", default=None)
    d.add_argument("--name", default="BREADBIN")
    u = sub.add_parser("upgrade", help="a format 1 image as format 2")
    u.add_argument("src")
    u.add_argument("out")
    u.add_argument("--boot", default=None)
    r = sub.add_parser("reu")
    r.add_argument("img")
    r.add_argument("out")
    l = sub.add_parser("ls")
    l.add_argument("img")
    l.add_argument("path", nargs="?", default="/")
    c = sub.add_parser("cat")
    c.add_argument("img")
    c.add_argument("path")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        img = build(a.out, a.boot, a.root, a.dev, a.rev)
        print(f"{a.out}: {FS(img).free_blocks()} blocks free")
    elif a.cmd == "d81":
        img = build_d81(a.out, a.root, a.name.encode("ascii"))
        print(f"{a.out}: {FS(img).free_blocks()} blocks free of {D81_BLOCKS}")
    elif a.cmd == "upgrade":
        img = upgrade(a.src, a.out, a.boot)
        print(f"{a.out}: format 2, {FS(img).free_blocks()} blocks free")
        if not a.boot and img.cbm_files():
            print("WARNING: no --boot given: the old boot file (a format 1 kernel) was copied "
                  "as it is, and it cannot read this format 2 disk: the result will NOT BOOT. "
                  "Pass --boot with a format 2 kernel (build/breadbin.prg).", file=sys.stderr)
    elif a.cmd == "reu":
        with open(a.out, "wb") as f:
            f.write(reu_image(load(a.img).data))
        print(f"{a.out}: {REU_SIZE} bytes, superblock at offset {SUPER_BLOCK * 256:#x}")
    elif a.cmd == "ls":
        fs = FS(load(a.img))
        for name, ino in fs.dir_entries(fs.lookup(a.path)):
            i = fs.read_inode(ino)
            t = {T_FILE: "-", T_DIR: "d", T_CHR: "c"}.get(i["type"], "?")
            print(f"{t} {ino:3} {i['size']:6} {name.decode()}")
    elif a.cmd == "cat":
        fs = FS(load(a.img))
        sys.stdout.buffer.write(fs.read_file(fs.lookup(a.path)))


if __name__ == "__main__":
    main()
