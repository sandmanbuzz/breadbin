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
        self.assertEqual(reu[376 * 256:376 * 256 + 6], b"C64FS\x01")
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
        sb = self.img.block(376)
        self.assertEqual(bytes(sb[0:5]), b"C64FS")
        self.assertEqual(sb[8], 128)
        self.assertEqual(sb[9] | sb[10] << 8, 377)

    def test_build_id(self):
        sb = self.img.block(376)
        bid = bytes(sb[15:19])
        self.assertNotEqual(bid, bytes(4))
        again = os.path.join(self.tmp.name, "y.d64")
        t = self.tmp.name
        M.build(again, os.path.join(t, "boot.prg"), os.path.join(t, "root"),
                ["console:1", "null:0"])
        self.assertEqual(bytes(M.load(again).block(376)[15:19]), bid)   # same content, same id
        with open(os.path.join(t, "root", "home", "readme"), "ab") as f:
            f.write(b"x")
        M.build(again, os.path.join(t, "boot.prg"), os.path.join(t, "root"),
                ["console:1", "null:0"])
        self.assertNotEqual(bytes(M.load(again).block(376)[15:19]), bid)

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
        for b in range(357, 394):
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
