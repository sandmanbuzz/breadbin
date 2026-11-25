"""SYS_LSEEK on the real kernel image in py65 (tools/uci_sim.py): c64fs files and directories, UCI
files against the fake Command Interface, and the descriptors that cannot seek.

Skips when py65 is not installed or the kernel has not been built (`make`). See docs/testing.md.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import uci_sim
    from uci_sim import FakeUCI, Sim
except ImportError:                         # py65 missing
    uci_sim = None

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")
BUILT = all(os.path.exists(os.path.join(BUILD, f)) for f in ("breadbin.prg", "kernel.lbl", "breadbin.d64"))
SKIP = "py65 not installed" if uci_sim is None else ("kernel not built (make)" if not BUILT else None)

O_RDONLY, O_WRONLY, O_RDWR, O_CREAT, O_TRUNC, O_APPEND = 0, 1, 2, 0x10, 0x20, 0x40
SEEK_SET, SEEK_CUR, SEEK_END = 0, 1, 2
MAXFILE = (12 + 128) * 256                  # c64fs: NDIRECT + one indirect block of 128
PATTERN = bytes((i * 7 + (i >> 8)) & 0xFF for i in range(5000))


def seek(s, fd, off, whence=SEEK_SET):
    """-> (errno or None, new position). The offset goes in as 24-bit two's complement; r1 hi
    is set to $A5 so the callers can check the call keeps it."""
    off &= 0xFFFFFF
    res = s.sys("LSEEK", a=fd, x=whence, r0=off & 0xFFFF, r1=off >> 16 | 0xA500)
    m = s.mem.b
    return s.errno(res), m[2] | m[3] << 8 | m[4] << 16


class Common:
    def make(self, path, data, flags=O_RDWR | O_CREAT | O_TRUNC):
        s = self.s
        fd = s.check(s.open(path, flags), "open " + path)
        for i in range(0, len(data), 1000):
            self.assertEqual(s.write(fd, data[i:i + 1000]), len(data[i:i + 1000]))
        return fd

    def ok(self, fd, off, whence=SEEK_SET):
        err, pos = seek(self.s, fd, off, whence)
        self.assertIsNone(err, "lseek(%d, %d, %d)" % (fd, off, whence))
        self.assertEqual(self.s.mem.b[5], 0xA5, "r1 hi kept")
        return pos

    def err(self, fd, off, whence=SEEK_SET):
        return seek(self.s, fd, off, whence)[0]


@unittest.skipIf(SKIP, SKIP)
class C64fs(Common, unittest.TestCase):
    def setUp(self):
        self.s = Sim(None)

    def test_set_cur_end_read(self):
        s = self.s
        fd = self.make("/tmp/p", PATTERN)
        self.assertEqual(self.ok(fd, 0, SEEK_CUR), len(PATTERN))      # tell
        self.assertEqual(self.ok(fd, 300), 300)
        self.assertEqual(s.read(fd, 10), PATTERN[300:310])
        self.assertEqual(self.ok(fd, -20, SEEK_CUR), 290)
        self.assertEqual(s.read(fd, 600), PATTERN[290:890])              # across a block
        self.assertEqual(self.ok(fd, 1000, SEEK_CUR), 1890)
        self.assertEqual(s.read(fd, 5), PATTERN[1890:1895])
        self.assertEqual(self.ok(fd, -100, SEEK_END), len(PATTERN) - 100)
        self.assertEqual(s.read_all(fd), PATTERN[-100:])
        self.assertEqual(self.ok(fd, 0, SEEK_END), len(PATTERN))
        self.assertEqual(s.read(fd, 10), b"")
        self.assertEqual(self.ok(fd, -len(PATTERN), SEEK_END), 0)
        self.assertEqual(s.read(fd, 4), PATTERN[:4])
        s.close(fd)

    def test_offset_bytes_beyond_16_bits(self):
        s = self.s
        fd = self.make("/tmp/p", PATTERN)
        self.assertEqual(self.ok(fd, 0x123456), 0x123456)
        self.assertEqual(s.read(fd, 10), b"")                              # past the end: 0 bytes
        self.assertEqual(self.ok(fd, -0x123456 + 7, SEEK_CUR), 7)
        self.assertEqual(s.read(fd, 3), PATTERN[7:10])
        self.assertEqual(self.ok(fd, 0x7FFFFF), 0x7FFFFF)                  # the largest offset
        self.assertEqual(self.ok(fd, 0x7FFFFF, SEEK_CUR), 0xFFFFFE)
        self.assertEqual(self.ok(fd, 1, SEEK_CUR), 0xFFFFFF)
        self.assertEqual(self.err(fd, 1, SEEK_CUR), "EINVAL")             # past 16 MB
        self.assertEqual(self.ok(fd, 0, SEEK_CUR), 0xFFFFFF)               # unchanged

    def test_refusals_leave_the_position(self):
        s = self.s
        fd = self.make("/tmp/p", PATTERN)
        self.ok(fd, 50)
        self.assertEqual(self.err(fd, -1), "EINVAL")
        self.assertEqual(self.err(fd, -51, SEEK_CUR), "EINVAL")
        self.assertEqual(self.err(fd, -len(PATTERN) - 1, SEEK_END), "EINVAL")
        self.assertEqual(self.err(fd, 0, 3), "EINVAL")
        self.assertEqual(self.err(fd, 0, 255), "EINVAL")
        self.assertEqual(s.read(fd, 4), PATTERN[50:54])
        s.close(fd)
        self.assertEqual(self.err(fd, 0), "EBADF")
        self.assertEqual(self.err(7, 0), "EBADF")
        self.assertEqual(self.err(200, 0), "EBADF")

    def test_overwrite_in_place(self):
        s = self.s
        fd = self.make("/tmp/w", PATTERN[:600])
        self.ok(fd, 254)
        s.write(fd, b"XYZW")                                               # across a block
        self.ok(fd, 0)
        want = PATTERN[:254] + b"XYZW" + PATTERN[258:600]
        self.assertEqual(s.read_all(fd), want)
        self.assertEqual(s.stat("/tmp/w")["size"], 600)
        s.close(fd)

    def test_write_past_the_end_reads_zeros(self):
        s = self.s
        fd = self.make("/tmp/h", b"ab")
        self.ok(fd, 200)                                                   # same block
        s.write(fd, b"c")
        self.ok(fd, 1000)                                                  # blocks 1 and 2 are holes
        s.write(fd, b"d")
        self.assertEqual(s.stat("/tmp/h")["size"], 1001)
        self.ok(fd, 0)
        want = b"ab" + bytes(198) + b"c" + bytes(799) + b"d"
        self.assertEqual(s.read_all(fd), want)
        s.close(fd)
        fd = s.check(s.open("/tmp/h"), "reopen")
        self.assertEqual(s.read_all(fd), want)

    def test_read_past_the_end_changes_nothing(self):
        s = self.s
        fd = self.make("/tmp/r", b"hello")
        self.ok(fd, 4000)
        self.assertEqual(s.read(fd, 100), b"")
        self.assertEqual(s.stat("/tmp/r")["size"], 5)

    def test_largest_file(self):
        s = self.s
        fd = self.make("/tmp/big", b"x")
        self.ok(fd, MAXFILE)
        self.assertEqual(s.errno(s.sys("WRITE", a=fd, r0=0x8100, r1=1)), "EFBIG")
        self.assertEqual(s.stat("/tmp/big")["size"], 1)
        self.ok(fd, MAXFILE - 1)
        s.write(fd, b"z")
        self.assertEqual(s.stat("/tmp/big")["size"], MAXFILE)
        self.ok(fd, -2, SEEK_END)
        self.assertEqual(s.read_all(fd), b"\0z")

    def test_append_still_appends(self):
        s = self.s
        fd = self.make("/tmp/a", b"0123", O_WRONLY | O_CREAT | O_TRUNC | O_APPEND)
        self.ok(fd, 1)
        s.write(fd, b"45")
        fd2 = s.check(s.open("/tmp/a"), "open")
        self.assertEqual(s.read_all(fd2), b"012345")

    def test_directory_rewinds(self):
        s = self.s
        fd = s.check(s.open("/"), "open /")
        first = s.read(fd, 32)
        s.read(fd, 64)
        self.assertEqual(self.ok(fd, 0), 0)
        self.assertEqual(s.read(fd, 32), first)
        self.assertEqual(self.ok(fd, -16, SEEK_END) % 16, 0)

    def test_not_seekable(self):
        s = self.s
        self.assertEqual(self.err(0, 0), "ESPIPE")                         # the console
        self.assertEqual(self.err(1, 0, SEEK_END), "ESPIPE")
        res = s.sys("PIPE")
        self.assertFalse(res[0])
        rd, wr = res[1], res[2]
        self.assertEqual(self.err(rd, 0), "ESPIPE")
        self.assertEqual(self.err(wr, 0), "ESPIPE")
        fd = s.check(s.open("/dev/null", O_RDWR), "open /dev/null")
        self.assertEqual(self.err(fd, 0), "ESPIPE")

    def test_cbm_dos_file_is_espipe(self):
        """A file on a CBM DOS disk keeps a track and sector in f_pos. The sim has no second
        drive, so this marks the open file's device as CBM DOS (dev_type 1) for the call."""
        s, m, L = self.s, self.s.mem.b, self.s.lbl
        fd = s.check(s.open("/etc/motd"), "open")
        ent = m[L["p_fd"] + fd]
        dev = m[L["f_dev"] + ent]
        old = m[L["dev_type"] + dev]
        m[L["dev_type"] + dev] = 1
        pos = [m[L[n] + ent] for n in ("f_pos0", "f_pos1", "f_pos2")]
        self.assertEqual(self.err(fd, 0), "ESPIPE")
        self.assertEqual([m[L[n] + ent] for n in ("f_pos0", "f_pos1", "f_pos2")], pos)
        m[L["dev_type"] + dev] = old


