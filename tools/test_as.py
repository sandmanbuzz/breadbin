"""The assembler's output, on the host: `as` runs under py65 (tools/asim.py), no VICE.
Header: "CX", 1, image size, BSS size, relocation count. A trailing .res is BSS (not stored); a .res
with something after it is stored as zeros, as it always was."""
import hashlib
import os
import re
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
class AsMalformed(unittest.TestCase):
    """Malformed input is refused with a message that names the line, never assembled into something else."""

    def asm(self, src):
        return asim.run("as", ["/s", "/o"], {"/s": src.encode()})

    def refused(self, src, text, line=None):
        r = self.asm(src)
        self.assertEqual(r.exit, 1, (src, r.out, r.err))
        self.assertIn(text, r.err)
        if line:
            self.assertIn(b"line %d:" % line, r.err)
        self.assertNotIn("/o", r.files)

    def test_unterminated_string_in_byte_is_refused(self):
        self.refused('nop\n.byte "abc\n', b"unterminated string", 2)

    def test_unterminated_string_in_text_is_refused(self):
        self.refused('.text "abc\n.byte 9\n', b"unterminated string", 1)

    def test_terminated_strings_still_assemble(self):
        r = self.asm('.byte "ab", 1 ; c\n.text "x;y"\n')
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(r.files["/o"][9:], b"ab\x01x;y")

    def test_trailing_junk_after_an_instruction_is_refused(self):
        self.refused("nop\nlda #1 junk\n", b"junk after the statement", 2)
        self.refused("lda (5),y z\n", b"junk after the statement", 1)
        self.refused("asl a b\n", b"junk after the statement", 1)

    def test_trailing_junk_after_a_directive_is_refused(self):
        self.refused(".byte 1 2\n", b"junk after the statement", 1)
        self.refused(".word 1 2\n", b"junk after the statement", 1)
        self.refused('.byte "a" "b"\n', b"junk after the statement", 1)
        self.refused("x = 5 6\n", b"junk after the statement", 1)
        self.refused("lab: nop nop\n", b"", 1)

    def test_comments_and_blanks_after_a_statement_are_fine(self):
        r = self.asm("lda #1 ; c\nnop   \n.byte 1,2 ;x\nlab: ; only\nx = 5 ; five\n")
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(r.files["/o"][9:], b"\xa9\x01\xea\x01\x02")

    def test_a_label_named_a_is_refused(self):
        # `a` in an operand is the accumulator: a symbol of that name could never be used
        self.refused("a: nop\n", b"a is the accumulator", 1)
        self.refused("a = 5\n", b"a is the accumulator", 1)
        r = self.asm("ab: nop\nlda #1\njmp ab\nfoo_a: nop\n")   # names that merely contain or start with a are fine
        self.assertEqual(r.exit, 0, r.err)

    def test_a_lone_quote_is_refused_and_emits_nothing(self):
        r = self.asm("lda #1\nlda #'\n")
        self.assertEqual(r.exit, 1, (r.out, r.err))
        self.assertIn(b"line 2:", r.err)
        self.assertIn(b"unterminated character", r.err)
        self.assertNotIn("/o", r.files)

    def test_an_unclosed_character_is_refused_and_a_closed_one_is_fine(self):
        self.refused("lda #'a\n", b"unterminated character", 1)
        r = self.asm("lda #'a'\n")
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(r.files["/o"][9:], b"\xa9a")


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

    def test_image_plus_res_over_the_pool_is_refused_and_the_message_says_so(self):
        # the pool holds image + BSS: 3 bytes of image and a count under the pool size still do not fit
        r = self.asm(".byte 1,2,3\n        .res 39423\n")
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"image plus res", r.err)
        self.assertNotIn("/o", r.files)
        r = self.asm(".byte 1,2,3\n        .res 39421\n")      # 39424 in all: one byte past the last page
        self.assertNotEqual(r.exit, 0)
        r = self.asm(".byte 1,2,3\n        .res 39420\n")      # 39423 in all: fits
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


