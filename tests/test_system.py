"""End-to-end tests: boot Breadbin in VICE and drive the shell."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice, make_target  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")


class Boot(unittest.TestCase):
    """One VICE session for a sequence of checks (booting is the slow part)."""

    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = make_target(cls.img)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def run_(self, cmd):
        return self.v.run(cmd)

    def test_00_kernal_is_shadowed(self):
        """The KERNAL ROM is out: RAM at $E000-$FFFF, vectors are ours."""
        if self.v.sees_cpu_port:      # a DMA read of $0001 returns the RAM under the port
            self.assertEqual(self.v.mem(0x0001, 0x0001), [0x35])
        vec = self.v.mem(0xfffa, 0xffff)
        nmi, irq = vec[0] | vec[1] << 8, vec[4] | vec[5] << 8
        for target in (nmi, irq):
            self.assertTrue(0x8000 <= target < 0xcf00, hex(target))

    def test_01_banner(self):
        s = self.v.screen()
        self.assertIn("breadbin 0.2", s)
        self.assertIn("kpatronas@gmail.com", s)

    def test_02_echo(self):
        self.assertEqual(self.run_("echo hello world"), "hello world")

    def test_03_ls_bin(self):
        out = self.run_("ls /bin")
        for name in ["cat", "ls", "sh", "init", "grep"]:
            self.assertIn(name, out.split())

    def test_04_cat(self):
        out = self.run_("cat /etc/motd")
        self.assertIn("welcome to breadbin.", out)

    def test_05_pipe_three_stages(self):
        out = self.run_("cat /home/readme | grep unix | wc")
        expect = subprocess.run("grep unix rootfs/home/readme | wc", shell=True, cwd=ROOT,
                                capture_output=True, text=True).stdout.split()
        self.assertEqual(out.split(), expect)

    def test_06_redirect_roundtrip(self):
        self.run_("echo hi there > /home/note")
        self.assertEqual(self.run_("cat /home/note"), "hi there")
        self.run_("echo again >> /home/note")
        self.assertEqual(self.run_("cat /home/note"), "hi there\nagain")

    def test_07_directories(self):
        self.run_("mkdir /home/src")
        self.run_("cd /home/src")
        self.assertEqual(self.run_("pwd"), "/home/src")
        self.run_("echo x > f")
        self.assertEqual(self.run_("ls"), "f")
        self.run_("cd ..")
        self.assertEqual(self.run_("pwd"), "/home")
        self.assertIn("directory not empty", self.run_("rmdir src"))
        self.run_("rm src/f")
        self.assertEqual(self.run_("rmdir src"), "")
        self.assertNotIn("src", self.run_("ls").split())
        self.run_("cd /")

    def test_08_background_and_kill(self):
        out = self.run_("count > /dev/null &")
        pid = out.strip("[]")
        self.assertTrue(pid.isdigit(), out)
        ps = self.run_("ps")
        self.assertIn("count", ps)
        self.run_("kill " + pid)
        ps = self.run_("ps")
        self.assertNotIn("count", ps)

    def test_09_errors(self):
        self.assertIn("no such file", self.run_("cat /nope"))
        self.assertIn("not found", self.run_("nosuchcmd").replace(
            "no such file or directory", "not found"))

    def test_10_mv_cp(self):
        self.run_("cp /etc/motd /home/m2")
        self.run_("mv /home/m2 /home/m3")
        self.assertIn("welcome", self.run_("cat /home/m3"))
        self.assertIn("no such file", self.run_("cat /home/m2"))

    def test_11_head_pipe_early_exit(self):
        out = self.run_("cat /home/readme | head -3 | wc")
        self.assertEqual(out.split()[0], "3")

    def test_12_sigpipe(self):
        out = self.run_("ls /bin | head -2")
        self.assertEqual(len(out.splitlines()), 2)
        self.assertNotIn("ls", self.run_("ps").split()[5:])

    def test_13_ctrl_c_blocked_reader(self):
        # cat with no args blocks reading the console; RUN/STOP kills it
        self.v.type("clear\n")
        self.v.wait_for("$")
        self.v.type("cat\n")
        self.v.wait_for("$ cat")
        import time
        time.sleep(3)
        self.v.keybuf(b"\x03")
        self.v._wait(lambda ls: any(l.endswith(" $") for l in ls[1:]), 60)
        self.assertNotIn("cat", self.run_("ps").split()[5:])

    def test_14_ctrl_c_busy_foreground(self):
        import time

        def wait_lines(done, timeout=60):
            # wait for the screen to show something, not for text already on it
            end = time.time() + timeout
            while True:
                lines = [l for l in self.v.screen_lines() if l]
                if done(lines) or time.time() > end:
                    return lines
                time.sleep(0.2)

        self.v.type("clear\n")
        wait_lines(lambda l: l == ["/ $"])
        self.v.type("count\n")
        wait_lines(lambda l: "3" in l)                  # the line "3", not a 3 in the banner
        self.v.keybuf(b"\x03")
        self.assertEqual(wait_lines(lambda l: l[-1] == "/ $")[-1], "/ $")
        self.assertNotIn("count", self.run_("ps"))

    def test_15_too_many_processes(self):
        # init + login + sh + 9 jobs fill the 12-slot process table
        pids = []
        for _ in range(9):
            pids.append(self.run_("sleep 9999 &").strip("[]"))
        out = self.v.run("sleep 9999 &", clear=False)
        self.assertIn("too many processes", out)
        self.assertTrue(all(p.isdigit() for p in pids), pids)
        self.v.run("kill " + " ".join(pids[:5]), clear=False)
        self.v.run("kill " + " ".join(pids[5:]), clear=False)
        self.assertEqual(self.run_("echo alive"), "alive")
        self.assertNotIn("sleep", self.run_("ps"))

    def test_16_paths(self):
        self.assertIn("cat", self.run_("ls /bin/").split())
        self.run_("cd /..")
        self.assertEqual(self.run_("pwd"), "/")
        self.assertIn("too long", self.run_("echo x > /home/abcdefghijklmnop").replace("\n", ""))
        self.assertIn("not a directory", self.run_("ls /etc/motd/x"))

    def test_17_basic_script(self):
        out = self.run_("basic /home/hello.bas")
        self.assertIn("5 squared is 25", out)
        self.assertIn("fib: 0 1 1 2 3 5 8 13 21 34", out)

    def test_18_basic_pipe(self):
        self.assertEqual(self.run_("echo 'print 6*7' | basic"), "42")
        self.assertIn("division by zero", self.run_("echo 'print 1/0' | basic"))

    def test_19_assembler(self):
        out = self.run_("as /home/hello.s /home/hello")
        self.assertIn("bytes", out)
        self.assertEqual(self.run_("/home/hello"), "hello, world! (assembled on a c64)")

    def test_20_more_pages(self):
        self.v.type("clear\n")
        self.v.wait_for("$")
        self.v.type("ls -l /bin | more\n")
        s = self.v.wait_for("--more--")
        self.assertIn("basic", s)
        self.v.type("q\n")
        self.v._wait(lambda ls: ls[-1].endswith(" $") or any(
            l.endswith(" $") for l in ls[-3:]), 60)

    def test_21_many_sleepers_stay_responsive(self):
        pids = [self.run_("sleep 9999 &").strip("[]") for _ in range(6)]
        import time
        t = time.time()
        self.assertEqual(self.run_("echo quick"), "quick")
        self.assertLess(time.time() - t, 30)
        self.v.run("kill " + " ".join(pids), clear=False)

    def test_22_easy_commands(self):
        self.assertEqual(self.run_("whoami"), "root")
        self.assertTrue(self.run_("uptime").startswith("up "))
        self.run_("date 13:45:10")
        self.assertTrue(self.run_("date").startswith("13:4"))
        self.assertEqual(self.run_("version"), "breadbin 0.2 by kpatronas@gmail.com")
        size = os.path.getsize(os.path.join(ROOT, "rootfs", "etc", "motd"))
        self.assertIn("size: %d" % size, self.run_("stat /etc/motd"))
        self.assertIn("0000: 77 65 6c 63", self.run_("hexdump /etc/motd | head -1"))
        self.assertIn("themes:", self.run_("theme nosuch"))
        self.run_("theme green")

    def test_23_wildcards_and_jobs(self):
        self.assertEqual(self.run_("echo /home/*.bas"), "/home/hello.bas")
        self.assertEqual(self.run_("echo /bin/s?"), "/bin/sh")
        self.assertEqual(self.run_("echo /nomatch*"), "/nomatch*")
        pid = self.run_("sleep 999 &").strip("[]")
        self.assertIn("[" + pid + "] running  sleep", self.run_("jobs"))
        self.run_("kill " + pid)

    def test_24_editor(self):
        import time
        self.v.type("clear\n")
        self.v.wait_for("$")
        self.v.type("edit /home/e.txt\n")
        self.v.wait_for("edit:", timeout=60)
        self.v.type("hello\nworld")
        time.sleep(2)
        self.v.keybuf(b"\x91\x1d\x1dX")   # up, right, right, X
        time.sleep(2)
        self.v.keybuf(b"\x0f")                  # ^O save
        self.v.wait_for(" saved")
        self.v.keybuf(b"\x18")                  # ^X quit
        time.sleep(3)
        self.assertEqual(self.run_("cat /home/e.txt | wc"), "     1      2     12")

    def test_25_login_password(self):
        import time
        self.v.type("clear\npasswd\n")
        self.v.wait_for("new password:")
        self.v.type("secret\n")
        self.v.wait_for("again:")
        self.v.type("secret\n")
        self.v.wait_for("password changed")
        self.v.type("exit\n")                         # log out: back to login
        self.v.wait_for("login:")
        self.v.type("root\n")
        self.v.wait_for("password:")
        self.v.type("wrong\n")
        self.v.wait_for("login incorrect")
        self.v.type("root\n")
        self.v.wait_for("password:")
        self.v.type("secret\n")
        time.sleep(4)
        self.assertEqual(self.run_("whoami"), "root")
        self.assertIn("root:", self.run_("cat /etc/passwd"))


class Persistence(unittest.TestCase):
    """Files written by Breadbin survive a reboot and are readable on the host."""

    def test_write_reboot_read(self):
        img = os.path.join(ROOT, "build", "persist.d64")
        with open(IMAGE, "rb") as f, open(img, "wb") as g:
            g.write(f.read())
        with Vice(img) as v:
            v.wait_shell()
            v.run("mkdir /home/keep")
            v.run("echo persistent data > /home/keep/f")
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"),
                              "cat", img, "/home/keep/f"], capture_output=True, text=True)
        self.assertEqual(out.stdout, "persistent data\n")
        with Vice(img) as v:
            v.wait_shell()
            self.assertEqual(v.run("cat /home/keep/f"), "persistent data")


class REU(unittest.TestCase):
    """With an REU: /tmp is a RAM disk."""

    def test_tmp_ramdisk(self):
        with Vice(IMAGE, reu=True) as v:
            v.wait_shell()
            self.assertIn("reu: 8 x 64k", v.screen())
            self.assertIn("/tmp", v.run("df"))
            v.run("echo hi > /tmp/x")
            self.assertEqual(v.run("cat /tmp/x"), "hi")
            v.run("mkdir /tmp/d")
            v.run("cd /tmp/d")
            v.run("cd ../..")
            self.assertEqual(v.run("pwd"), "/")
            self.assertIn("home", v.run("ls /tmp/..").split())
            self.assertIn("exists", v.run("mkdir /tmp/d"))


def c1541_dir(img):
    out = subprocess.run(["c1541", img, "-dir"], capture_output=True, text=True).stdout
    return out


class Cache(unittest.TestCase):
    """The REU block cache: a second boot on the same REU reads from it, a different
    disk discards it, writes stay in step."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.img = os.path.join(self.tmp.name, "disk.d64")
        self.reu = os.path.join(self.tmp.name, "reu.img")
        shutil.copy(IMAGE, self.img)

    def tearDown(self):
        self.tmp.cleanup()

    def boot(self, *cmds):
        """Boot once with the shared REU image (2 MB); run cmds, then `cache`: its counters."""
        with Vice(self.img, reu=2048, reu_image=self.reu) as v:
            v.wait_shell()
            outs = [v.run(c) for c in cmds]
            return outs, self.stat(v.run("cache"))

    @staticmethod
    def stat(text):
        m = re.search(r"reu cache: (\w+)(?:\s+hits (\d+)\s+bus reads (\d+)\s+bus errors (\d+))?", text)
        assert m, text
        return m.group(1), *(int(x) for x in m.groups()[1:] if x is not None)

    def test_warm_boot_hits(self):
        state, hits, misses, errs = self.boot()[1]
        self.assertEqual(state, "on")
        self.assertGreater(misses, 20)      # cold: everything came from the bus
        self.assertEqual(errs, 0)
        state, hits2, misses2, errs = self.boot()[1]
        self.assertGreater(hits2, 20)
        self.assertLess(misses2, 5)
        self.assertEqual(errs, 0)

    def test_new_disk_discards(self):
        self.boot()
        with open(self.img, "r+b") as f:    # another build: a different id
            f.seek(376 * 256 + 15)
            f.write(b"\xde\xad\xbe\xef")
        _, hits, misses, _ = self.boot()[1]
        self.assertGreater(misses, 20)
        self.assertLess(hits, misses)

    def test_new_label_discards(self):
        self.boot()
        with open(self.img, "r+b") as f:    # same build id, another disk label
            f.seek(357 * 256 + 0x90)
            f.write(b"OTHERDISK")
        _, hits, misses, _ = self.boot()[1]
        self.assertGreater(misses, 20)
        self.assertLess(hits, misses)

    def test_pristine_disk_after_writes(self):
        """The hardware flow: a session writes, then the pristine image is mounted again
        on the same (warm) REU. Nothing the earlier session wrote may show up."""
        self.boot("echo x > /home/f")
        shutil.copy(IMAGE, self.img)
        outs, (_, hits, misses, errs) = self.boot("ls /home")
        self.assertNotIn("f", outs[0].split())
        self.assertGreater(misses, 20)
        self.assertEqual(errs, 0)
        outs, _ = self.boot("echo y > /home/g", "ls /home")
        self.assertIn("g", outs[1].split())
        self.assertNotIn("f", outs[1].split())

    def test_write_through(self):
        self.boot("echo one > /home/f")
        outs, _ = self.boot("cat /home/f", "echo two > /home/f")
        self.assertEqual(outs[0], "one")
        outs, (_, hits, misses, _) = self.boot("cat /home/f")
        self.assertEqual(outs[0], "two")
        self.assertGreater(hits, misses)

    def test_off_and_flush(self):
        self.boot()
        with Vice(self.img, reu=2048, reu_image=self.reu) as v:
            v.wait_shell()
            v.run("cache off")
            st = self.stat(v.run("cache"))
            self.assertEqual(st[0], "off")
            h = st[1]               # taken once it is off: loading `cache off` itself hit
            v.run("ls /bin")
            self.assertEqual(self.stat(v.run("cache"))[1], h)    # no hits while off
            v.run("cache on")
            self.assertEqual(self.stat(v.run("cache"))[0], "on")
            v.run("cache flush")
            m = self.stat(v.run("cache"))[2]
            v.run("ls /bin")
            self.assertGreater(self.stat(v.run("cache"))[2], m)   # flushed: back to the bus

    def test_no_reu(self):
        with Vice(self.img) as v:
            v.wait_shell()
            self.assertEqual(self.stat(v.run("cache"))[0], "none")
            self.assertIn("usage", v.run("cache bogus"))

    def test_small_reu(self):
        with Vice(self.img, reu=256) as v:      # 4 banks: /tmp works, no room for the cache
            v.wait_shell()
            self.assertEqual(self.stat(v.run("cache"))[0], "none")
            v.run("echo hi > /tmp/x")
            self.assertEqual(v.run("cat /tmp/x"), "hi")

    def test_cache0_kernel_has_no_cache(self):
        img = os.path.join(ROOT, "build0", "breadbin.d64")
        subprocess.run(["make", "BUILD=build0", "CACHE=0"], cwd=ROOT, check=True,
                       capture_output=True)
        with Vice(img, reu=2048) as v:
            v.wait_shell()
            self.assertEqual(self.stat(v.run("cache"))[0], "none")


