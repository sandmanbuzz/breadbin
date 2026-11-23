"""The user library (src/lib: the per-routine objects and err.s) routine by routine under py65, through tools/libsim.py.

Two kinds of test, both on the library as built from this tree:
  * the contract: what each routine returns and writes, against a model written in Python from the routine's
    comment in the source (strlen is min(len, 255), dec_str is str(n), perr prints the line /etc/errors has ...);
  * the footprint: the zero page and stack a routine may use. Programs keep their own values in $23-$2F and in
    lp1/lp2 ($30-$33) across calls to the library, so which scratch bytes each routine may change is part of its
    contract (CLOBBER below, measured on the library as it was before the size pass: no routine may take more).
Each case runs under two different zero-page fills, so a routine that reads a stale scratch byte is caught.

BREADBIN_LIB_BASE=<dir of an older tree with src/lib and include> adds a differential run: the same cases on
both builds must agree on registers, flags, output and exit, and the new one may clobber no more than the old.
Skips without py65 or cc65."""
import os
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import libsim

ROOT = libsim.ROOT
SKIP = None
if libsim.MPU is None:
    SKIP = "py65 not installed"
elif not shutil.which("ca65"):
    SKIP = "cc65 not installed"

LP1, LP2, LP3, LT0, LT1, LT2, LT3, LVAL = 0x30, 0x32, 0x34, 0x36, 0x37, 0x38, 0x39, 0x3A
STR = 0x8000                                   # where inputs are placed
FILL = (0xA5, 0x5A)
ERRORS = open(os.path.join(ROOT, "rootfs", "etc", "errors"), "rb").read()
BUILTIN = {5: b"i/o error", 2: b"no such file or directory", 19: b"no such device or no disk"}

# Zero page a routine may change: r0/r1 $02-$05, lp1 $30-31, lp2 $32-33, lp3 $34-35, lt0-lt3 $36-39, lval $3A-3B (the
# syscall scratch $08-$1F is never listed). Measured on the library before the size pass, on library calls whose
# every path ran (tools/libsim.py); a routine that changes anything else breaks a caller's variable.
CLOBBER = {
    'argn': set(),
    'basename': {0x30, 0x31, 0x36},
    'dec_str': {0x37, 0x3a, 0x3b},
    'eprint': {0x02, 0x03, 0x04, 0x05, 0x30, 0x31, 0x36},
    'eputc': {0x02, 0x03, 0x04, 0x05, 0x36},
    'fprint': {0x02, 0x03, 0x04, 0x05, 0x30, 0x31, 0x36},
    'fputc': {0x02, 0x03, 0x04, 0x05, 0x36},
    'newline': {0x02, 0x03, 0x04, 0x05, 0x36},
    'open_or_die': {0x02, 0x03, 0x34, 0x35},
    'parse_dec': {0x30, 0x31, 0x36, 0x3a, 0x3b},
    'perr': {0x02, 0x03, 0x04, 0x05, 0x30, 0x31, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a},
    'print': {0x02, 0x03, 0x04, 0x05, 0x30, 0x31, 0x36},
    'print_dec': {0x02, 0x03, 0x04, 0x05, 0x30, 0x31, 0x36, 0x37, 0x3a, 0x3b},
    'print_dec_w': {0x02, 0x03, 0x04, 0x05, 0x30, 0x31, 0x32, 0x33, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x3b},
    'print_hex': {0x02, 0x03, 0x04, 0x05, 0x36},
    'putc': {0x02, 0x03, 0x04, 0x05, 0x36},
    'strcmp': set(),
    'strlen': {0x30, 0x31},
    'write_buf': set(),
}
SEEN = {}                                      # BREADBIN_LIB_MEASURE=1 prints what the cases above saw changed, as CLOBBER


def _lib(tree, tag):
    work = tempfile.mkdtemp(prefix="libsim-" + tag + "-")
    unittest.addModuleCleanup(shutil.rmtree, work, True)
    return libsim.Lib(tree, work)


def u16(v):
    return v & 0xFF, v >> 8


def cstring(s):
    return s + b"\0"