class PoolSize(unittest.TestCase):
    """as refuses a .res that the user pool cannot hold: its POOLSZ must be the pool the kernel
    gives a program, KSTART (src/kernel/k.inc) less $0800. The two are in different files; this
    test is what keeps them the same when the footprint work moves the edge a page at a time."""

    def test_pool_size_matches_the_kernel(self):
        def const(path, name):
            with open(os.path.join(ROOT, path)) as f:
                for line in f:
                    m = re.match(r"\s*%s\s*=\s*\$([0-9A-Fa-f]+)" % name, line)
                    if m:
                        return int(m.group(1), 16)
            self.fail(f"{name} not found in {path}")
        kernel = const("src/kernel/k.inc", "KSTART") - 0x0800
        as_pool = const("src/bin/as.s", "POOLSZ")
        self.assertEqual(as_pool, kernel, "as's POOLSZ is not KSTART - $0800 in src/kernel/k.inc")


@unittest.skipIf(SKIP, SKIP)
class AsWriteErrors(unittest.TestCase):
    """A write that fails (a full disk) is an error: as says so and exits non-zero, rather than
    leaving a short file behind with exit 0."""

    SRC = b"lbl: .byte 1, 2, 3\n        .word lbl\n"

    def test_a_successful_write_is_fine(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC})
        self.assertEqual(r.exit, 0, r.err)

    def test_a_failed_header_write_is_reported(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC}, fail_write=1)
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"cannot write", r.err)

    def test_a_failed_image_write_is_reported(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC}, fail_write=2)
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"cannot write", r.err)

    def test_a_failed_relocation_write_is_reported(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC}, fail_write=3)
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"cannot write", r.err)

