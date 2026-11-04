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

    def test_pc_wrap_then_more_bytes_ends_cleanly(self):
        # the hater's input: a wrap error, then more bytes: the old fill loop wrote over all of memory
        r = self.asm(".byte 1,1,1,1,1,1,1,1,1,1\n.res 65530\n.byte 1\n", expect_exit=1)
        self.assertIn(b"too big", r.err)
        self.assertNotIn("/o", r.files)

    def test_a_forward_res_count_is_an_error(self):
        r = self.asm(".byte 1\n.res n\n.byte 2\nn = 4\n", expect_exit=1)
        self.assertIn(b"res count", r.err)
        self.assertNotIn("/o", r.files)

    def test_a_backward_res_count_is_fine(self):
        h, img, _ = self.out("n = 4\n.byte 1\n.res n\n")
        self.assertEqual((h["image"], h["bss"]), (1, 4))




@unittest.skipIf(SKIP, SKIP)
class AsLongLine(unittest.TestCase):
    """as read a line into a 128-byte buffer and dropped every character past 126, silently: a
    long .byte line lost its tail and its zero, and the program ran on into the next data."""

    def image(self, n):
        src = b's: .byte "' + b"x" * n + b'", 0\n'
        return asim.run("as", ["/s", "/o"], {"/s": src})

    def test_a_long_line_is_kept_whole(self):
        r = self.image(150)
        self.assertEqual(r.exit, 0, r.err)
        b = r.files["/o"]
        self.assertIn(b"x" * 150 + b"\x00", b[9:9 + head(b)["image"]])

    def test_the_low_byte_of_a_constant_is_zero_page(self):
        # <$1234 is $34: a zero-page pointer; only a label's low byte is refused
        for src in ("        lda (<$1234),y\n", "PTR = $1234\n        lda (<PTR),y\n"):
            self.assertEqual(asim.run("as", ["/s", "/o"], {"/s": src.encode()}).exit, 0, src)

    def test_a_cr_inside_a_string_is_kept(self):
        src = b's: .byte "a\rb", 0\n'
        r = asim.run("as", ["/s", "/o"], {"/s": src})
        self.assertEqual(r.exit, 0, r.err)
        b = r.files["/o"]
        self.assertIn(b"\x61\x0d\x62\x00", b[9:9 + head(b)["image"]])

    def test_a_line_of_254_characters_fits(self):
        # the line is `s: .byte "` (10) + the string + `", 0` (4): 240 characters make 254 in all
        r = self.image(240)
        self.assertEqual(r.exit, 0, r.err)
        self.assertIn(b"x" * 240 + b"\x00", r.files["/o"][9:9 + head(r.files["/o"])["image"]])

    def test_crlf_does_not_count_against_the_limit(self):
        src = b's: .byte "' + b"x" * 240 + b'", 0\r\n'
        r = asim.run("as", ["/s", "/o"], {"/s": src})
        self.assertEqual(r.exit, 0, r.err)

    def test_a_line_of_255_characters_is_refused_loudly(self):
        r = self.image(241)
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"line too long", r.err)