@unittest.skipIf(SKIP, SKIP)
class LibCase(unittest.TestCase):
    """Runs a check on every library under test; subclasses define test_* using self.libs."""
    libs = {}

    @classmethod
    def setUpClass(cls):
        if not LibCase.libs:
            LibCase.libs["new"] = _lib(ROOT, "new")
            base = os.environ.get("BREADBIN_LIB_BASE")
            if base:
                LibCase.libs["base"] = _lib(base, "base")

    def each(self, name, **kw):
        """Run routine `name` on every library under every fill: yields (tag, result)."""
        for tag, lib in self.libs.items():
            for fill in FILL:
                yield tag, lib.call(name, fill=fill, **kw)

    def check_footprint(self, name, r, tag):
        SEEN.setdefault(name, set()).update(r.clobbered)
        extra = set(r.clobbered) - CLOBBER.get(name, set(r.clobbered))
        self.assertFalse(extra, "%s (%s) changed zero page %s that callers may hold" % (name, tag, sorted(map(hex, extra))))


class Core(LibCase):
    def test_strlen(self):
        for n in (0, 1, 2, 7, 127, 128, 254, 255, 256, 300):
            for ptr in (STR, STR + 0xFE):
                data = b"x" * n
                for tag, r in self.each("strlen", a=ptr & 0xFF, x=ptr >> 8, mem={ptr: cstring(data)}):
                    self.assertEqual((r.a, r.y), (min(n, 255),) * 2, (tag, n))
                    self.check_footprint("strlen", r, tag)

    def test_basename(self):
        for path in (b"", b"/", b"a", b"a/b", b"/a/b/", b"dir/file", b"//x", b"x/", b"/etc/errors", b"a" * 200 + b"/b"):
            for tag, r in self.each("basename", a=STR & 0xFF, x=STR >> 8, mem={STR: cstring(path)}):
                self.assertEqual(r.cstr(r.a | r.x << 8), path[path.rfind(b"/") + 1:], (tag, path))
                self.check_footprint("basename", r, tag)

    def test_print_family(self):
        for text in (b"", b"a", b"hello, world\n", b"z" * 254, b"z" * 255, b"z" * 300, bytes(range(1, 40))):
            exp = text[:255]                       # strlen stops at 255
            for name, fd in (("print", 1), ("eprint", 2)):
                for tag, r in self.each(name, a=STR & 0xFF, x=STR >> 8, mem={STR: cstring(text)}):
                    self.assertEqual(r.out.get(fd, b""), exp, (tag, name))
                    self.assertEqual(r.out.get(3 - fd, b""), b"")
                    self.assertEqual(r.c, 0)
                    self.check_footprint(name, r, tag)
            for tag, r in self.each("fprint", a=STR & 0xFF, x=STR >> 8, y=7, mem={STR: cstring(text)}):
                self.assertEqual(r.out.get(7, b""), exp, tag)
                self.check_footprint("fprint", r, tag)

    def test_print_reports_a_failed_write(self):
        for name in ("print", "eprint"):
            for tag, r in self.each(name, a=STR & 0xFF, x=STR >> 8, mem={STR: b"hi\0"}, write_fail=1):
                self.assertEqual(r.c, 1, (tag, name))

    def test_write_buf_is_the_syscall(self):
        for tag, r in self.each("write_buf", a=2, mem={0x02: bytes(u16(STR)) + bytes([3, 0]), STR: b"abc"}):
            self.assertEqual(r.out, {2: b"abc"}, tag)
            self.check_footprint("write_buf", r, tag)

    def test_putc_family(self):
        for ch in (0, 1, 10, 65, 127, 128, 255):
            for name, fd in (("putc", 1), ("eputc", 2), ("newline", 1)):
                want = 10 if name == "newline" else ch
                for tag, r in self.each(name, a=ch):
                    self.assertEqual(r.out, {fd: bytes([want])}, (tag, name, ch))
                    self.assertEqual(r.c, 0)
                    self.check_footprint(name, r, tag)
            for tag, r in self.each("fputc", a=ch, y=9):
                self.assertEqual(r.out, {9: bytes([ch])}, tag)
                self.check_footprint("fputc", r, tag)

    def test_putc_reports_a_failed_write(self):
        for name in ("putc", "eputc", "newline"):
            for tag, r in self.each(name, a=65, write_fail=1):
                self.assertEqual(r.c, 1, (tag, name))

    def test_exit_is_the_syscall(self):
        for code in (0, 1, 255):
            for tag, r in self.each("exit", a=code):
                self.assertEqual(r.exit, code, tag)

    def test_argn(self):
        for argv in (("p",), ("p", "one"), ("cat", "a", "bb", "ccc")):
            for idx in range(len(argv) + 3):
                for tag, r in self.each("argn", a=idx, argv=argv):
                    if idx < len(argv):
                        self.assertEqual(r.c, 0, (tag, argv, idx))
                        self.assertEqual(r.cstr(r.a | r.x << 8), argv[idx].encode(), (tag, argv, idx))
                    else:
                        self.assertEqual(r.c, 1, (tag, argv, idx))
                    self.check_footprint("argn", r, tag)

    def test_strcmp(self):
        pairs = [(b"", b""), (b"a", b"a"), (b"a", b"b"), (b"ab", b"a"), (b"a", b"ab"), (b"abc", b"abc"), (b"abd", b"abc"),
                 (b"x" * 254, b"x" * 254), (b"x" * 254, b"x" * 253 + b"y")]
        for s, t in pairs:
            for tag, r in self.each("strcmp", mem={LP1: bytes(u16(STR)) + bytes(u16(STR + 0x400)),
                                                   STR: cstring(s), STR + 0x400: cstring(t)}):
                self.assertEqual(r.z, int(s == t), (tag, s, t))
                self.check_footprint("strcmp", r, tag)