class Drives(unittest.TestCase):
    """mount: normal C64 disks and Breadbin disks on drive 9."""

    def test_cbm_disk(self):
        cbm = os.path.join(ROOT, "build", "t_cbm9.d64")
        if os.path.exists(cbm):
            os.unlink(cbm)
        subprocess.run(["c1541", "-format", "cbmdisk,cb", "d64", cbm,
                        "-write", os.path.join(ROOT, "rootfs", "etc", "motd"), "motd,s",
                        "-write", os.path.join(ROOT, "rootfs", "home", "readme"), "readme,s"],
                       capture_output=True, check=True)
        with Vice(IMAGE, extra=["-drive9type", "1541", "-9", cbm]) as v:
            v.wait_shell()
            self.assertEqual(v.run("mount 9 /mnt"), "")
            self.assertIn("drive 9 on /mnt (cbm dos)", v.run("mount"))
            self.assertEqual(v.run("ls /mnt").split(), ["motd", "readme"])
            self.assertIn("welcome to breadbin.", v.run("cat /mnt/motd"))
            v.run("cp /etc/help /mnt/help")
            v.run("rm /mnt/motd")
            v.run("mv /mnt/help /mnt/h2")
            self.assertEqual(v.run("ls /mnt").split(), ["readme", "h2"])
            self.assertIn("/mnt", v.run("df"))
            self.assertIn("operation not permitted", v.run("mkdir /mnt/d"))
            v.run("umount /mnt")
        d = c1541_dir(cbm)
        self.assertIn('"h2"', d)
        self.assertNotIn('"motd"', d)
        out = os.path.join(ROOT, "build", "t_h2.txt")
        subprocess.run(["c1541", cbm, "-read", "h2,s", out], capture_output=True)
        with open(out, "rb") as f, open(os.path.join(ROOT, "rootfs", "etc", "help"), "rb") as g:
            self.assertEqual(f.read(), g.read())

    def test_breadbin_disk(self):
        img9 = os.path.join(ROOT, "build", "t_c64fs9.d64")
        with open(IMAGE, "rb") as f, open(img9, "wb") as g:
            g.write(f.read())
        with Vice(IMAGE, extra=["-drive9type", "1541", "-9", img9]) as v:
            v.wait_shell()
            v.run("mount 9 /mnt")
            self.assertIn("drive 9 on /mnt (c64fs)", v.run("mount"))
            v.run("mkdir /mnt/x")
            v.run("echo hi > /mnt/x/f")
            self.assertEqual(v.run("cat /mnt/x/f"), "hi")
            self.assertEqual(v.run("/mnt/bin/echo from drive 9"), "from drive 9")
            v.run("cd /mnt/x")
            self.assertIn("device busy", v.run("umount /mnt"))
            v.run("cd ../..")
            self.assertEqual(v.run("pwd"), "/")
            self.assertEqual(v.run("umount /mnt"), "")
            self.assertIn("no such device", v.run("mount 10 /mnt"))
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"),
                              "cat", img9, "/x/f"], capture_output=True, text=True)
        self.assertEqual(out.stdout, "hi\n")

    def test_boot_from_drive_9(self):
        """The root disk is on the drive we booted from, not always drive 8."""
        with Vice(IMAGE, boot_device=9) as v:
            v.wait_shell()
            self.assertEqual(v.run("mount").splitlines()[0], "drive 9 on / (c64fs)")
            self.assertIn("busy", v.run("mount 9 /mnt"))        # the running system's drive
            v.run("echo hi > /home/x")
            self.assertEqual(v.run("cat /home/x"), "hi")

    def test_format(self):
        blank = os.path.join(ROOT, "build", "t_blank9.d64")
        with open(blank, "wb") as f:
            f.write(bytes(174848))
        with Vice(IMAGE, extra=["-drive9type", "1541", "-9", blank]) as v:
            v.wait_shell()
            self.assertIn("no such device", v.run("mount 9 /mnt"))
            self.assertIn("only drives 9, 10 and 11", v.run("format 8").replace("\n", " "))
            v.type("clear\nformat 9 c64fs mydisk\n")
            v.wait_for("(y/n)")
            v.type("y\n")
            v.wait_for("done", timeout=400)
            v.run("mount 9 /mnt")
            v.run("mkdir /mnt/src")
            v.run("echo hello > /mnt/src/f")
            self.assertEqual(v.run("cat /mnt/src/f"), "hello")
            v.run("umount /mnt")
            v.type("clear\nformat 9 cbm plain\n")
            v.wait_for("(y/n)")
            v.type("y\n")
            v.wait_for("done", timeout=400)
            v.run("mount 9 /mnt")
            self.assertIn("(cbm dos)", v.run("mount"))
            v.run("echo hi > /mnt/note")
            v.run("umount /mnt")
        d = c1541_dir(blank)
        self.assertIn('"plain', d)
        self.assertIn('"note"', d)


if __name__ == "__main__":
    unittest.main()