@unittest.skipIf(SKIP, SKIP)
class AsZeroPageAndNames(unittest.TestCase):
    """(zp),y and (zp,x) take a zero-page pointer: the 6502 has no other form, and as used to
    assemble an absolute pointer silently. Names are kept to 14 characters: a longer name is refused,
    not cut (a cut name collided with its prefix)."""

    def asm(self, src):
        return asim.run("as", ["/s", "/o"], {"/s": src.encode()})

    def test_indirect_y_with_a_zero_page_pointer_is_fine(self):
        self.assertEqual(self.asm("ptr = $2b\n        lda (ptr),y\n").exit, 0)

    def test_indirect_y_with_an_absolute_pointer_is_refused(self):
        r = self.asm("ptr = $1234\n        lda (ptr),y\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"zero page", r.err)

    def test_indirect_x_with_an_absolute_pointer_is_refused(self):
        r = self.asm("ptr = $1234\n        lda (ptr,x)\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"zero page", r.err)

    def test_a_forward_zero_page_pointer_is_fine(self):
        self.assertEqual(self.asm("        lda (ptr),y\nptr = $2b\n").exit, 0)

    def test_a_forward_absolute_pointer_is_refused(self):
        r = self.asm("        lda (ptr),y\nptr = $1234\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"zero page", r.err)

    def test_a_label_at_image_offset_zero_is_refused(self):
        # a label is an offset in the image, not a runtime address: a small offset is not zero page
        r = self.asm("ptr: .word 0\n        lda (ptr),y\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"zero page", r.err)

    def test_a_label_at_a_small_image_offset_is_refused(self):
        r = self.asm("        lda (ptr),y\n        nop\nptr: .word 0\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"zero page", r.err)

    def test_a_res_label_is_refused(self):
        r = self.asm("ptr: .res 2\n        lda (ptr),y\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"zero page", r.err)

    def test_a_low_byte_of_a_label_is_refused(self):
        r = self.asm("        lda (<lbl),y\nlbl: .word 0\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"zero page", r.err)

    def test_the_program_counter_is_refused(self):
        r = self.asm("        lda (*),y\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"zero page", r.err)

    def test_a_14_character_name_is_kept_and_distinct(self):
        self.assertEqual(self.asm("abcdefghijklmn: nop\nabcdefghijklmo: nop\n").exit, 0)

    def test_a_15_character_name_is_refused_not_cut(self):
        r = self.asm("abcdefghijklmno: nop\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"longer than 14", r.err)


@unittest.skipIf(SKIP, SKIP)
class AsSymbolLimit(unittest.TestCase):
    """The table holds 255 names, 35 of them builtins: 220 labels of a program (was 185)."""

    def labels(self, n):
        return b"".join(b"l%d: nop\n" % i for i in range(n))

    def test_220_labels_fit(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.labels(220)})
        self.assertEqual(r.exit, 0, r.err)

    def test_221_labels_are_refused_loudly(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.labels(221)})
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"too many symbols", r.err)


@unittest.skipIf(SKIP, SKIP)
class AsCrAndPointers(unittest.TestCase):
    asm = AsOutput.asm
    out = AsOutput.out

    def test_zero_page_pointer_low_and_high_byte_of_a_constant_are_fine(self):
        # (<$1234),y is the pointer at $34 and (>$1234),y the pointer at $12: fixed bytes
        h, img, _ = self.out("lda (<$1234),y\nlda (>$1234),y\n")
        self.assertEqual(img, b"\xb1\x34\xb1\x12")

    def test_high_byte_of_a_label_is_refused_like_the_low_byte(self):
        r = self.asm("nop\nlbl: lda (>lbl),y\n", expect_exit=1)
        self.assertIn(b"zero page", r.err)

    def test_a_cr_inside_a_string_is_kept_and_crlf_lines_still_work(self):
        h, img, _ = self.out('.byte "a\rb", 7\r\n.byte 9\r\n.byte 1\r')
        self.assertEqual(img, b"a\rb\x07\x09\x01")

    def test_lone_cr_at_end_of_input_is_dropped(self):
        h, img, _ = self.out(".byte 5\r")
        self.assertEqual(img, b"\x05")


@unittest.skipIf(SKIP, SKIP)
class AsResCount(unittest.TestCase):
    """.res takes a count that is a number: not a negative one (the 16-bit pc would wrap to a huge BSS)
    and not an address (a label's value is an image offset, not a count)."""

    def asm(self, src):
        return asim.run("as", ["/s", "/o"], {"/s": src.encode()})

    def test_a_wrapped_count_is_refused(self):
        # as has no unary minus (`.res -1` is a syntax error); a wrap is what gets through: 0-1 is $FFFF
        r = self.asm("        .res 0-1\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"too big", r.err)

    def test_a_count_at_the_pool_size_is_refused(self):
        r = self.asm("        .res 39424\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"too big", r.err)

    def test_a_count_just_under_the_pool_size_is_fine(self):
        r = self.asm("        .res 39423\n")
        self.assertEqual(r.exit, 0, r.err)

    def test_a_label_as_the_count_is_refused(self):
        r = self.asm("n = 4\nbuf: .res n\n")          # a plain equate is a number: fine
        self.assertEqual(r.exit, 0, r.err)
        r = self.asm("here: .res here\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"res count is an address", r.err)

    def test_a_count_that_fills_the_address_space_is_refused_when_it_overflows(self):
        r = self.asm("        .res 65535\n        .res 2\n")
        self.assertNotEqual(r.exit, 0)


if __name__ == "__main__":
    unittest.main()
