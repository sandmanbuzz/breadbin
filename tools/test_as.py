"""The assembler's output, on the host: `as` runs under py65 (tools/asim.py), no VICE.
Header: "CX", 1, image size, BSS size, relocation count. A trailing .res is BSS (not stored); a .res
with something after it is stored as zeros, as it always was."""
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asim  # noqa: E402

ROOT = asim.ROOT
BUILT = os.path.exists(os.path.join(ROOT, "build", "root", "bin", "as"))
SKIP = "py65 not installed" if asim.MPU is None else (None if BUILT else "not built (make)")


def head(b):
    return {"image": int.from_bytes(b[3:5], "little"), "bss": int.from_bytes(b[5:7], "little"),
            "relocs": int.from_bytes(b[7:9], "little")}


@unittest.skipIf(SKIP, SKIP)
class AsOutput(unittest.TestCase):
    def asm(self, src, expect_exit=0):
        r = asim.run("as", ["/s", "/o"], {"/s": src.encode()})
        self.assertEqual(r.exit, expect_exit, (r.out, r.err))
        return r

    def out(self, src):
        r = self.asm(src)
        b = r.files["/o"]
        self.assertEqual(b[:3], b"CX\x01")
        h = head(b)
        img = b[9:9 + h["image"]]
        self.assertEqual(len(b), 9 + h["image"] + 2 * h["relocs"])
        return h, img, r

    def test_hello_is_the_old_assembler_output_with_its_trailing_res_as_bss(self):
        with open(os.path.join(ROOT, "rootfs", "home", "hello.s"), "rb") as f:
            src = f.read()
        r = asim.run("as", ["/home/hello.s", "/home/hello"], {"/home/hello.s": src})
        self.assertEqual(r.exit, 0)
        b = r.files["/home/hello"]
        h = head(b)
        # the old assembler wrote 83 bytes of image (the last ones the trailing .res zeros), 5
        # relocations and a BSS size of 0; sha256 of its image + relocation table (all after the header):
        old_size, old_sha = 83, "d72ef53988aef8ed"
        self.assertEqual(h["image"] + h["bss"], old_size)
        self.assertGreater(h["bss"], 0)
        rebuilt = b[9:9 + h["image"]] + bytes(h["bss"]) + b[9 + h["image"]:]
        self.assertEqual(hashlib.sha256(rebuilt).hexdigest()[:16], old_sha)
        self.assertEqual(r.out, ("/home/hello: %d bytes, 5 relocations\n" % h["image"]).encode())

    def test_no_res_no_bss(self):
        h, img, _ = self.out(".byte 1, 2, 3\n")
        self.assertEqual((h["image"], h["bss"]), (3, 0))
        self.assertEqual(img, b"\x01\x02\x03")

    def test_res_in_the_middle_is_stored_as_zeros(self):
        h, img, _ = self.out(".byte 1, 2, 3\n.res 4\n.byte 9\n")
        self.assertEqual((h["image"], h["bss"]), (8, 0))
        self.assertEqual(img, b"\x01\x02\x03\0\0\0\0\x09")

    def test_leading_res_is_stored(self):
        h, img, _ = self.out(".res 3\n.byte 5\n")
        self.assertEqual((h["image"], h["bss"]), (4, 0))
        self.assertEqual(img, b"\0\0\0\x05")

    def test_trailing_res_is_bss(self):
        h, img, r = self.out(".byte 1, 2, 3\n.res 4\n")
        self.assertEqual((h["image"], h["bss"]), (3, 4))
        self.assertEqual(img, b"\x01\x02\x03")
        self.assertEqual(r.out, b"/o: 3 bytes, 0 relocations\n")

    def test_several_trailing_res_add_up(self):
        h, img, _ = self.out(".byte 7\n.res 10\n.res 5\n")
        self.assertEqual((h["image"], h["bss"]), (1, 15))

    def test_res_then_zero_byte_then_res(self):
        h, img, _ = self.out(".byte 7\n.res 2\n.byte 0\n.res 3\n")
        self.assertEqual((h["image"], h["bss"]), (4, 3))
        self.assertEqual(img, b"\x07\0\0\0")

    def test_labels_after_trailing_res_and_relocation(self):
        h, img, _ = self.out(".word buf\nbuf: .res 300\n")
        self.assertEqual((h["image"], h["bss"], h["relocs"]), (2, 300, 1))
        self.assertEqual(img, b"\x02\x08"[:1] + bytes([img[1]]))   # low byte 2; high byte = page + 0

    def test_a_big_trailing_res_no_longer_hits_the_8k_output_limit(self):
        h, img, _ = self.out(".byte 1\n.res 20000\n")
        self.assertEqual((h["image"], h["bss"]), (1, 20000))

    def test_a_big_stored_res_still_does(self):
        r = self.asm(".res 9000\n.byte 1\n", expect_exit=1)
        self.assertNotIn("/o", r.files)

    def test_res_zero_is_nothing(self):
        h, img, _ = self.out(".byte 1\n.res 0\n.byte 2\n")
        self.assertEqual((h["image"], h["bss"]), (2, 0))
        self.assertEqual(img, b"\x01\x02")

    def test_pc_overflow_is_an_error(self):
        r = self.asm(".byte 1\n.res 60000\n.res 60000\n", expect_exit=1)
        self.assertNotIn("/o", r.files)

    def test_instructions_after_res_see_the_right_addresses(self):
        # lda buf (absolute, relocatable) after a middle .res: the label is past the zeros
        h, img, _ = self.out(".byte 1\nbuf: .res 2\nlda buf\n")
        self.assertEqual((h["image"], h["bss"], h["relocs"]), (6, 0, 1))
        self.assertEqual(img[3], 0xAD)       # lda abs
        self.assertEqual(img[4], 1)          # buf = 1: low byte

    def test_input_is_a_file_listing_errors_without_output(self):
        r = self.asm("frobnicate\n", expect_exit=1)
        self.assertNotIn("/o", r.files)

    def test_bigbuf_assembles_small_and_runs(self):
        with open(os.path.join(ROOT, "rootfs", "home", "bigbuf.s"), "rb") as f:
            src = f.read()
        r = asim.run("as", ["/s", "/o"], {"/s": src})
        self.assertEqual(r.exit, 0, r.err)
        b = r.files["/o"]
        h = head(b)
        self.assertEqual(h["bss"], 12000)
        self.assertLess(len(b), 200)                      # the old assembler: refused (over 8 KB) or 12 KB on disk
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".cx") as f:
            f.write(b)
            f.flush()
            run = asim.run("bigbuf", [], path=f.name)
        self.assertEqual((run.exit, run.out), (0, b"bss ok\n"))


if __name__ == "__main__":
    unittest.main()
