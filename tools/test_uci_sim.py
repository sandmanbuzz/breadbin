"""UCI v1 against a fake Command Interface: the real kernel image in py65 (tools/uci_sim.py).

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
    from uci_sim import FakeUCI, Sim, cx_image
except ImportError:                         # py65 missing
    uci_sim = None

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")
BUILT = all(os.path.exists(os.path.join(BUILD, f)) for f in ("breadbin.prg", "kernel.lbl", "breadbin.d64"))
SKIP = "py65 not installed" if uci_sim is None else ("kernel not built (make)" if not BUILT else None)

O_RDONLY, O_WRONLY, O_RDWR, O_CREAT, O_TRUNC, O_APPEND = 0, 1, 2, 0x10, 0x20, 0x40
T_FILE, T_DIR = 1, 2
PATTERN = bytes((i * 7 + (i >> 8)) & 0xFF for i in range(32768))


@unittest.skipIf(SKIP, SKIP)
class Classic(unittest.TestCase):
    """No Command Interface: the kernel never touches $DF1B-$DF1F except the mount probe."""

    def test_boot_and_files_never_touch_the_registers(self):
        s = Sim(None)
        self.assertEqual(s.mem.touch, [])
        fd = s.check(s.open("/etc/motd"), "open")
        self.assertIn(b"welcome to breadbin.", s.read_all(fd))
        s.close(fd)
        self.assertEqual(s.errno(s.path_call("MKDIR", "/u")), None)
        s.check(s.open("/u/f", O_WRONLY | O_CREAT), "create")
        self.assertEqual(s.mem.touch, [])

    def test_mount_uci_says_no_such_device(self):
        s = Sim(None)
        s.mem.b[0xDF1D] = 0xFF                  # an REU's unused register, or open bus
        self.assertEqual(s.errno(s.mount_uci("/mnt")), "ENODEV")
        self.assertEqual(s.mem.touch, [("r", 0xDF1D)])     # one ID read, nothing written
        self.assertIsNone(s.mntinfo(3))
        self.assertEqual(s.errno(s.mount_uci("/nonexistent")), "ENODEV")   # probe first

    def test_open_bus_c9_without_an_interface(self):
        s = Sim(None)
        s.mem.b[0xDF1C:0xDF20] = bytes([0xC9] * 4)  # open bus showing $C9 everywhere
        self.assertEqual(s.errno(s.mount_uci("/mnt")), "ENODEV")    # IDENTIFY times out
        self.assertIsNone(s.mntinfo(3))


@unittest.skipIf(SKIP, SKIP)
class Mounted(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ucisim")
        self.host = os.path.join(self.dir, "host")
        os.makedirs(os.path.join(self.host, "Temp", "sub"))
        with open(os.path.join(self.host, "Temp", "pattern.bin"), "wb") as f:
            f.write(PATTERN)
        with open(os.path.join(self.host, "Temp", "hello.txt"), "wb") as f:
            f.write(b"hello from the ultimate\n")
        with open(os.path.join(self.host, "Temp", "a-rather-long-file-name.txt"), "wb") as f:
            f.write(b"long\n")
        self.u = FakeUCI(self.host)
        self.s = Sim(self.u)
        self.assertIsNone(self.s.errno(self.s.path_call("MKDIR", "/u")))
        self.assertIsNone(self.s.errno(self.s.mount_uci("/u")))

    def tearDown(self):
        self.assertEqual(self.u.leaks, 0, "OPEN on a target with a file still open")
        self.assertEqual(self.u.writes_while_busy, 0, "command bytes written while not idle")
        shutil.rmtree(self.dir)

    def h(self, *p):
        return os.path.join(self.host, *p)

    def hread(self, *p):
        with open(self.h(*p), "rb") as f:
            return f.read()

    def test_mount_listed(self):
        self.assertEqual(self.s.mntinfo(3), (0, 0x80, "/u"))
        self.assertEqual(self.s.errno(self.s.mount_uci("/mnt")), "EBUSY")

    def test_ls(self):
        s = self.s
        self.assertEqual(s.listdir("/u"), [(3, "Temp")])
        self.assertEqual(s.listdir("/u/Temp"), [(2, "a-rather-long~"), (2, "hello.txt"), (2, "pattern.bin"), (3, "sub")])
        self.assertEqual(s.listdir("/u/Temp", chunk=256), s.listdir("/u/Temp"))
        self.assertEqual(s.listdir("/u/Temp/sub"), [])
        st = s.stat("/u/Temp")
        self.assertEqual((st["type"], st["dev"]), (T_DIR, 5))
        st = s.stat("/u/Temp/pattern.bin")
        self.assertEqual((st["type"], st["size"]), (T_FILE, 32768))
        st = s.stat("/u")
        self.assertEqual((st["type"], st["ino"]), (T_DIR, 1))
        self.assertEqual(s.stat("/u/Temp/a-rather-long-file-name.txt")["size"], 5)   # full name works

    def test_cat(self):
        s = self.s
        fd = s.check(s.open("/u/Temp/pattern.bin"), "open")
        self.assertEqual(s.read_all(fd, 1000), PATTERN)
        self.assertEqual(s.read(fd, 100), b"")                          # past the end
        s.close(fd)
        fd = s.check(s.open("/u/Temp/pattern.bin"), "open")
        self.assertEqual(s.read(fd, 0x700), PATTERN[:0x700])            # one request, 4 packets
        s.close(fd)
        # the probe's handle was adopted: OPEN once per open() here, never twice
        self.assertEqual(sum(1 for t, op, _ in self.u.log if op == 0x02), 2)

    def test_errors(self):
        s = self.s
        self.assertEqual(s.errno(s.open("/u/Temp/missing")), "ENOENT")
        self.assertEqual(s.errno(s.open("/u/nodir/missing")), "ENOENT")
        self.assertEqual(s.errno(s.open("/u/Temp", O_WRONLY)), "EISDIR")
        self.assertEqual(s.errno(s.stat("/u/Temp/missing")), "ENOENT")
        self.assertEqual(s.errno(s.open("/u/Temp/missing", O_WRONLY)), "ENOENT")
        fd = s.check(s.open("/u/Temp/hello.txt"), "open")
        self.assertEqual(s.errno(s.sys("WRITE", a=fd, r0=0x9100, r1=1)), "EBADF")
        s.close(fd)

    def test_write_and_read_back(self):
        s = self.s
        data = bytes(range(256)) * 6 + b"tail"
        fd = s.check(s.open("/u/Temp/new.bin", O_WRONLY | O_CREAT | O_TRUNC), "create")
        self.assertEqual(s.write(fd, data[:1000]), 1000)
        self.assertEqual(s.write(fd, data[1000:]), len(data) - 1000)
        s.close(fd)
        self.assertEqual(self.hread("Temp", "new.bin"), data)
        self.assertEqual(s.stat("/u/Temp/new.bin")["size"], len(data))
        fd = s.check(s.open("/u/Temp/new.bin"), "open")
        self.assertEqual(s.read_all(fd), data)
        s.close(fd)
        # O_TRUNC on an existing file, then O_APPEND
        fd = s.check(s.open("/u/Temp/new.bin", O_WRONLY | O_TRUNC), "trunc")
        s.write(fd, b"one\n")
        s.close(fd)
        fd = s.check(s.open("/u/Temp/new.bin", O_WRONLY | O_APPEND), "append")
        s.write(fd, b"two\n")
        s.close(fd)
        self.assertEqual(self.hread("Temp", "new.bin"), b"one\ntwo\n")
        # O_WRONLY without O_TRUNC overwrites in place
        fd = s.check(s.open("/u/Temp/new.bin", O_WRONLY), "open")
        s.write(fd, b"ONE")
        s.close(fd)
        self.assertEqual(self.hread("Temp", "new.bin"), b"ONE\ntwo\n")

    def test_100k_write(self):
        s = self.s
        data = bytes((i * 13) & 0xFF for i in range(102400))
        fd = s.check(s.open("/u/Temp/big", O_WRONLY | O_CREAT | O_TRUNC), "create")
        for i in range(0, len(data), 0x700):
            s.write(fd, data[i:i + 0x700])
        s.close(fd)
        self.assertEqual(self.hread("Temp", "big"), data)
        self.assertEqual(s.stat("/u/Temp/big")["size"], 102400)

    def test_relative_paths_and_cwd(self):
        s = self.s
        s.check(s.path_call("CHDIR", "/u/Temp"), "chdir")
        self.assertEqual(s.getcwd(), "/u/Temp")
        fd = s.check(s.open("rel.txt", O_WRONLY | O_CREAT), "create rel")
        s.write(fd, b"relative\n")
        s.close(fd)
        self.assertEqual(self.hread("Temp", "rel.txt"), b"relative\n")
        fd = s.check(s.open("./sub/../hello.txt"), "open rel")
        self.assertEqual(s.read_all(fd), b"hello from the ultimate\n")
        s.close(fd)
        self.assertIn((2, "rel.txt"), s.listdir("."))
        s.check(s.path_call("CHDIR", "sub"), "chdir sub")
        self.assertEqual(s.getcwd(), "/u/Temp/sub")
        s.check(s.path_call("CHDIR", ".."), "chdir ..")
        s.check(s.path_call("CHDIR", ".."), "chdir ..")
        self.assertEqual(s.getcwd(), "/u")
        self.assertEqual(s.stat(".")["ino"], 1)
        # walking out of the mount with ".." reaches c64fs
        fd = s.check(s.open("../etc/motd"), "open ../etc/motd")
        self.assertIn(b"welcome to breadbin.", s.read_all(fd))
        s.close(fd)
        fd = s.check(s.open("/u/../etc/motd"), "open /u/../etc/motd")
        s.close(fd)
        s.check(s.path_call("CHDIR", ".."), "chdir out")
        self.assertEqual(s.getcwd(), "/")
        self.assertEqual(s.stat("/etc/motd")["dev"], 0)

    def test_unlink_mkdir_rmdir(self):
        s = self.s
        self.assertIsNone(s.errno(s.path_call("UNLINK", "/u/Temp/hello.txt")))
        self.assertFalse(os.path.exists(self.h("Temp", "hello.txt")))
        self.assertEqual(s.errno(s.path_call("UNLINK", "/u/Temp/hello.txt")), "ENOENT")
        self.assertEqual(s.errno(s.path_call("UNLINK", "/u/Temp/sub")), "EISDIR")
        self.assertIsNone(s.errno(s.path_call("MKDIR", "/u/Temp/d")))
        self.assertTrue(os.path.isdir(self.h("Temp", "d")))
        self.assertEqual(s.errno(s.path_call("MKDIR", "/u/Temp/d")), "EEXIST")
        self.assertEqual(s.errno(s.path_call("MKDIR", "/u/nodir/d")), "ENOENT")
        fd = s.check(s.open("/u/Temp/d/f", O_WRONLY | O_CREAT), "create")
        s.close(fd)
        self.assertEqual(s.errno(s.path_call("RMDIR", "/u/Temp/d")), "ENOTEMPTY")
        self.assertEqual(s.errno(s.path_call("RMDIR", "/u/Temp/d/f")), "ENOTDIR")
        self.assertEqual(s.errno(s.path_call("RMDIR", "/u/Temp/d/.")), "EINVAL")
        self.assertEqual(s.errno(s.path_call("RMDIR", "/u/Temp/missing")), "ENOENT")
        s.check(s.path_call("UNLINK", "/u/Temp/d/f"), "unlink")
        self.assertIsNone(s.errno(s.path_call("RMDIR", "/u/Temp/d")))
        self.assertFalse(os.path.exists(self.h("Temp", "d")))

    def test_rename(self):
        s = self.s
        self.assertIsNone(s.errno(s.path_call("RENAME", "/u/Temp/hello.txt", "/u/Temp/sub/h2")))
        self.assertEqual(self.hread("Temp", "sub", "h2"), b"hello from the ultimate\n")
        self.assertFalse(os.path.exists(self.h("Temp", "hello.txt")))
        self.assertEqual(s.errno(s.path_call("RENAME", "/u/Temp/missing", "/u/Temp/x")), "ENOENT")
        self.assertEqual(s.errno(s.path_call("RENAME", "/u/Temp/pattern.bin", "/u/Temp/sub/h2")), "EEXIST")
        self.assertEqual(s.errno(s.path_call("RENAME", "/u/Temp/pattern.bin", "/home/p")), "EXDEV")
        self.assertEqual(s.errno(s.path_call("RENAME", "/etc/motd", "/u/Temp/m")), "EXDEV")
        s.check(s.path_call("CHDIR", "/u/Temp"), "chdir")
        self.assertIsNone(s.errno(s.path_call("RENAME", "sub", "sub2")))
        self.assertTrue(os.path.isdir(self.h("Temp", "sub2")))

    def test_many_open_files(self):
        """Three files at once on two host handles: evictions reopen and seek."""
        s = self.s
        a = s.check(s.open("/u/Temp/pattern.bin"), "a")
        b = s.check(s.open("/u/Temp/pattern.bin"), "b")
        c = s.check(s.open("/u/Temp/out", O_WRONLY | O_CREAT), "c")
        got_a, got_b = b"", b""
        for i in range(8):
            got_a += s.read(a, 300)
            got_b += s.read(b, 500)
            s.write(c, got_a[-300:])
        self.assertEqual(got_a, PATTERN[:2400])
        self.assertEqual(got_b, PATTERN[:4000])
        for fd in (a, b, c):
            s.close(fd)
        self.assertEqual(self.hread("Temp", "out"), PATTERN[:2400])
        self.assertTrue(any(op == 0x06 for _, op, _ in self.u.log), "no SEEK after an eviction")

    def test_too_many_and_umount(self):
        s = self.s
        fds = [s.check(s.open("/u/Temp/hello.txt"), "open %d" % i) for i in range(5)]
        self.assertEqual(s.errno(s.open("/u/Temp/hello.txt")), "EMFILE")
        self.assertEqual(s.errno(s.path_call("UMOUNT", "/u")), "EBUSY")
        for fd in fds:
            s.close(fd)
        s.check(s.path_call("CHDIR", "/u/Temp"), "chdir")
        self.assertEqual(s.errno(s.path_call("UMOUNT", "/u")), "EBUSY")
        s.check(s.path_call("CHDIR", "/"), "chdir")
        free = s.mem.b[s.lbl["free_pages"]]
        self.assertIsNone(s.errno(s.path_call("UMOUNT", "/u")))
        self.assertEqual(s.mem.b[s.lbl["free_pages"]], free + 1)       # the path page is back
        self.assertIsNone(s.mntinfo(3))
        self.assertTrue(all(t.file is None for t in self.u.targets.values()))
        self.assertEqual(s.errno(s.open("/u/Temp/hello.txt")), "ENOENT")   # c64fs /u again
        self.assertIsNone(s.errno(s.mount_uci("/u")))
        fd = s.check(s.open("/u/Temp/hello.txt"), "open after remount")
        s.close(fd)

    def test_run_a_program(self):
        s = self.s
        with open(os.path.join(BUILD, "root", "bin", "echo"), "rb") as f:
            prog = f.read()
        with open(self.h("Temp", "echo"), "wb") as f:
            f.write(prog)
        for path, cwd in (("/u/Temp/echo", "/"), ("./echo", "/u/Temp")):
            s.check(s.path_call("CHDIR", cwd), "chdir")
            pid = s.check(s.spawn(path), "spawn " + path)
            slot = [i for i in range(12) if s.mem.b[s.lbl["p_pid"] + i] == pid and s.mem.b[s.lbl["p_state"] + i]][0]
            base = s.mem.b[s.lbl["p_mpage"] + slot]
            img, _ = cx_image(prog, base)
            self.assertEqual(bytes(s.mem.b[base * 256:base * 256 + len(img)]), img)
            self.assertEqual(s.mem.b[s.lbl["p_cwddev"] + slot], 5 if cwd != "/" else 0)
        with open(self.h("Temp", "notcx"), "wb") as f:
            f.write(b"plain text, not a program\n")
        self.assertEqual(s.errno(s.spawn("/u/Temp/notcx")), "ENOEXEC")
        self.assertEqual(s.errno(s.spawn("/u/Temp/missing")), "ENOENT")
        self.assertEqual(s.errno(s.spawn("/u/Temp")), "ENOEXEC")

    def test_c64fs_unchanged_while_mounted(self):
        s = self.s
        fd = s.check(s.open("/home/x", O_WRONLY | O_CREAT | O_TRUNC), "create")
        s.write(fd, b"on c64fs\n")
        s.close(fd)
        fd = s.check(s.open("/home/x"), "open")
        self.assertEqual(s.read_all(fd), b"on c64fs\n")
        s.close(fd)
        self.assertEqual(s.stat("/home/x")["dev"], 0)
        names = [n for _, n in s.listdir("/bin")]
        self.assertIn("echo", names)
        self.assertEqual(s.errno(s.path_call("RENAME", "/home/x", "/u/Temp/x")), "EXDEV")


if __name__ == "__main__":
    unittest.main()