@unittest.skipIf(SKIP, SKIP)
class Uci(Common, unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="lseeksim")
        self.host = os.path.join(self.dir, "host")
        os.makedirs(os.path.join(self.host, "Temp", "sub"))
        with open(os.path.join(self.host, "Temp", "p.bin"), "wb") as f:
            f.write(PATTERN)
        self.u = FakeUCI(self.host)
        self.s = Sim(self.u)
        self.assertIsNone(self.s.errno(self.s.path_call("MKDIR", "/u")))
        self.assertIsNone(self.s.errno(self.s.mount_uci("/u")))

    def tearDown(self):
        self.assertEqual(self.u.leaks, 0, "OPEN on a target with a file still open")
        self.assertEqual(self.u.writes_while_busy, 0, "command bytes written while not idle")
        self.assertEqual(self.u.extends, 0, "a write-mode SEEK past the end (FatFs fills it with junk)")
        shutil.rmtree(self.dir)

    def hread(self, name):
        with open(os.path.join(self.host, "Temp", name), "rb") as f:
            return f.read()

    def test_set_cur_end_read(self):
        s = self.s
        fd = s.check(s.open("/u/Temp/p.bin"), "open")
        self.assertEqual(self.ok(fd, 300), 300)
        self.assertEqual(s.read(fd, 10), PATTERN[300:310])
        self.assertEqual(self.ok(fd, -20, SEEK_CUR), 290)
        self.assertEqual(s.read(fd, 600), PATTERN[290:890])
        self.assertEqual(self.ok(fd, -100, SEEK_END), len(PATTERN) - 100)
        self.assertEqual(s.read_all(fd), PATTERN[-100:])
        self.assertEqual(self.ok(fd, 0, SEEK_END), len(PATTERN))
        self.assertEqual(s.read(fd, 10), b"")
        self.assertEqual(self.ok(fd, 0), 0)
        self.assertEqual(s.read(fd, 4), PATTERN[:4])
        s.close(fd)

    def test_past_the_end_is_refused(self):
        s = self.s
        fd = s.check(s.open("/u/Temp/p.bin", O_RDWR), "open")
        self.ok(fd, 10)
        self.assertEqual(self.err(fd, len(PATTERN) + 1), "EINVAL")
        self.assertEqual(self.err(fd, 1, SEEK_END), "EINVAL")
        self.assertEqual(self.err(fd, -11, SEEK_CUR), "EINVAL")
        self.assertEqual(s.read(fd, 3), PATTERN[10:13])
        self.assertEqual(len(self.hread("p.bin")), len(PATTERN))
        s.close(fd)

    def test_overwrite_and_grow(self):
        s = self.s
        fd = s.check(s.open("/u/Temp/p.bin", O_RDWR), "open")
        self.ok(fd, 1000)
        s.write(fd, b"XYZ")
        self.assertEqual(self.ok(fd, -2, SEEK_CUR), 1001)
        self.assertEqual(s.read(fd, 4), b"YZ" + PATTERN[1003:1005])
        self.ok(fd, 0, SEEK_END)
        s.write(fd, b"tail")
        self.assertEqual(self.ok(fd, 0, SEEK_END), len(PATTERN) + 4)       # the size after a write
        self.ok(fd, -6, SEEK_END)
        self.assertEqual(s.read_all(fd), PATTERN[-2:] + b"tail")
        s.close(fd)
        self.assertEqual(self.hread("p.bin"), PATTERN[:1000] + b"XYZ" + PATTERN[1003:] + b"tail")

    def test_new_file(self):
        s = self.s
        fd = self.make("/u/Temp/n.bin", b"abcdef")
        self.assertEqual(self.ok(fd, -6, SEEK_END), 0)
        self.assertEqual(s.read_all(fd), b"abcdef")
        s.close(fd)

    def test_appends_through_one_descriptor(self):
        """Each O_APPEND write lands after the last one: FILE INFO still gives the size at the last
        close (H11), so the module must know what its own handle has written since."""
        s = self.s
        with open(os.path.join(self.host, "Temp", "log"), "wb") as f:
            f.write(b"0123456789")
        fd = s.check(s.open("/u/Temp/log", O_WRONLY | O_APPEND), "open")
        for chunk in (b"ab", b"cd", b"ef"):
            s.write(fd, chunk)
        self.assertEqual(self.ok(fd, 0, SEEK_CUR), 16)
        s.close(fd)
        self.assertEqual(self.hread("log"), b"0123456789abcdef")

    def test_appends_while_other_files_take_the_handles(self):
        """A's host handle is closed and reopened between its appends (two DOS targets, three
        files): after a reopen FILE INFO has the size its close wrote, and the mark starts again."""
        s = self.s
        a = self.make("/u/Temp/a.log", b"1", O_WRONLY | O_CREAT | O_TRUNC | O_APPEND)
        b = s.check(s.open("/u/Temp/p.bin"), "open b")
        c = s.check(s.open("/u/Temp/p.bin"), "open c")
        for k in range(3):
            s.write(a, b"%d" % (k + 2))
            self.assertEqual(s.read(b, 1), PATTERN[k:k + 1])
            self.assertEqual(s.read(c, 1), PATTERN[k:k + 1])
        s.write(a, b"5")
        self.assertEqual(self.ok(a, 0, SEEK_END), 5)
        for fd in (a, b, c):
            s.close(fd)
        self.assertEqual(self.hread("a.log"), b"12345")

    def test_tell_and_seek_back_in_a_file_still_being_written(self):
        s = self.s
        fd = s.check(s.open("/u/Temp/w.bin", O_RDWR | O_CREAT | O_TRUNC), "open")
        s.write(fd, b"header..body-body-body")
        self.assertEqual(self.ok(fd, 0, SEEK_CUR), 22)
        self.assertEqual(self.ok(fd, 0, SEEK_END), 22)
        self.assertEqual(self.ok(fd, 6), 6)
        s.write(fd, b"!!")
        self.assertEqual(self.ok(fd, 0, SEEK_END), 22)
        s.close(fd)
        self.assertEqual(self.hread("w.bin"), b"header!!body-body-body")

    def test_two_files_share_the_handles(self):
        """Seeks on one file while another holds the host's handles (uci_ensure reopens)."""
        s = self.s
        a = s.check(s.open("/u/Temp/p.bin"), "open a")
        b = self.make("/u/Temp/q.bin", b"0123456789")
        c = self.make("/u/Temp/r.bin", b"abcdefghij")
        self.ok(a, -5, SEEK_END)
        self.ok(b, 3)
        self.ok(c, -2, SEEK_END)
        self.assertEqual(s.read(a, 5), PATTERN[-5:])
        self.assertEqual(s.read(b, 2), b"34")
        self.assertEqual(s.read(c, 9), b"ij")
        for fd in (a, b, c):
            s.close(fd)

    def test_append_after_a_seek_still_appends(self):
        s = self.s
        with open(os.path.join(self.host, "Temp", "log"), "wb") as f:
            f.write(b"0123456789")
        fd = s.check(s.open("/u/Temp/log", O_WRONLY | O_APPEND), "open")
        self.assertEqual(self.ok(fd, 0), 0)
        s.write(fd, b"AB")
        self.assertEqual(self.ok(fd, 0, SEEK_CUR), 12)
        self.ok(fd, 3)
        s.write(fd, b"C")
        s.close(fd)
        self.assertEqual(self.hread("log"), b"0123456789ABC")

    def test_seek_does_not_move_the_host_past_a_shortened_end(self):
        """Descriptor A stands at 1000; B truncates the file to 2 bytes. Rewinding A asks the
        size, which must not SEEK A's write handle to 1000 first (FatFs would extend the file)."""
        s = self.s
        a = s.check(s.open("/u/Temp/p.bin", O_RDWR), "open a")
        self.ok(a, 1000)
        s.read(a, 1)                                    # the host stands at 1001 for A
        b = s.check(s.open("/u/Temp/p.bin", O_WRONLY | O_TRUNC), "open b")
        s.write(b, b"hi")
        s.close(b)
        self.assertEqual(self.ok(a, 0), 0)
        self.assertEqual(self.ok(a, 0, SEEK_END), 2)
        self.assertEqual(self.err(a, 3), "EINVAL")
        self.assertEqual(s.read_all(a), b"")
        s.close(a)
        self.assertEqual(self.hread("p.bin"), b"hi")

    def test_directory_positions_stay_below_64k(self):
        s = self.s
        fd = s.check(s.open("/u/Temp"), "open")
        self.assertEqual(self.ok(fd, 0xFFFF), 0xFFFF)
        self.assertEqual(s.read(fd, 16), b"")
        self.assertEqual(self.err(fd, 1, SEEK_CUR), "EINVAL")
        self.assertEqual(self.err(fd, 0x10003), "EINVAL")
        self.assertEqual(self.ok(fd, 0, SEEK_CUR), 0xFFFF)
        s.close(fd)

    def test_directory(self):
        s = self.s
        fd = s.check(s.open("/u/Temp"), "open")
        first = s.read(fd, 16)
        self.assertTrue(first)
        self.assertEqual(self.err(fd, 0, SEEK_END), "EINVAL")
        self.assertEqual(self.ok(fd, 0), 0)
        self.assertEqual(s.read(fd, 16), first)
        s.close(fd)


if __name__ == "__main__":
    unittest.main()