class Num(LibCase):
    VALUES = sorted(set(list(range(0, 1200)) + [9999, 10000, 10001, 12345, 32767, 32768, 40000, 59999, 60000, 65534, 65535]
                        + [10 ** k + d for k in range(5) for d in (-1, 0, 1) if 0 <= 10 ** k + d < 65536]
                        + random.Random(1).sample(range(65536), 400)))

    def test_dec_str(self):
        for v in self.VALUES:
            for tag, r in self.each("dec_str", a=v & 0xFF, x=v >> 8):
                s = str(v).encode()
                self.assertEqual(r.cstr(r.a | r.x << 8), s, (tag, v))
                self.assertEqual(r.y, len(s), (tag, v))
                self.check_footprint("dec_str", r, tag)

    def test_print_dec(self):
        for v in self.VALUES[::7]:
            for tag, r in self.each("print_dec", a=v & 0xFF, x=v >> 8):
                self.assertEqual(r.out, {1: str(v).encode()}, (tag, v))
                self.check_footprint("print_dec", r, tag)

    def test_print_dec_w(self):
        for v in self.VALUES[::17]:
            for w in range(0, 9):
                for tag, r in self.each("print_dec_w", a=v & 0xFF, x=v >> 8, y=w):
                    self.assertEqual(r.out, {1: str(v).rjust(w).encode()}, (tag, v, w))
                    self.check_footprint("print_dec_w", r, tag)

    def test_print_hex(self):
        for v in range(256):
            for tag, r in self.each("print_hex", a=v):
                self.assertEqual(r.out, {1: b"%02x" % v}, (tag, v))
                self.check_footprint("print_hex", r, tag)

    def test_parse_dec(self):
        cases = [b"0", b"7", b"10", b"007", b"255", b"256", b"65535", b"65536", b"99999", b"123456", b"1" * 20, b"9" * 100]
        cases += [str(v).encode() for v in random.Random(2).sample(range(65536), 60)]
        for s in cases:
            for tag, r in self.each("parse_dec", a=STR & 0xFF, x=STR >> 8, mem={STR: cstring(s)}):
                want = int(s) & 0xFFFF
                self.assertEqual((r.c, r.a | r.x << 8), (0, want), (tag, s))
                self.assertEqual(r.mem[LVAL] | r.mem[LVAL + 1] << 8, want, "tail reads lval+1: " + repr(s))
                self.check_footprint("parse_dec", r, tag)
        for s in (b"", b"a", b"1a", b"a1", b"1 2", b"-1", b" 1", b"1.5", b"1\n", b"\xb1", b"0x10"):
            for tag, r in self.each("parse_dec", a=STR & 0xFF, x=STR >> 8, mem={STR: cstring(s)}):
                self.assertEqual(r.c, 1, (tag, s))
                self.check_footprint("parse_dec", r, tag)


def file_lookup(errno, data):
    """What perr prints for `errno` when /etc/errors holds `data`: the text of the first line "NN text" with NN == errno,
    read byte by byte; a line that is empty or has a non-digit before the space is skipped; the text runs to the newline
    or the end of the file; nothing found (or the file cannot be read): "error NN"."""
    for line in data.split(b"\n"):
        head, sp, text = line.partition(b" ")
        if sp and head.isdigit() and int(head) & 0xFF == errno:
            return text
    return b"error %d" % errno


def expect(errno, argv0=b"prog", extra=None, data=ERRORS):
    msg = BUILTIN.get(errno) or file_lookup(errno, data)
    return argv0 + b": " + (extra + b": " if extra else b"") + msg + b"\n"