@unittest.skipIf(SKIP, SKIP)
class AsV8(unittest.TestCase):
    """Review V8 (agent C, on main 433ed4e): defects found by whole-file reads and by asim."""

    def run_as(self, src):
        return asim.run("as", ["/s", "/o"], {"/s": src.encode()})

    def test_256_errors_fail_the_assembly(self):
        # the error count is one byte: 256 errors used to wrap to 0 and read as success
        r = self.run_as("lda nosuch\n" * 256)
        self.assertEqual(r.exit, 1, r.err[-120:])

    def test_forward_equate_of_a_label_is_refused(self):
        # `x = fin` with fin later: the value and the relocation flag were not carried into pass 2
        r = self.run_as(" lda x\nx = fin\nfin: rts\n")
        self.assertEqual(r.exit, 1, r.err)
        self.assertIn(b"forward", r.err)

    def test_forward_equate_used_by_a_branch_is_refused(self):
        # n is 2 bytes in pass 1 and 3 in pass 2: the jmp landed in the middle of an instruction
        r = self.run_as(" jmp e\nn = k\n lda n\ne: rts\nk = $1234\n")
        self.assertEqual(r.exit, 1, r.err)
        self.assertIn(b"forward", r.err)

    def test_forward_equate_as_a_res_count_is_refused(self):
        # the res-count rule must not be bypassed through an equate
        r = self.run_as("n = bigc\n.res n\n.byte 7\nbigc = 300\n")
        self.assertEqual(r.exit, 1, r.err)
        self.assertIn(b"forward", r.err)

    def test_backward_equate_of_a_label_is_the_label(self):
        a = self.run_as("fin: rts\n x = fin\n lda x\n")
        b = self.run_as("fin: rts\n lda fin\n")
        self.assertEqual(a.exit, 0, a.err)
        self.assertEqual(b.exit, 0, b.err)
        self.assertEqual(a.files["/o"], b.files["/o"])


    SRC8 = b"lbl: .byte 1, 2, 3\n        .word lbl\n"

    def image(self, src):
        r = self.run_as(src)
        self.assertEqual(r.exit, 0, r.err)
        b = r.files["/o"]
        return b[9:9 + head(b)["image"]]

    def test_an_apostrophe_in_a_string_does_not_stop_the_string(self):
        # the lowercase pass once toggled one shared flag for ' and ": a ' inside "..." flipped it
        self.assertEqual(self.image('.byte "don\'t PANIC"\n'), b"don't PANIC")

    def test_an_apostrophe_in_a_string_leaves_the_next_operand_alone(self):
        self.assertEqual(self.image('Foo = 1\n.byte "don\'t", Foo\n'), b"don't\x01")

    def test_a_double_quote_in_single_quotes_is_a_character(self):
        self.assertEqual(self.image(".byte '\"', 1\n"), b'"\x01')

    def test_a_byte_of_a_label_in_word_is_refused(self):
        # .word stores two bytes and relocates the second: a byte of a label cannot be relocated there
        for src in [".word >lbl\nlbl: rts\n", ".word <lbl\nlbl: rts\n"]:
            r = self.run_as(src)
            self.assertEqual(r.exit, 1, src)
            self.assertIn(b"label", r.err)

    def test_a_failed_write_keeps_the_previous_output(self):
        # the output is written under a temporary name and renamed only when complete
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8, "/o": b"OLD"}, fail_write=2)
        self.assertNotEqual(r.exit, 0)
        self.assertIn(b"cannot write", r.err)
        self.assertEqual(r.files.get("/o"), b"OLD")
        self.assertEqual(set(r.files), {"/s", "/o"})

    def test_a_failed_write_leaves_no_output_file(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8}, fail_write=2)
        self.assertNotEqual(r.exit, 0)
        self.assertEqual(set(r.files), {"/s"})

    def test_a_successful_write_replaces_the_old_output(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8, "/o": b"OLD"})
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(r.files["/o"][:3], b"CX\x01")
        self.assertEqual(set(r.files), {"/s", "/o"})


    def test_an_output_name_too_long_for_the_temporary_name_is_refused(self):
        r = asim.run("as", ["/s", "/" + "a" * 79], {"/s": self.SRC8})
        self.assertEqual(r.exit, 1, r.err)
        self.assertTrue(r.err.startswith(b"as: ") and r.err.endswith(b"\n"), r.err)
        self.assertIn(b"too long", r.err)


    def test_a_14_character_output_name_assembles(self):
        # c64fs names are at most 14 characters: the temporary name must not be longer than the output's
        r = asim.run("as", ["/s", "/abcdefghijklmn"], {"/s": self.SRC8})
        self.assertEqual(r.exit, 0, r.err)
        self.assertIn("/abcdefghijklmn", r.files)

    def test_a_failed_rename_after_the_unlink_leaves_the_complete_temporary_and_says_so(self):
        # the old output is unlinked before the rename (CBM DOS cannot rename over it), so when the rename fails the
        # old output is gone and the complete temporary is the file: the message names it and says so
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8, "/o": b"OLD"}, fail_rename=1)
        self.assertEqual(r.exit, 1, r.err)
        self.assertNotIn("/o", r.files)
        self.assertTrue(r.files.get("/~o", b"")[:3] == b"CX\x01", sorted(r.files))
        self.assertIn(b"~o", r.err)
        self.assertIn(b"old output was removed", r.err)

    def test_a_failed_rename_with_no_old_output_does_not_claim_a_removal(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8}, fail_rename=1)
        self.assertEqual(r.exit, 1, r.err)
        self.assertNotIn(b"removed", r.err)
        self.assertIn(b"~o", r.err)

    def test_reassembly_onto_an_existing_output_replaces_it_where_rename_refuses_to_replace(self):
        # src/mod/cbm.s cbm_rename sends "R0:new=old"; CBM DOS refuses an existing new name (error 63; kernel EIO).
        # as unlinks the old output first, so the rename lands. Modelled in asim only (rename_noreplace); the VICE
        # answer is recorded in docs/design/s13-as-limits.md.
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8, "/o": b"OLD"}, rename_noreplace=True)
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(r.files["/o"][:3], b"CX\x01")
        self.assertNotIn("/~o", r.files)
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8}, rename_noreplace=True)
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(r.files["/o"][:3], b"CX\x01")
        self.assertNotIn("/~o", r.files)

    def test_a_user_file_at_the_temporary_name_is_not_destroyed(self):
        # the temporary is derived from the output name; a file already there is refused, not truncated
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8, "/~o": b"USER"})
        self.assertEqual(r.exit, 1, r.err)
        self.assertEqual(r.files["/~o"], b"USER")
        self.assertIn(b"~o", r.err)
        self.assertIn(b"remove it and try again", r.err)
        self.assertNotIn("/o", r.files)

    def test_a_probe_error_other_than_absent_is_refused(self):
        # only ENOENT means the temporary name is free; any other error from the probe must not be treated as absent
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8}, fail_read_open=("/~o", 5))
        self.assertEqual(r.exit, 1, r.err)
        self.assertNotIn("/o", r.files)
        self.assertNotIn("/~o", r.files)

    def test_a_user_file_at_the_temporary_name_survives_a_failed_write(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8, "/~o": b"USER"}, fail_write=1)
        self.assertEqual(r.exit, 1, r.err)
        self.assertEqual(r.files["/~o"], b"USER")

    def test_an_output_named_like_the_old_temporary_keeps_its_content(self):
        good = asim.run("as", ["/s", "/o"], {"/s": self.SRC8}).files["/o"]
        r = asim.run("as", ["/s", "/~as"], {"/s": self.SRC8})
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(r.files["/~as"], good)

    def test_a_user_file_named_tilde_as_is_left_alone(self):
        r = asim.run("as", ["/s", "/o"], {"/s": self.SRC8, "/~as": b"USER"})
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(r.files["/~as"], b"USER")

    def test_output_name_lengths(self):
        for n in (13, 14):
            name = "/" + "x" * n
            r = asim.run("as", ["/s", name], {"/s": self.SRC8})
            self.assertEqual(r.exit, 0, (n, r.err))
            self.assertEqual(r.files[name][:3], b"CX\x01")
            self.assertEqual(sorted(r.files), sorted(["/s", name]))
        r = asim.run("as", ["/s", "/" + "x" * 15], {"/s": self.SRC8})
        self.assertEqual(r.exit, 1)
        self.assertIn(b"too long", r.err)
        self.assertEqual(sorted(r.files), ["/s"])

    def test_a_tilde_name_of_14_characters_does_not_collide_with_its_temporary(self):
        name = "/" + "~" * 14
        r = asim.run("as", ["/s", name], {"/s": self.SRC8})
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(r.files[name][:3], b"CX\x01")
        self.assertEqual(sorted(r.files), sorted(["/s", name]))

    def test_two_outputs_in_one_directory_do_not_interfere(self):
        a = asim.run("as", ["/s", "/a"], {"/s": self.SRC8})
        self.assertEqual(a.exit, 0, a.err)
        files = dict(a.files)
        files["/s"] = b"x: .byte 9\n"
        b = asim.run("as", ["/s", "/b"], files)
        self.assertEqual(b.exit, 0, b.err)
        self.assertEqual(b.files["/a"], a.files["/a"])
        self.assertNotEqual(b.files["/b"], b.files["/a"])
        self.assertEqual(sorted(b.files), ["/a", "/b", "/s"])

    def test_a_byte_of_a_label_through_an_equate_is_refused(self):
        # k => lbl is label-derived: .byte k would be a constant 0 with no relocation
        for use in (".byte k", ".word k"):
            r = self.run_as("lbl: rts\nk = >lbl\n" + use + "\n")
            self.assertEqual(r.exit, 1, (use, r.err))
        r = self.run_as("lbl: rts\nk = <lbl\n.byte k\n")
        self.assertEqual(r.exit, 1, r.err)

    def test_a_plain_label_equate_still_relocates_in_word(self):
        r = self.run_as("lbl: rts\nk = lbl\n.word k\n")
        self.assertEqual(r.exit, 0, r.err)
        self.assertEqual(head(r.files["/o"])["relocs"], 1)


if __name__ == "__main__":
    unittest.main()
