import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import mkimage as M  # noqa: E402
import cx  # noqa: E402


def make_tree(root):
    os.makedirs(os.path.join(root, "bin"))
    os.makedirs(os.path.join(root, "home"))
    os.makedirs(os.path.join(root, "tmp"))
    with open(os.path.join(root, "home", "readme"), "wb") as f:
        f.write(b"hello unix\n" * 100)   # 1100 bytes, 5 blocks
    with open(os.path.join(root, "bin", "big"), "wb") as f:
        f.write(bytes(range(256)) * 20)  # 5120 bytes, uses indirect block


class TestImage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        make_tree(os.path.join(t, "root"))
        self.boot = bytes(range(256)) * 10 + b"end"
        with open(os.path.join(t, "boot.prg"), "wb") as f:
            f.write(self.boot)
        self.out = os.path.join(t, "x.d64")
        M.build(self.out, os.path.join(t, "boot.prg"), os.path.join(t, "root"),
                ["console:1", "null:0"])
        self.img = M.load(self.out)
        self.fs = M.FS(self.img)

    def tearDown(self):
        self.tmp.cleanup()

    def test_size(self):
        self.assertEqual(os.path.getsize(self.out), 174848)

    def test_reu_image(self):
        """The REU root layout: block b at offset b*256, padded to 256 KB."""
        out = os.path.join(self.tmp.name, "x.reu")
        M.main(["reu", self.out, out])
        with open(out, "rb") as f:
            reu = f.read()
        with open(self.out, "rb") as f:
            d64 = f.read()
        self.assertEqual(len(reu), 262144)
        self.assertEqual(reu[376 * 256:376 * 256 + 6], b"C64F2\x02")
        for b in (0, 357, 376, 400, 682):
            self.assertEqual(reu[b * 256:(b + 1) * 256], d64[b * 256:(b + 1) * 256])
        self.assertEqual(reu[len(d64):], bytes(262144 - len(d64)))

    def test_cbm_directory_has_boot_file(self):
        self.assertEqual(self.img.cbm_files(), [(b"BREADBIN", 0x82)])
        self.assertEqual(self.img.cbm_read(b"BREADBIN"), self.boot)

    def test_no_rev_is_unchanged(self):
        """Without --rev: no stamp entry and no /etc/build (today's image)."""
        self.assertEqual(self.img.cbm_entries(), [(b"BREADBIN", 0x82)])
        with self.assertRaises(FileNotFoundError):
            self.fs.lookup("/etc/build")

    def _build_rev(self, rev):
        t = self.tmp.name
        out = os.path.join(t, "rev.d64")
        M.build(out, os.path.join(t, "boot.prg"), os.path.join(t, "root"),
                ["console:1", "null:0"], rev)
        img = M.load(out)
        return img, M.FS(img)

    def test_rev_stamp_entry(self):
        img, fs = self._build_rev("8cc3e57")
        # boot file first, then the closed DEL stamp, nothing else
        self.assertEqual(img.cbm_entries(), [(b"BREADBIN", 0x82), (b"BUILD 8CC3E57", 0xC0)])
        self.assertEqual(img.cbm_files(), [(b"BREADBIN", 0x82)])   # DEL is not a file
        self.assertEqual(img.cbm_read(b"BREADBIN"), self.boot)
        d = img.block(M.ts_to_block(18, 1))
        self.assertEqual(bytes(d[34:37]), b"\xc0\x00\x00")           # DEL closed+locked, t/s 0/0
        self.assertEqual(bytes(d[32 + 5:32 + 21]), b"BUILD 8CC3E57" + b"\xa0" * 3)
        self.assertEqual(bytes(d[32 + 30:32 + 32]), b"\x00\x00")       # 0 blocks
        self.assertEqual(bytes(d[0:2]), b"\x00\xff")                  # single dir sector

    def test_rev_dirty_and_long(self):
        img, _ = self._build_rev("abcdef0+")
        self.assertEqual(img.cbm_entries()[1][0], b"BUILD ABCDEF0+")
        img, fs = self._build_rev("x" * 40)
        self.assertEqual(img.cbm_entries()[1][0], b"BUILD " + b"X" * 10)  # 16-char name limit
        ino = fs.lookup("/etc/build")
        self.assertEqual(fs.read_file(ino), b"breadbin " + b"x" * 40 + b"\n")

    def test_rev_etc_build(self):
        _, fs = self._build_rev("8cc3e57+")
        self.assertEqual(fs.read_file(fs.lookup("/etc/build")), b"breadbin 8cc3e57+\n")
        self.assertEqual(fs.read_file(fs.lookup("/home/readme")), b"hello unix\n" * 100)

    def test_cbm_bam_all_allocated(self):
        bam = self.img.block(M.ts_to_block(18, 0))
        self.assertTrue(all(bam[4 * t] == 0 for t in range(1, 36)))

    def test_superblock(self):
        """Upstream's format 2 (docs/filesystem.md there): magic, version, 683 blocks, 128
        inodes, bitmap 377, inodes 378 (32 blocks), root 1, last_time 0."""
        sb = self.img.block(376)
        self.assertEqual(bytes(sb[0:6]), b"C64F2\x02")
        self.assertEqual(sb[6] | sb[7] << 8, 683)
        self.assertEqual(sb[8], 128)
        self.assertEqual(sb[9] | sb[10] << 8, 377)
        self.assertEqual(sb[11] | sb[12] << 8, 378)
        self.assertEqual((sb[13], sb[14]), (32, 1))
        self.assertEqual(bytes(sb[15:19]), bytes(4))           # last_time: 0, unknown
        self.assertEqual(bytes(sb[19:M.SB_BUILD_ID]), bytes(M.SB_BUILD_ID - 19))

    def test_inodes_are_64_bytes(self):
        """Inode n at block 378 + n // 4, offset (n % 4) * 64; bytes 32-63 (times, reserved) 0."""
        blk = self.img.block(378)
        self.assertEqual(blk[0], 0xff)                         # inode 0: reserved
        self.assertEqual(blk[64:66], bytes([M.T_DIR, 6]))      # root: 2 + bin, dev, home, tmp
        big = self.fs.lookup("/bin/big")
        raw = self.img.block(378 + big // 4)[(big % 4) * 64:(big % 4) * 64 + 64]
        self.assertEqual(raw[2] | raw[3] << 8, 5120)
        for n in range(128):
            raw = self.img.block(378 + n // 4)[(n % 4) * 64:(n % 4) * 64 + 64]
            self.assertEqual(raw[32:], bytes(32), n)

    def test_build_id(self):
        sb = self.img.block(376)
        bid = bytes(sb[M.SB_BUILD_ID:M.SB_BUILD_ID + 4])
        self.assertNotEqual(bid, bytes(4))
        again = os.path.join(self.tmp.name, "y.d64")
        t = self.tmp.name
        M.build(again, os.path.join(t, "boot.prg"), os.path.join(t, "root"),
                ["console:1", "null:0"])
        self.assertEqual(bytes(M.load(again).block(376)[M.SB_BUILD_ID:M.SB_BUILD_ID + 4]), bid)   # same content, same id
        with open(os.path.join(t, "root", "home", "readme"), "ab") as f:
            f.write(b"x")
        M.build(again, os.path.join(t, "boot.prg"), os.path.join(t, "root"),
                ["console:1", "null:0"])
        self.assertNotEqual(bytes(M.load(again).block(376)[M.SB_BUILD_ID:M.SB_BUILD_ID + 4]), bid)

    def test_root_entries(self):
        names = [n for n, _ in self.fs.dir_entries(M.ROOT_INO)]
        self.assertEqual(names[:2], [b".", b".."])
        self.assertEqual(sorted(names[2:]), [b"bin", b"dev", b"home", b"tmp"])

    def test_dotdot(self):
        home = self.fs.lookup("/home")
        d = dict(self.fs.dir_entries(home))
        self.assertEqual(d[b".."], M.ROOT_INO)
        self.assertEqual(d[b"."], home)

    def test_file_roundtrip(self):
        self.assertEqual(self.fs.read_file(self.fs.lookup("/home/readme")),
                         b"hello unix\n" * 100)
        self.assertEqual(self.fs.read_file(self.fs.lookup("/bin/big")),
                         bytes(range(256)) * 20)
        self.assertNotEqual(self.fs.read_inode(self.fs.lookup("/bin/big"))["indirect"], 0)

    def test_devices(self):
        i = self.fs.read_inode(self.fs.lookup("/dev/console"))
        self.assertEqual((i["type"], i["major"]), (M.T_CHR, 1))

    def test_boot_and_dir_track_not_in_free_space(self):
        for b in range(11):
            self.assertTrue(self.fs.is_used(b))
        for b in range(357, 410):
            self.assertTrue(self.fs.is_used(b))

    def test_bits_past_end_marked_used(self):
        self.assertTrue(all(self.fs.is_used(b) for b in range(683, 2048)))

    def test_name_too_long(self):
        with self.assertRaises(OSError):
            self.fs.create(M.ROOT_INO, b"a" * 15, b"x")

    def test_ts_mapping(self):
        self.assertEqual(M.ts_to_block(18, 0), 357)
        self.assertEqual(M.block_to_ts(682), (35, 16))
        self.assertEqual(M.block_to_ts(376), (19, 0))


class TestPlacement(unittest.TestCase):
    """build(): directories and indirect blocks near the inode table, file data in runs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        root = os.path.join(t, "root")
        os.makedirs(os.path.join(root, "bin"))
        os.makedirs(os.path.join(root, "lib"))
        for i in range(60):                               # a /bin of four directory blocks
            with open(os.path.join(root, "bin", f"c{i:02}"), "wb") as f:
                f.write(bytes([i]) * (256 * (1 + i % 5)))
        with open(os.path.join(root, "bin", "sh"), "wb") as f:
            f.write(os.urandom(256 * 20))                 # needs the indirect block
        with open(os.path.join(t, "boot.prg"), "wb") as f:
            f.write(bytes(300))
        self.out = os.path.join(t, "x.d64")
        self.root = root
        M.build(self.out, os.path.join(t, "boot.prg"), root, ["null:0"])
        self.fs = M.FS(M.load(self.out))

    def tearDown(self):
        self.tmp.cleanup()

    def blocks(self, path):
        ino = self.fs.read_inode(self.fs.lookup(path))
        return [self.fs.bmap(ino, i) for i in range((ino["size"] + 255) // 256)], ino

    def test_contents_survive(self):
        for name in ("sh", "c07", "c59"):
            with open(os.path.join(self.root, "bin", name), "rb") as f:
                self.assertEqual(self.fs.read_file(self.fs.lookup("/bin/" + name)), f.read())

    def test_directories_and_indirect_are_near_the_inode_table(self):
        centre = M.block_to_ts(self.fs.istart)[0]
        for path in ("/", "/bin", "/lib"):
            bl, _ = self.blocks(path)
            for b in bl:
                self.assertLessEqual(abs(M.block_to_ts(b)[0] - centre), 4, path)
        _, ino = self.blocks("/bin/sh")
        self.assertLessEqual(abs(M.block_to_ts(ino["indirect"])[0] - centre), 4)

    def test_hot_file_is_first_in_its_directory(self):
        names = [n for n, _ in self.fs.dir_entries(self.fs.lookup("/bin"))]
        self.assertEqual(names[2], b"sh")                 # after . and ..

    def test_a_files_blocks_run_consecutively_within_a_track(self):
        bl, _ = self.blocks("/bin/sh")
        for a, b in zip(bl, bl[1:]):
            ta, sa = M.block_to_ts(a)
            tb, sb = M.block_to_ts(b)
            if ta == tb:
                self.assertEqual(sb, sa + 1)
            else:                                         # a new track: the nearest one with room
                self.assertLessEqual(abs(tb - ta), 2)

    def test_no_block_used_twice(self):
        seen = {}
        def walk(n, path):
            ino = self.fs.read_inode(n)
            nb = (ino["size"] + 255) // 256
            owned = [self.fs.bmap(ino, i) for i in range(nb)] + ([ino["indirect"]] if ino["indirect"] else [])
            for b in owned:
                self.assertNotIn(b, seen, path)
                seen[b] = path
                self.assertTrue(self.fs.is_used(b), path)
            if ino["type"] == M.T_DIR:
                for name, c in self.fs.dir_entries(n):
                    if name not in (b".", b".."):
                        walk(c, path + "/" + name.decode())
        walk(M.ROOT_INO, "")

    def test_deterministic(self):
        t = self.tmp.name
        out2 = os.path.join(t, "y.d64")
        M.build(out2, os.path.join(t, "boot.prg"), self.root, ["null:0"])
        with open(self.out, "rb") as a, open(out2, "rb") as b:
            self.assertEqual(a.read(), b.read())


class TestD81(unittest.TestCase):
    """`mkimage.py d81`: a c64fs volume for a 1581 (mounted with /lib/km/d81)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = os.path.join(cls.tmp.name, "root")
        os.makedirs(os.path.join(root, "sub"))
        cls.big = bytes((i * 31 + (i >> 8)) & 0xFF for i in range(140 * 256))     # the largest file c64fs holds
        with open(os.path.join(root, "big"), "wb") as f:
            f.write(cls.big)
        with open(os.path.join(root, "sub", "a"), "wb") as f:
            f.write(b"a\n")
        cls.out = os.path.join(cls.tmp.name, "v.d81")
        M.main(["d81", cls.out, "--root", root, "--name", "vol"])
        with open(cls.out, "rb") as f:
            cls.data = f.read()
        cls.fs = M.FS(M.load(cls.out))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def blk(self, t, s):
        b = M.d81_block(t, s)
        return self.data[b * 256:(b + 1) * 256]

    def test_size_and_mapping(self):
        self.assertEqual(len(self.data), 819200)
        self.assertEqual(M.d81_block(1, 0), 0)
        self.assertEqual(M.d81_block(40, 0), 1560)
        self.assertEqual(M.d81_block(80, 39), 3199)

    def test_superblock_is_upstreams_1581_layout(self):
        """3200 blocks, bitmap 377-378, inodes 379-410 (upstream docs/filesystem.md)."""
        sb = self.data[376 * 256:377 * 256]
        self.assertEqual(sb[0:6], b"C64F2\x02")
        self.assertEqual(sb[6] | sb[7] << 8, 3200)
        self.assertEqual(sb[8], 128)
        self.assertEqual(sb[9] | sb[10] << 8, 377)
        self.assertEqual(sb[11] | sb[12] << 8, 379)
        self.assertEqual(sb[13], 32)
        self.assertEqual((self.fs.nblocks, self.fs.nbm), (3200, 2))
        self.assertEqual(sb[M.SB_BUILD_ID:M.SB_BUILD_ID + 4], bytes(4))   # no REU cache key: not a boot disk

    def test_files_roundtrip(self):
        self.assertEqual(self.fs.read_file(self.fs.lookup("/big")), self.big)
        self.assertEqual(self.fs.read_file(self.fs.lookup("/sub/a")), b"a\n")

    def test_reserved_blocks(self):
        for b in [0] + list(range(376, 411)) + list(range(1560, 1600)) + list(range(3200, 4096)):
            self.assertTrue(self.fs.is_used(b), b)
        ino = self.fs.read_inode(self.fs.lookup("/big"))
        used = [self.fs.bmap(ino, i) for i in range(140)] + [ino["indirect"]]
        self.assertFalse(any(b == 0 or 376 <= b < 411 or 1560 <= b < 1600 or b >= 3200 for b in used))

    def test_bitmap_bits(self):
        """Block b: bitmap block 377 + (b >> 11), byte (b >> 3) & 255, bit b & 7."""
        bm0 = self.data[377 * 256:378 * 256]
        bm1 = self.data[378 * 256:379 * 256]
        self.assertEqual(bm0[1560 >> 3:1600 >> 3], b"\xff" * 5)                  # track 40
        self.assertEqual(bm0[1600 >> 3], 0)
        self.assertEqual(bm1[(3200 >> 3) & 255:], b"\xff" * (256 - ((3200 >> 3) & 255)))   # past the end
        self.assertEqual(bm1[(3192 >> 3) & 255], 0)

    def test_alloc_fills_3200_and_skips_track_40(self):
        img = M.Image(size=M.D81_SIZE)
        fs = M.FS(img)
        fs.format(img.write_cbm_d81() | {0})
        got = []
        with self.assertRaises(OSError):
            while True:
                got.append(fs.alloc_block())
        self.assertEqual(len(got), 3200 - 2 - 35 - 40)       # block 0, root dir, metadata, track 40
        self.assertEqual(max(got), 3199)
        self.assertTrue(any(2048 <= b < 3200 for b in got))
        self.assertFalse(any(1560 <= b < 1600 for b in got))
        self.assertEqual(fs.free_blocks(), 0)

    def test_cbm_header_bam_and_directory(self):
        h = self.blk(40, 0)
        self.assertEqual(h[0:3], bytes([40, 3, 0x44]))
        self.assertEqual(h[4:20], b"VOL".ljust(16, b"\xa0"))
        self.assertEqual(h[0x16:0x18], b"BB")
        self.assertEqual(h[0x19:0x1b], b"3D")
        for s, link in ((1, (40, 2)), (2, (0, 0xff))):
            bam = self.blk(40, s)
            self.assertEqual(tuple(bam[0:2]), link)
            self.assertEqual(bam[2:7], bytes([0x44, 0xbb]) + b"BB" + bytes([0xc0]))
            self.assertEqual(bam[0x10:0x10 + 6 * 40], bytes(240))      # every track: 0 free, all allocated
        self.assertEqual(self.blk(40, 3)[0:2], bytes([0, 0xff]))
        self.assertEqual(self.blk(40, 3)[2:], bytes(254))               # an empty directory

    def test_d64_load_still_rejects_other_sizes(self):
        with self.assertRaises(ValueError):
            M.Image(bytes(1000))

    def test_ls_and_cat_on_a_d81(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            M.main(["ls", self.out, "/"])
        self.assertIn("big", buf.getvalue())
        self.assertIn("sub", buf.getvalue())


def format1(img, reserved, nblocks):
    """A format 1 c64fs (magic C64FS, 32-byte inodes, one bitmap block) as kernels before
    format 2 wrote it; FS then works on it by its superblock."""
    sb = bytearray(256)
    sb[0:6] = b"C64FS\x01"
    sb[6], sb[7] = nblocks & 0xff, nblocks >> 8
    sb[8:15] = bytes([128, 377 & 0xff, 377 >> 8, 378 & 0xff, 378 >> 8, 16, 1])
    img.put_block(376, sb)
    for b in range(377, 394):
        img.put_block(b, bytearray(256))
    fs = M.FS(img)
    assert (fs.version, fs.nbm, fs.lay.inode_size) == (1, 1, 32)
    for b in set(reserved) | set(range(376, 394)) | set(range(nblocks, 2048)):
        fs.set_used(b, True)
    ino0 = fs.read_inode(0)
    ino0["type"] = 0xff
    fs.write_inode(0, ino0)
    assert fs.alloc_inode(M.T_DIR) == 1
    fs.dir_add(1, b".", 1)
    fs.dir_add(1, b"..", 1)
    r = fs.read_inode(1)
    r["nlink"] = 2
    fs.write_inode(1, r)
    return fs


class TestUpgrade(unittest.TestCase):
    """`mkimage.py upgrade`: format 1 -> format 2, contents kept."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "root")
        make_tree(self.root)
        self.boot = bytes(range(256)) * 10 + b"end"

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, fs):
        self.assertEqual(fs.version, 2)
        self.assertEqual(fs.read_file(fs.lookup("/home/readme")), b"hello unix\n" * 100)
        self.assertEqual(fs.read_file(fs.lookup("/bin/big")), bytes(range(256)) * 20)
        i = fs.read_inode(fs.lookup("/dev/console"))
        self.assertEqual((i["type"], i["major"]), (M.T_CHR, 1))
        self.assertEqual(sorted(n for n, _ in fs.dir_entries(1)), [b".", b"..", b"bin", b"dev", b"home", b"tmp"])

    def test_d64_boot_disk(self):
        img = M.Image()
        fs = format1(img, img.write_cbm(b"BREADBIN", self.boot), 683)
        fs.add_tree(self.root, 1)
        fs.create(fs.mkdir(1, b"dev"), b"console", b"", M.T_CHR, 1)
        src, out = os.path.join(self.tmp.name, "old.d64"), os.path.join(self.tmp.name, "new.d64")
        with open(src, "wb") as f:
            f.write(img.data)
        M.main(["upgrade", src, out])
        new = M.load(out)
        self.check(M.FS(new))
        self.assertEqual(new.cbm_read(b"BREADBIN"), self.boot)          # copied as it was
        self.assertNotEqual(bytes(new.block(376)[M.SB_BUILD_ID:M.SB_BUILD_ID + 4]), bytes(4))
        with self.assertRaises(SystemExit):                              # not format 1 any more
            M.upgrade(out, out + "2")

    def test_d64_new_kernel(self):
        img = M.Image()
        fs = format1(img, img.write_cbm(b"BREADBIN", b"old"), 683)
        fs.add_tree(self.root, 1)
        fs.create(fs.mkdir(1, b"dev"), b"console", b"", M.T_CHR, 1)
        src, out = os.path.join(self.tmp.name, "old.d64"), os.path.join(self.tmp.name, "new.d64")
        with open(src, "wb") as f:
            f.write(img.data)
        boot = os.path.join(self.tmp.name, "boot.prg")
        with open(boot, "wb") as f:
            f.write(self.boot)
        M.upgrade(src, out, boot)
        new = M.load(out)
        self.check(M.FS(new))
        self.assertEqual(new.cbm_read(b"BREADBIN"), self.boot)

    def test_d81_volume(self):
        """A .d81 from before format 2 (2048 blocks, one bitmap block) becomes 3200 blocks."""
        img = M.Image(size=M.D81_SIZE)
        fs = format1(img, img.write_cbm_d81() | {0}, 2048)
        fs.add_tree(self.root, 1)
        fs.create(fs.mkdir(1, b"dev"), b"console", b"", M.T_CHR, 1)
        src, out = os.path.join(self.tmp.name, "old.d81"), os.path.join(self.tmp.name, "new.d81")
        with open(src, "wb") as f:
            f.write(img.data)
        new = M.upgrade(src, out)
        fs2 = M.FS(new)
        self.check(fs2)
        self.assertEqual((fs2.nblocks, fs2.nbm, fs2.istart), (3200, 2, 379))
        self.assertTrue(all(fs2.is_used(b) for b in [0] + list(range(1560, 1600))))
        self.assertEqual(new.block(1560)[0:3], bytes([40, 3, 0x44]))    # the 1581 header kept
        self.assertEqual(bytes(new.block(376)[M.SB_BUILD_ID:M.SB_BUILD_ID + 4]), bytes(4))


class TestCX(unittest.TestCase):
    def test_relocs(self):
        a = bytes([0xad, 0x10, 0x00, 0xea, 0x20, 0x00, 0xa0])
        b = bytes([0xad, 0x10, 0x01, 0xea, 0x20, 0x00, 0xa0])
        self.assertEqual(cx.relocs(a, b), [2])

    def test_bad_diff(self):
        with self.assertRaises(ValueError):
            cx.relocs(b"\x01", b"\x05")

    def test_header(self):
        out = cx.make_cx(b"\x00\x10", b"\x00\x11", 300)
        self.assertEqual(out[:3], b"CX\x01")
        self.assertEqual(out[3:9], bytes([2, 0, 44, 1, 1, 0]))
        self.assertEqual(out[-2:], b"\x01\x00")

    def test_bss_label(self):
        self.assertEqual(cx.bss_size("al 000123 .__BSS_SIZE__\n"), 0x123)


if __name__ == "__main__":
    unittest.main()