class Err(LibCase):
    FILES = {"/etc/errors": ERRORS}

    def perr(self, errno, extra=None, files=None, argv=("prog",), **kw):
        mem = {}
        xy = {}
        if extra is not None:
            mem[STR] = cstring(extra)
            xy = dict(x=STR & 0xFF, y=STR >> 8)
        return self.each("perr", a=errno, mem=mem, argv=argv, files=self.FILES if files is None else files, **xy, **kw)

    def test_every_real_errno_with_the_shipped_file(self):
        for errno in (1, 2, 3, 5, 7, 8, 9, 10, 11, 12, 16, 17, 18, 19, 20, 21, 22, 24, 27, 28, 32, 36, 39, 4, 13, 23, 40, 99):
            for tag, r in self.perr(errno):
                self.assertEqual(r.out, {2: expect(errno)}, (tag, errno))
                self.assertIsNone(r.exit)
                self.check_footprint("perr", r, tag)

    def test_extra_string_and_program_name(self):
        for errno in (2, 17, 22, 99):
            for tag, r in self.perr(errno, extra=b"/home/some file", argv=("longername",)):
                self.assertEqual(r.out, {2: expect(errno, b"longername", b"/home/some file")}, (tag, errno))

    def test_builtin_messages_need_no_disk(self):
        for errno in BUILTIN:
            for tag, r in self.perr(errno, files={}):
                self.assertEqual(r.out, {2: expect(errno)}, (tag, errno))
                self.assertFalse([t for t in r.trace if t[0] != "WRITE"], "a built-in message touched the disk: %s" % (r.trace,))

    def test_missing_unreadable_or_odd_file_falls_back_to_error_n(self):
        odd = {
            "no file": {},
            "empty": {"/etc/errors": b""},
            "no newline at the end": {"/etc/errors": b"17 file exists"},
            "not a number": {"/etc/errors": b"x17 bad\n17x bad\n17 good\n"},
            "empty lines": {"/etc/errors": b"\n\n17 hit\n"},
            "text to the end": {"/etc/errors": b"3 a\n22 until eof"},
            "number only": {"/etc/errors": b"22\n22 two\n"},
            "leading zeros": {"/etc/errors": b"022 padded\n"},
            "first of two": {"/etc/errors": b"22 one\n22 two\n"},
            "just under 255 bytes of text": {"/etc/errors": b"22 " + b"t" * 250 + b"\n"},
        }
        for what, files in odd.items():
            for errno in (22, 17, 3, 99):
                for tag, r in self.perr(errno, files=files):
                    self.assertEqual(r.out, {2: expect(errno, data=files.get("/etc/errors", b""))}, (tag, what, errno))
                    self.check_footprint("perr", r, tag)

    def test_failures_while_reading(self):
        for errno in (22, 17, 39):
            for kw in (dict(open_fail={"/etc/errors": 5}), dict(read_fail=1), dict(read_fail=7), dict(chunk=1), dict(chunk=3)):
                for tag, r in self.perr(errno, **kw):
                    out = r.out[2]
                    self.assertTrue(out.startswith(b"prog: ") and out.endswith(b"\n"), (tag, errno, kw, out))
                    if "open_fail" in kw:
                        self.assertEqual(out, b"prog: error %d\n" % errno, (tag, errno, kw))
                    elif "read_fail" not in kw:
                        self.assertEqual(out, expect(errno), (tag, errno, kw))
                    self.check_footprint("perr", r, tag)

    def test_open_or_die(self):
        for tag, r in self.each("open_or_die", a=STR & 0xFF, x=STR >> 8, y=0, mem={STR: b"/etc/errors\0"}, files=self.FILES):
            self.assertIsNone(r.exit)
            self.assertEqual((r.c, r.out), (0, {}), tag)
            self.assertEqual(r.a, 3)
            self.check_footprint("open_or_die", r, tag)
        for tag, r in self.each("open_or_die", a=STR & 0xFF, x=STR >> 8, y=0, mem={STR: b"/no/such\0"}, files=self.FILES, argv=("cat",)):
            self.assertEqual(r.exit, 1, tag)
            self.assertEqual(r.out, {2: b"cat: /no/such: no such file or directory\n"}, tag)


if __name__ == "__main__":
    if os.environ.get("BREADBIN_LIB_MEASURE"):
        import atexit
        atexit.register(lambda: print("CLOBBER = {\n" + "".join("    %r: %r,\n" % (k, sorted(v)) for k, v in sorted(SEEN.items())) + "}"))
    unittest.main()
