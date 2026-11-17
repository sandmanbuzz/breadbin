"""d81.km against fake drives: the real kernel image in py65 (tools/uci_sim.py), the real module.

The boot drive is served a block at a time, as in the other simulator tests. Drives 9-11
are fakes one level lower, at the kernel's byte primitives (iec_ch_open, iec_out_*,
iec_in_*): they take the DOS commands the kernel sends ("U1", "U2", "B-P" on a "#"
channel), check track and sector against their geometry and answer 66 for an illegal
pair, as a drive does. So the kernel's own open, block read, block write and mount run,
and with them the four call sites the module repoints. What this does not show is a real
1581's DOS or the bus timing: see tests/d81_vice.py.

Skips when py65 is not installed or the kernel has not been built (`make`). See docs/testing.md.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkimage
try:
    import uci_sim
    from uci_sim import Sim
except ImportError:                         # py65 missing
    uci_sim = None
    Sim = object

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")
BUILT = all(os.path.exists(os.path.join(BUILD, f))
            for f in ("breadbin.prg", "kernel.lbl", "breadbin.d64", "root/lib/km/d81"))
SKIP = "py65 not installed" if uci_sim is None else ("kernel not built (make)" if not BUILT else None)

O_RDONLY, O_WRONLY, O_CREAT = 0, 1, 0x10
ST = 0x90
SITES = (("ts_rd_io", "blk_to_ts"), ("ts_wr_io", "blk_to_ts"), ("open_mnt_io", "iec_open"), ("open_dio_io", "iec_open"))


def pattern(n, seed):
    return bytes((i * 7 + (i >> 8) * 13 + seed) & 0xFF for i in range(n))


class Drive:
    """A disk drive as far as the block commands go. kind: "1541" or "1581"."""

    def __init__(self, kind, image):
        self.kind, self.image = kind, bytearray(image)
        self.buf = bytearray(256)
        self.status = b"00, OK,00,00"
        self.log = []                       # every command, as text
        self.writes = []                    # (track, sector) of every U2 that was carried out

    def offset(self, t, s):
        """Image offset of a track and sector, or None when the drive has no such block."""
        if self.kind == "1581":
            return ((t - 1) * 40 + s) * 256 if 1 <= t <= 80 and 0 <= s < 40 else None
        if 1 <= t <= 35 and 0 <= s < mkimage.sectors_per_track(t):
            return mkimage.ts_to_block(t, s) * 256
        return None

    def command(self, cmd):
        text = cmd.decode("latin1")
        self.log.append(text)
        self.status = b"00, OK,00,00"
        if text[:2] in ("U1", "U2"):
            ch, drv, t, s = (int(v) for v in text[3:].split())
            assert (ch, drv) == (2, 0), text
            off = self.offset(t, s)
            if off is None:
                self.status = b"66,ILLEGAL TRACK OR SECTOR,%02d,%02d" % (t, s)
            elif text[1] == "1":
                self.buf[:] = self.image[off:off + 256]
            else:
                self.image[off:off + 256] = self.buf
                self.writes.append((t, s))
        elif text[:3] == "B-P":
            assert text == "B-P:2 0", text
        elif text[:3] == "N0:":
            self.new_disk()
        else:
            raise AssertionError("unexpected command %r" % text)


    def new_disk(self):
        """N0: a blank disk with the DOS's header and a BAM with every block free (as far as
        format cares: the CBM side must end up all allocated)."""
        self.image[:] = bytes(len(self.image))
        if self.kind == "1581":
            o = mkimage.d81_block(40, 0) * 256
            self.image[o:o + 4] = bytes([40, 3, ord("D"), 0])
            for sec in (1, 2):
                o = mkimage.d81_block(40, sec) * 256
                self.image[o:o + 16] = bytes([40, 2, ord("D"), 0xBB, 0x42, 0x42, 0xC0]) + bytes(9)
                self.image[o + 16:o + 256] = bytes([40, 255, 255, 255, 255, 255]) * 40
        else:
            o = mkimage.ts_to_block(18, 0) * 256
            self.image[o:o + 4] = bytes([18, 1, ord("A"), 0])
            for t in range(35):
                self.image[o + 4 + 4 * t:o + 8 + 4 * t] = bytes([17, 255, 255, 1])


class BusSim(Sim):
    """Sim with drives on IEC devices 9-11: {9: Drive, ...}."""

    def __init__(self, drives):
        super().__init__()
        self.drives = drives
        L, h = self.lbl, self.hooks
        blk = {"iec_open": self._ok, "iec_close": self._ok}
        for name, serve in blk.items():
            h[L[name]] = lambda serve=serve: serve() if self.mpu.x == 0 else self.mpu.step()
        for name, serve in (("iec_read", self._rd), ("iec_write", self._wr)):
            h[L[name]] = lambda serve=serve: serve() if self.mem.b[L["rq_dev"]] == 0 else self.mpu.step()
        for name in ("ch_open", "ch_close", "out_begin", "out_byte", "out_end", "in_begin", "in_byte", "in_end"):
            h[L["iec_" + name]] = getattr(self, "_" + name)
        self.cur, self.sa, self.out, self.inq = None, 0, bytearray(), b""

    def _to(self):
        """A = IEC device, X = secondary address: the drive, or None (carry set, ENODEV)."""
        self.cur, self.sa = self.drives.get(self.mpu.a), self.mpu.x
        self.mem.b[ST] = 0
        if self.cur is None:
            self.mpu.a = 19
            self._rts(carry=True)
            return False
        return True

    def _ch_open(self):
        if self._to():
            self._rts()

    def _ch_close(self):
        self._rts()

    def _out_begin(self):
        if self._to():
            self.out = bytearray()
            self._rts()

    def _out_byte(self):
        self.out.append(self.mpu.a)
        self._rts()

    def _out_end(self):
        if self.sa == 15:
            self.cur.command(bytes(self.out))
        else:
            assert self.sa == 2 and len(self.out) == 256, (self.sa, len(self.out))
            self.cur.buf[:] = self.out
        self._rts()

    def _in_begin(self):
        if self._to():
            if self.sa == 15:
                self.inq = self.cur.status + b"\r"
                self.cur.status = b"00, OK,00,00"
            else:
                self.inq = bytes(self.cur.buf)
            self._rts()

    def _in_byte(self):
        if self.inq:
            self.mpu.a, self.inq = self.inq[0], self.inq[1:]
            self.mem.b[ST] = 0 if self.inq else 0x40
        else:
            self.mpu.a = 0x0D
            self.mem.b[ST] = 0x42
        self._rts()

    def _in_end(self):
        self._rts()

    # ---- what the tests ask for
    def mod_load(self, name="d81"):
        return self.sys("CACHE", a=4, r0=self.cstr("/lib/km/" + name))

    def mount(self, drive, path="/mnt"):
        return self.sys("MOUNT", a=drive, r0=self.cstr(path), limit=20_000_000)

    def umount(self, path="/mnt"):
        return self.sys("UMOUNT", r0=self.cstr(path), limit=20_000_000)

    def cat(self, path):
        fd = self.check(self.open(path), "open " + path)
        data = self.read_all(fd)
        self.close(fd)
        return data

    def store(self, path, data):
        fd = self.check(self.open(path, O_WRONLY | O_CREAT), "create " + path)
        for i in range(0, len(data), 1000):
            n = self.write(fd, data[i:i + 1000])
            assert n == len(data[i:i + 1000]), (n, i)
        self.close(fd)

    def site(self, name):
        a = self.lbl[name]
        assert self.mem.b[a] == 0x20, name
        return self.mem.b[a + 1] | self.mem.b[a + 2] << 8

    def diskio_read(self, drive, block):
        self.check(self.sys("DISKIO", a=drive, x=2, r0=0x8200, r1=block), "diskio read %d" % block)
        return bytes(self.mem.b[0x8200:0x8300])


def volume(root_files, fill=0):
    """A .d81 c64fs volume with these files in /, and `fill` more blocks taken by files /fNN."""
    d = tempfile.mkdtemp(prefix="d81sim")
    try:
        for name, data in root_files.items():
            with open(os.path.join(d, name), "wb") as f:
                f.write(data)
        n = 0
        while fill > 0:
            take = min(fill, 141) - 1               # 140 data blocks and the indirect block at most
            if take < 13:
                break
            with open(os.path.join(d, "f%02d" % n), "wb") as f:
                f.write(pattern(take * 256, n))
            fill -= take + 1
            n += 1
        img = mkimage.Image(size=mkimage.D81_SIZE)
        reserved = img.write_cbm_d81()
        fs = mkimage.FS(img)
        fs.format(reserved | {0})
        fs.add_tree(d, mkimage.ROOT_INO)
        return bytes(img.data)
    finally:
        shutil.rmtree(d)


def numbered(nblocks):
    """An image whose every block says which block it is."""
    return b"".join(bytes([b & 0xFF, b >> 8]) * 128 for b in range(nblocks))


@unittest.skipIf(SKIP, SKIP)
class Sites(unittest.TestCase):
    def test_sites_are_calls_to_the_kernels_own_routines(self):
        s = BusSim({})
        for site, target in SITES:
            self.assertEqual(s.site(site), s.lbl[target], site)

    def test_load_points_the_sites_at_the_module_and_unload_puts_them_back(self):
        s = BusSim({})
        free = s.free()
        slot = s.check(s.mod_load(), "load")
        (base, pages), = s.modules()
        self.assertEqual(pages, 1)
        for site, target in SITES:
            self.assertEqual(s.site(site) >> 8, base, site)
        self.assertEqual(s.site("ts_rd_io"), s.site("ts_wr_io"))
        self.assertEqual(s.site("open_mnt_io"), s.site("open_dio_io"))
        self.assertEqual(s.errno(s.mod_load()), "ENODEV")           # a second copy: init refuses (mod_load says ENODEV)
        self.assertEqual(len(s.modules()), 1)
        for site, target in SITES:
            self.assertEqual(s.site(site) >> 8, base, site)
        s.check(s.sys("CACHE", a=5, x=slot), "unload")
        for site, target in SITES:
            self.assertEqual(s.site(site), s.lbl[target], site)
        self.assertEqual(s.modules(), [])
        self.assertEqual(s.free(), free)

    def test_boot_drive_files_with_the_module_loaded(self):
        s = BusSim({})
        with open(os.path.join(BUILD, "root", "bin", "sh"), "rb") as f:
            sh = f.read()
        s.check(s.mod_load(), "load")
        self.assertEqual(s.cat("/bin/sh"), sh)
        s.store("/tmp/x", pattern(3000, 1))
        self.assertEqual(s.cat("/tmp/x"), pattern(3000, 1))


@unittest.skipIf(SKIP, SKIP)
class Mapping(unittest.TestCase):
    """Raw blocks through diskio(): the block number the kernel asks for against the image."""

    def test_every_tenth_block_and_the_edges_of_a_1581(self):
        img = numbered(mkimage.D81_BLOCKS)
        s = BusSim({9: Drive("1581", img)})
        s.check(s.mod_load(), "load")
        blocks = sorted(set(range(0, 3200, 10)) | {1, 39, 40, 41, 79, 80, 255, 256, 257, 295, 296, 1559, 1560,
                                                   1599, 1600, 2047, 2048, 3159, 3160, 3199})
        for b in blocks:
            self.assertEqual(s.diskio_read(9, b), img[b * 256:b * 256 + 256], b)
        log = s.drives[9].log
        self.assertEqual(log[:3], ["U1:2 0 1 39", "U1:2 0 1 40", "U1:2 0 1 0"])
        self.assertEqual(log[-1], "U1:2 0 80 39")

    def test_block_past_the_disk_is_an_error(self):
        s = BusSim({9: Drive("1581", numbered(mkimage.D81_BLOCKS))})
        s.check(s.mod_load(), "load")
        self.assertEqual(s.errno(s.sys("DISKIO", a=9, x=2, r0=0x8200, r1=3200)), "EIO")
        self.assertEqual(s.drives[9].log[-1], "U1:2 0 81 0")
        self.assertEqual(s.errno(s.sys("DISKIO", a=9, x=2, r0=0x8200, r1=0xFFFF)), "EIO")
        self.assertEqual(s.drives[9].writes, [])

    def test_a_1541_keeps_the_kernels_mapping(self):
        img = numbered(mkimage.NBLOCKS)
        s = BusSim({10: Drive("1541", img)})
        s.check(s.mod_load(), "load")
        for b in (0, 20, 21, 356, 357, 376, 682):
            self.assertEqual(s.diskio_read(10, b), img[b * 256:b * 256 + 256], b)
        log = s.drives[10].log
        self.assertEqual(log[:2], ["U1:2 0 1 39", "U1:2 0 1 0"])        # one question, refused; then the read
        self.assertNotIn("U1:2 0 1 40", log)
        self.assertEqual(log[-1], "U1:2 0 35 16")

    def test_write_goes_to_the_same_block(self):
        img = numbered(mkimage.D81_BLOCKS)
        s = BusSim({9: Drive("1581", img)})
        s.check(s.mod_load(), "load")
        for b in (41, 1600, 3199):
            s.put(0x8200, pattern(256, b))
            s.check(s.sys("DISKIO", a=9, x=1, r0=0x8200, r1=b), "diskio write")
            self.assertEqual(bytes(s.drives[9].image[b * 256:b * 256 + 256]), pattern(256, b))
        self.assertEqual(s.drives[9].writes, [(2, 1), (41, 0), (80, 39)])
        rest = bytearray(s.drives[9].image)
        for b in (41, 1600, 3199):
            rest[b * 256:b * 256 + 256] = img[b * 256:b * 256 + 256]
        self.assertEqual(bytes(rest), img)

    def test_without_the_module_a_1581_gets_the_1541_mapping(self):
        s = BusSim({9: Drive("1581", numbered(mkimage.D81_BLOCKS))})
        s.diskio_read(9, 376)
        self.assertEqual(s.drives[9].log, ["U1:2 0 19 0"])


@unittest.skipIf(SKIP, SKIP)
class Mounted(unittest.TestCase):
    FILES = {"small": b"hello from a 1581\n", "big": pattern(20000, 5)}

    def test_no_module_no_mount_and_nothing_written(self):
        img = volume(self.FILES)
        s = BusSim({9: Drive("1581", img)})
        self.assertIsNotNone(s.errno(s.mount(9)))
        self.assertEqual(s.drives[9].writes, [])
        self.assertEqual(bytes(s.drives[9].image), img)

    def test_read_files(self):
        s = BusSim({9: Drive("1581", volume(self.FILES))})
        s.check(s.mod_load(), "load")
        s.check(s.mount(9), "mount")
        self.assertIn("U1:2 0 10 16", s.drives[9].log)              # the superblock: block 376
        for name, data in self.FILES.items():
            self.assertEqual(s.cat("/mnt/" + name), data, name)
        self.assertEqual(s.drives[9].writes, [])

    def test_write_files_and_read_them_on_the_host(self):
        s = BusSim({9: Drive("1581", volume(self.FILES))})
        s.check(s.mod_load(), "load")
        s.check(s.mount(9), "mount")
        new = pattern(30000, 9)
        s.store("/mnt/new", new)
        s.check(s.path_call("MKDIR", "/mnt/d"), "mkdir")
        s.store("/mnt/d/inner", b"inside\n")
        self.assertEqual(s.cat("/mnt/new"), new)
        s.check(s.umount(), "umount")
        fs = mkimage.FS(mkimage.Image(s.drives[9].image))
        self.assertEqual((fs.nblocks, fs.nbm, fs.istart), (3200, 2, 379))
        self.assertEqual(fs.read_file(fs.lookup("/new")), new)
        self.assertEqual(fs.read_file(fs.lookup("/d/inner")), b"inside\n")
        for name, data in self.FILES.items():
            self.assertEqual(fs.read_file(fs.lookup("/" + name)), data, name)

    def test_files_grow_around_track_40(self):
        img = volume({}, fill=1500)
        before = mkimage.FS(mkimage.Image(img))
        first = min(b for b in range(3200) if not before.is_used(b))
        self.assertLess(first, 1560)
        self.assertGreater(first, 1500)
        s = BusSim({9: Drive("1581", img)})
        s.check(s.mod_load(), "load")
        s.check(s.mount(9), "mount")
        new = pattern(60 * 256, 3)
        s.store("/mnt/across", new)
        self.assertEqual(s.cat("/mnt/across"), new)
        s.check(s.umount(), "umount")
        out = bytes(s.drives[9].image)
        fs = mkimage.FS(mkimage.Image(out))
        self.assertEqual(fs.read_file(fs.lookup("/across")), new)
        ino = fs.read_inode(fs.lookup("/across"))
        used = [fs.bmap(ino, i) for i in range(60)]
        self.assertTrue(any(b < 1560 for b in used) and any(b >= 1600 for b in used), used)
        self.assertFalse(any(1560 <= b < 1600 for b in used), used)
        self.assertEqual(out[1560 * 256:1600 * 256], img[1560 * 256:1600 * 256])     # the 1581's own track
        self.assertIn((41, 0), s.drives[9].writes)
        self.assertFalse(any(t == 40 for t, _ in s.drives[9].writes), s.drives[9].writes)

    def test_full_volume_is_enospc_not_a_write_past_it(self):
        """Format 2: 3200 blocks, two bitmap blocks. The volume is full up to past block 2048,
        so every block the kernel finds is in the second bitmap block (378); up to 3199, then
        ENOSPC."""
        img = volume({}, fill=2900)
        before = mkimage.FS(mkimage.Image(img))
        self.assertGreater(min(b for b in range(3200) if not before.is_used(b)), 2048)
        s = BusSim({9: Drive("1581", img)})
        s.check(s.mod_load(), "load")
        s.check(s.mount(9), "mount")
        free = mkimage.FS(mkimage.Image(img)).free_blocks()
        got = 0
        for n in range(8):                                  # 8 files of 140 blocks: more than is free
            fd = s.check(s.open("/mnt/g%d" % n, O_WRONLY | O_CREAT), "create")
            s.put(0x8100, pattern(1024, n))
            full = False
            for _ in range(35):
                res = s.sys("WRITE", a=fd, r0=0x8100, r1=1024)
                if res[0]:
                    self.assertEqual(s.errno(res), "ENOSPC")
                    full = True
                    break
                got += s.r1()
                if s.r1() < 1024:
                    full = True
                    break
            s.close(fd)
            if full:
                break
        self.assertTrue(full)
        self.assertGreater(got, (free - 12) * 256 - 1024)
        s.check(s.umount(), "umount")
        out = bytes(s.drives[9].image)
        self.assertEqual(out[1560 * 256:1600 * 256], img[1560 * 256:1600 * 256])
        self.assertFalse(any(t == 40 or t > 80 or sec > 39 for t, sec in s.drives[9].writes))
        after = mkimage.FS(mkimage.Image(out))
        self.assertEqual(after.free_blocks(), 0)
        self.assertIn((80, 39), s.drives[9].writes)                 # block 3199: the last one
        self.assertIn((10, 18), s.drives[9].writes)                 # bitmap block 378 (the second)

    def test_1541_volume_beside_a_1581_volume(self):
        with open(os.path.join(BUILD, "breadbin.d64"), "rb") as f:
            d64 = f.read()
        with open(os.path.join(BUILD, "root", "bin", "sh"), "rb") as f:
            sh = f.read()
        s = BusSim({9: Drive("1581", volume(self.FILES)), 10: Drive("1541", d64)})
        s.check(s.mod_load(), "load")
        s.check(s.path_call("MKDIR", "/tmp/m"), "mkdir")
        s.check(s.mount(9), "mount 9")
        s.check(s.mount(10, "/tmp/m"), "mount 10")
        self.assertIn("U1:2 0 19 0", s.drives[10].log)              # block 376 on a 1541
        self.assertEqual(s.cat("/tmp/m/bin/sh"), sh)
        self.assertEqual(s.cat("/mnt/big"), self.FILES["big"])
        s.store("/tmp/m/tmp/y", pattern(5000, 2))
        s.store("/mnt/y", pattern(5000, 4))
        s.check(s.umount("/tmp/m"), "umount 10")
        s.check(s.umount(), "umount 9")
        fs = mkimage.FS(mkimage.Image(s.drives[10].image))
        self.assertEqual(fs.read_file(fs.lookup("/tmp/y")), pattern(5000, 2))
        fs = mkimage.FS(mkimage.Image(s.drives[9].image))
        self.assertEqual(fs.read_file(fs.lookup("/y")), pattern(5000, 4))

    def test_unload_is_refused_while_mounted(self):
        s = BusSim({9: Drive("1581", volume(self.FILES)), 10: Drive("1541", numbered(mkimage.NBLOCKS))})
        slot = s.check(s.mod_load(), "load")
        s.check(s.mount(9), "mount")
        self.assertEqual(s.errno(s.sys("CACHE", a=5, x=slot)), "EBUSY")
        self.assertEqual(s.cat("/mnt/small"), self.FILES["small"])
        s.check(s.umount(), "umount")
        s.check(s.sys("CACHE", a=5, x=slot), "unload")
        for site, target in SITES:
            self.assertEqual(s.site(site), s.lbl[target], site)
        self.assertIsNotNone(s.errno(s.mount(9)))                   # and the volume is a stranger again
        self.assertEqual(s.drives[9].writes, [])

    def test_swapped_drive_is_asked_again(self):
        """The same device, first a 1581 volume, then a 1541 one: the answer is not remembered."""
        with open(os.path.join(BUILD, "breadbin.d64"), "rb") as f:
            d64 = f.read()
        s = BusSim({9: Drive("1581", volume(self.FILES))})
        s.check(s.mod_load(), "load")
        s.check(s.mount(9), "mount")
        s.check(s.umount(), "umount")
        s.drives[9] = Drive("1541", d64)
        s.check(s.mount(9), "mount the 1541")
        self.assertEqual(s.cat("/mnt/etc/motd"), mkimage.FS(mkimage.Image(d64)).read_file(
            mkimage.FS(mkimage.Image(d64)).lookup("/etc/motd")))
        s.check(s.umount(), "umount")

    def test_absent_drive(self):
        s = BusSim({})
        s.check(s.mod_load(), "load")
        self.assertEqual(s.errno(s.mount(9)), "ENODEV")



@unittest.skipIf(SKIP, SKIP)
class Format2(unittest.TestCase):
    """c64fs format 2 (upstream's) on a 1541 in drive 10, no module: the version check, and
    inode bytes 32-63 (upstream's times), which iput writes as zero."""

    def d64(self, patch=None):
        with open(os.path.join(BUILD, "breadbin.d64"), "rb") as f:
            img = bytearray(f.read())
        if patch:
            patch(img)
        return img

    @staticmethod
    def ino_raw(img, n):
        off = (378 + n // 4) * 256 + (n % 4) * 64
        return bytes(img[off:off + 64])

    def test_times_kept_where_untouched_zero_where_changed(self):
        img = self.d64()
        fs = mkimage.FS(mkimage.Image(img))
        motd, tmp = fs.lookup("/etc/motd"), fs.lookup("/tmp")
        for n in (motd, tmp):
            off = (378 + n // 4) * 256 + (n % 4) * 64
            img[off + 32:off + 64] = bytes(range(1, 33))          # as if upstream had set times
        s = BusSim({10: Drive("1541", img)})
        s.check(s.mount(10), "mount")
        self.assertEqual(s.cat("/mnt/etc/motd"), fs.read_file(motd))
        s.store("/mnt/tmp/y", pattern(600, 1))
        s.check(s.umount(), "umount")
        out = bytes(s.drives[10].image)
        fs2 = mkimage.FS(mkimage.Image(out))
        y = fs2.lookup("/tmp/y")
        self.assertEqual(fs2.read_file(y), pattern(600, 1))
        self.assertEqual(self.ino_raw(out, motd)[32:], bytes(range(1, 33)))   # read only: kept
        self.assertEqual(self.ino_raw(out, tmp)[32:], bytes(32))             # changed: 0, unknown
        self.assertEqual(self.ino_raw(out, y)[32:], bytes(32))

    def _not_c64fs(self, patch):
        s = BusSim({10: Drive("1541", self.d64(patch))})
        s.mount(10)                         # a CBM DOS disk now (its BAM), or no mount at all
        self.assertIsNotNone(s.errno(s.open("/mnt/etc/motd")))
        self.assertEqual(s.drives[10].writes, [])

    def test_format_1_is_not_mounted_as_c64fs(self):
        def v1(img):
            img[376 * 256:376 * 256 + 6] = b"C64FS\x01"
        self._not_c64fs(v1)

    def test_other_version_is_not_mounted(self):
        def v3(img):
            img[376 * 256 + 5] = 3
        self._not_c64fs(v3)



@unittest.skipIf(SKIP, SKIP)
class FormatSim(unittest.TestCase):
    """/bin/format run in the sim on a fake 1541 and a fake 1581 (with /lib/km/d81): it must write
    format 2 with the drive's geometry, and the result must read in mkimage and mount and take a
    file in the kernel. Console reads and writes are answered at the syscall entries."""

    def run_format(self, s, drive, kind="c64fs"):
        m, L = s.mem.b, s.lbl
        for i in range(2):                                   # the caller's own image (as test_exec_sim)
            m[L["pg_used"] + 0x20 - 8 + i] = 1
        m[L["free_pages"]] -= 2
        m[L["p_mpage"]], m[L["p_mlen"]] = 0x20, 2
        args, a, ptrs = [b"format", b"%d" % drive, kind.encode(), b"vol"], 0x8440, []
        for t in args:
            s.put(a, t + b"\0")
            ptrs.append(a)
            a += len(t) + 1
        for i, p in enumerate(ptrs + [0]):
            m[0x8400 + 2 * i], m[0x8401 + 2 * i] = p & 0xFF, p >> 8
        out, DONE = bytearray(), 0xFFF0

        def sys_read():
            r0 = m[2] | m[3] << 8
            m[r0:r0 + 2] = b"y\n"
            m[4], m[5] = 2, 0
            s._rts()

        def sys_write():
            r0, n = m[2] | m[3] << 8, m[4] | m[5] << 8
            out.extend(m[r0:r0 + n])
            s._rts()

        def sys_exit():
            self.status = s.mpu.a
            s.mpu.pc = DONE

        hooks = {s.sysno["READ"]: sys_read, s.sysno["WRITE"]: sys_write, s.sysno["EXIT"]: sys_exit}
        s.hooks.update(hooks)
        r0 = s.cstr("/bin/format")
        m[2], m[3], m[4], m[5] = r0 & 0xFF, r0 >> 8, 0x00, 0x84
        addr = s.sysno["SPAWN"]
        m[s.TRAMP:s.TRAMP + 3] = bytes([0x20, addr & 0xFF, addr >> 8])
        s.mpu.pc, s.mpu.sp, s.mpu.a, s.mpu.x, s.mpu.y = s.TRAMP, 0xFF, 0, 1, 0x80   # SP_EXEC
        s.run(DONE, 200_000_000)
        for h in hooks:
            del s.hooks[h]
        return bytes(out)

    def check_volume(self, img, nblocks, istart, reserved):
        fs = mkimage.FS(mkimage.Image(img))
        sb = img[376 * 256:377 * 256]
        self.assertEqual(bytes(sb[:6]), b"C64F2\x02")
        self.assertEqual(sb[13], 32)
        self.assertEqual(bytes(sb[15:]), bytes(241))                 # no times, no build id
        self.assertEqual((fs.nblocks, fs.bm_start, fs.istart), (nblocks, 377, istart))
        self.assertEqual(sorted(name for name, _ in fs.dir_entries(1)), [b".", b".."])
        used = {b for b in range(nblocks) if fs.is_used(b)}
        self.assertEqual(used, reserved | {1})                      # 1: the root directory
        for b in range(nblocks, (istart - 377) * 2048):
            self.assertTrue(fs.is_used(b), b)
        ino0 = img[istart * 256:istart * 256 + 64]
        self.assertEqual(ino0[0], 0xFF)
        root = bytes(img[istart * 256 + 64:istart * 256 + 128])
        self.assertEqual(root[:8], bytes([2, 2, 32, 0, 0, 0, 1, 0]))
        self.assertEqual(root[8:], bytes(56))
        return fs

    def test_format_a_1541(self):
        s = BusSim({9: Drive("1541", bytes(683 * 256))})
        out = self.run_format(s, 9)
        self.assertEqual(self.status, 0, out)
        self.assertIn(b"done", out)
        d = s.drives[9]
        self.assertIn("N0:VOL,BB", d.log)
        self.assertIn("U1:2 0 35 54", d.log)                     # block 720 in the 1541 numbering
        self.assertIn("U1:2 0 35 34", d.log)                     # block 700: not a 1581 either
        self.assertTrue(all(c[:2] != "U1" or int(c.split()[-1]) < 100 for c in d.log), d.log)
        img = bytes(d.image)
        o = 357 * 256
        self.assertEqual(img[o + 4:o + 144], bytes(140))           # the CBM BAM: nothing free
        self.check_volume(img, 683, 378, {0} | set(range(357, 410)))
        s.check(s.mount(9), "mount")
        s.store("/mnt/f", pattern(3000, 7))
        s.check(s.umount(), "umount")
        fs = mkimage.FS(mkimage.Image(bytes(d.image)))
        self.assertEqual(fs.read_file(fs.lookup("/f")), pattern(3000, 7))

    def test_format_a_1581_with_the_module(self):
        s = BusSim({9: Drive("1581", bytes(3200 * 256))})
        s.check(s.mod_load(), "mod load")
        out = self.run_format(s, 9)
        self.assertEqual(self.status, 0, out)
        d = s.drives[9]
        img = bytes(d.image)
        for sec in (1, 2):                                          # the 1581 BAM: nothing free
            o = mkimage.d81_block(40, sec) * 256
            self.assertEqual(img[o + 16:o + 256], bytes(240))
            self.assertEqual(img[o:o + 3], bytes([40, 2, ord("D")]))
        self.assertEqual(img[mkimage.d81_block(40, 0) * 256 + 2], ord("D"))
        self.check_volume(img, 3200, 379, {0} | set(range(376, 411)) | set(range(1560, 1600)))
        s.check(s.mount(9), "mount")
        s.store("/mnt/f", pattern(30000, 8))
        s.check(s.umount(), "umount")
        fs = mkimage.FS(mkimage.Image(bytes(d.image)))
        self.assertEqual(fs.read_file(fs.lookup("/f")), pattern(30000, 8))
        self.assertTrue(all(t != 40 for t, _ in d.writes[-120:]))

    def test_a_1581_without_the_module_is_refused(self):
        s = BusSim({9: Drive("1581", bytes(3200 * 256))})
        out = self.run_format(s, 9)
        self.assertEqual(self.status, 1)
        self.assertIn(b"mod load /lib/km/d81", out)
        self.assertEqual(s.drives[9].writes, [])                   # the DOS format only


if __name__ == "__main__":
    unittest.main()
