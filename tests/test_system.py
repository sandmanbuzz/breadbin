"""End-to-end tests: boot Breadbin in VICE and drive the shell."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
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
        self.assertIn("breadbox 0.1", s)
        self.assertIn("based on breadbin by kpatronas@gmail.com", s)
        self.assertIn("based on breadbin by kpatronas@gmail.com\nmemory:", s)

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
        out_mkdir = self.run_("mkdir /home/src")
        out_cd = self.run_("cd /home/src")
        self.assertEqual(self.run_("pwd"), "/home/src",
                         msg=f"mkdir printed {out_mkdir!r}, cd printed {out_cd!r}")
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
        # init + sh (login has exec'd into it) + 8 jobs fill the 10-slot process table
        pids = []
        for _ in range(8):
            pids.append(self.run_("sleep 9999 &").strip("[]"))
        out = self.v.run("sleep 9999 &", clear=False)
        self.assertIn("too many processes", out)
        self.assertTrue(all(p.isdigit() for p in pids), pids)
        self.v.run("kill " + " ".join(pids[:4]), clear=False)
        self.v.run("kill " + " ".join(pids[4:]), clear=False)
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
        self.assertEqual(self.run_("version"),
                         "breadbox 0.1\nbased on breadbin by kpatronas@gmail.com")
        size = os.path.getsize(os.path.join(ROOT, "rootfs", "etc", "motd"))
        self.assertIn("size: %d" % size, self.run_("stat /etc/motd"))
        self.assertIn("0000: 77 65 6c 63", self.run_("hexdump /etc/motd | head -1"))
        self.assertIn("themes:", self.run_("theme nosuch"))
        out = self.run_("turbo 99")               # no $D031 registers under VICE; a bad index on an Ultimate that has them
        self.assertTrue("no turbo registers" in out or "usage: turbo" in out, out)
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

    def test_28_basic_depth_limit_survives_switches(self):
        # STKSAVE is 128: the deepest legal expression (11 levels, about 106 bytes of saved
        # stack) must survive 600 timer-driven context switches (at 96 it was killed
        # silently, status 139), and no run of minus signs may grow the stack past the cap.
        e = "(" * 10 + "1" + ")" * 10
        self.run_(f"echo '10 for i = 1 to 600 : a = {e} : next i : print a' > /home/d11")
        self.assertEqual(self.run_("basic /home/d11"), "1")
        self.run_("echo '10 for i = 1 to 600 : a = -----5 : next i : print a' > /home/um")
        self.assertEqual(self.run_("basic /home/um"), "-5")
        m = "-" * 40
        self.run_(f"echo '10 for i = 1 to 600 : a = {m}5 : next i : print a' > /home/u40")
        self.assertIn("too complex", self.run_("basic /home/u40"))
        self.assertEqual(self.run_("echo alive"), "alive")
        self.run_("rm /home/d11 /home/um /home/u40")

    def test_26_error_messages_from_the_file(self):
        """perr looks messages up in /etc/errors; three are built in; a missing file gives 'error N'."""
        self.assertIn("file exists", self.run_("mkdir /bin"))                 # from /etc/errors
        self.run_("mv /etc/errors /etc/errors.x")
        try:
            self.assertIn("no such file or directory", self.run_("cat /nope"))   # built in
            self.assertIn("error 17", self.run_("mkdir /bin"))                   # the file is gone
        finally:
            self.run_("mv /etc/errors.x /etc/errors")
        self.assertIn("file exists", self.run_("mkdir /bin"))

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

    def test_27_assembler_trailing_res_is_bss(self):
        """A .res at the end of the source is BSS (S12a): 12,000 bytes of buffer that are not in the
        file, are zero at load, and are writable. The old assembler refused anything over 8 KB."""
        out = self.run_("as /home/bigbuf.s /home/bigbuf")
        self.assertIn("bytes", out)
        self.assertEqual(self.run_("/home/bigbuf"), "bss ok")
        # the first run left 42 in its BSS; the program checks it is zero again at the start
        self.assertEqual(self.run_("/home/bigbuf"), "bss ok")

    def test_29_io_counters(self):
        """IOSTAT (default build): the counters are in the label file and a healthy boot reads blocks
        without a retry or a failure. io_nread, io_nretry and io_nfail count block reads only
        (iec_read); block writes (iec_write) have their own io_nwretry and io_nwfail (one byte).
        io_neoi is printed, not asserted: it says whether the drive sends EOI on the 256th byte of
        a U1 read."""
        lbl, last = {}, {}
        with open(os.path.join(ROOT, "build", "kernel.lbl")) as f:
            for line in f:
                m = re.match(r"al ([0-9A-F]+) \.(io_n\w+)$", line.strip())
                if m:
                    lbl[m.group(2)] = int(m.group(1), 16)
                m = re.match(r"al ([0-9A-F]+) \.(io_l(?:trk|sct|idx|try|st|wn))$", line.strip())
                if m:
                    last[m.group(2)] = int(m.group(1), 16)
        if "io_nread" not in lbl:
            self.skipTest("built with IOSTAT=0")
        self.run_("ls /bin")
        self.run_("cat /etc/passwd")
        self.run_("cp /etc/passwd /home/c29")     # a block write or two
        self.run_("rm /home/c29")
        n = {}
        for k, a in lbl.items():
            b = self.v.mem(a, a + 1)
            n[k] = b[0] if k == "io_nwfail" else b[0] | b[1] << 8
        print("\nIOSTAT", n)
        # the last timeout's record (one byte each; see blk.s): printed, not asserted
        print("IOSTAT last event", {k: self.v.mem(a, a)[0] for k, a in last.items()})
        self.assertGreater(n["io_nread"], 0)
        self.assertEqual(n["io_nretry"], 0)
        self.assertEqual(n["io_nfail"], 0)
        self.assertEqual(n.get("io_nwretry"), 0)
        self.assertEqual(n.get("io_nwfail"), 0)


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
            # an REU is not a Command Interface: $DF1D reads an unused register
            self.assertIn("no such device", v.run("mount uci /mnt"))
            self.assertNotIn("uci", v.run("mount"))


def c1541_dir(img):
    out = subprocess.run(["c1541", img, "-dir"], capture_output=True, text=True).stdout
    return out


class REURoot(unittest.TestCase):
    """The REU as the root device: a disk image preloaded as the REU (block b at offset
    b*256, `mkimage.py reu`), no drive. Boots from the .prg, as a web demo would."""

    PRG = os.path.join(ROOT, "build", "breadbin.prg")
    NODRIVE = ["-drive8type", "0", "-autostartprgmode", "1"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reu = os.path.join(self.tmp.name, "root.reu")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"),
                        "reu", IMAGE, self.reu], check=True, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def boot(self, **kw):
        return Vice(self.PRG, reu=256, reu_image=self.reu, extra=self.NODRIVE, **kw)

    def test_boot_and_write(self):
        with self.boot() as v:
            v.wait_shell()
            self.assertIn("reu: 4 x 64k", v.screen())
            self.assertIn("root on reu", v.screen())
            out = v.run("ls /bin").split()
            for name in ["cat", "ls", "sh", "init", "grep"]:
                self.assertIn(name, out)
            self.assertIn("welcome to breadbin.", v.run("cat /etc/motd"))
            v.run("echo hi there > /home/note")
            self.assertEqual(v.run("cat /home/note"), "hi there")
            v.run("mkdir /home/d")
            self.assertIn("d", v.run("ls /home").split())
            # the REU is the root, not /tmp, and there is no cache: nothing mounted over it
            self.assertNotIn("/tmp", v.run("df"))
            self.assertEqual(v.run("cache").split()[2], "none")

    def test_write_persists_in_the_reu_image(self):
        with self.boot() as v:
            v.wait_shell()
            v.run("echo kept > /home/keep")
        with self.boot() as v:      # the emulator saved the REU on exit
            v.wait_shell()
            self.assertEqual(v.run("cat /home/keep"), "kept")

    def test_no_reu_no_drive_cannot_mount(self):
        with Vice(self.PRG, extra=self.NODRIVE) as v:
            v.wait_for("cannot mount root", timeout=60)

    def test_blank_reu_no_drive_cannot_mount(self):
        with open(self.reu, "wb") as f:
            f.write(bytes(256 * 1024))
        with self.boot() as v:
            v.wait_for("cannot mount root", timeout=60)

    def test_stale_superblock_version_cannot_mount(self):
        with open(self.reu, "r+b") as f:     # a superblock of another version: not ours to adopt
            f.seek(376 * 256 + 5)
            f.write(b"\x02")
        with self.boot() as v:
            v.wait_for("cannot mount root", timeout=60)

    def test_nblocks_beyond_the_reu_refused(self):
        with open(self.reu, "r+b") as f:     # a disk bigger than the REU (4 banks = 1024 blocks)
            f.seek(376 * 256 + 6)
            f.write(b"\x00\x05")
        with self.boot() as v:
            v.wait_for("cannot mount root", timeout=60)
            self.assertIn("too big", v.screen())

    def test_drive_wins_over_reu_image(self):
        """Classic and Expanded unchanged: with a drive the root is the disk, and an REU that
        holds a root image is left alone (no /tmp mkfs over it)."""
        with open(self.reu, "rb") as f:
            before = f.read()
        with Vice(IMAGE, reu=256, reu_image=self.reu) as v:
            v.wait_shell()
            self.assertIn("reu holds a root image: /tmp not on reu", v.screen())
            self.assertNotIn("root on reu", v.screen())
            # /tmp is the root disk's directory, not a mount
            self.assertNotIn("/tmp", v.run("df"))
            v.run("echo hi > /tmp/x")
            self.assertEqual(v.run("cat /tmp/x"), "hi")
            self.assertIn("welcome", v.run("cat /etc/motd"))
        with open(self.reu, "rb") as f:
            after = f.read()
        self.assertEqual(before[:18 * 256], after[:18 * 256])
        self.assertEqual(before[376 * 256:377 * 256], after[376 * 256:377 * 256])



class Eject(unittest.TestCase):
    """The boot disk leaves drive 8 (`eject`): / is served from the REU cache, a writer to / sleeps
    until `reattach`, and drive 8 mounts another disk meanwhile."""

    def test_eject_swap_reattach(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = os.path.join(tmp, "disk.d64")
            other = os.path.join(tmp, "other.d64")
            shutil.copy(IMAGE, img)
            subprocess.run(["c1541", "-format", "cbmdisk,cb", "d64", other,
                            "-write", os.path.join(ROOT, "rootfs", "etc", "motd"), "motd,s"],
                           capture_output=True, check=True)
            with Vice(img, reu=2048, reu_image=os.path.join(tmp, "reu.img")) as v:
                v.wait_shell()
                self.assertEqual(v.run("eject", timeout=900), "")
                self.assertIn("welcome to breadbin.", v.run("cat /etc/motd"))     # from the cache
                self.assertEqual(v.run("echo t > /tmp/t; cat /tmp/t"), "t")       # the REU disk is unaffected
                v.type("touch /late\n")                                          # a writer to / sleeps: no disk under it
                time.sleep(15)
                self.assertNotRegex(v.screen().rstrip().splitlines()[-1], r"\$ $")   # no prompt: it is still waiting
                v.keybuf(b"\x03")                                                 # and it can be killed
                self.assertEqual(v.run("echo up"), "up")
                self.assertNotIn("late", v.run("ls /"))                           # nothing was created
                self.assertNotEqual(v.run("cache flush"), "")                     # the cache is the root now: no flush, no off
                self.assertNotEqual(v.run("cache off"), "")
                self.assertNotEqual(v.run("mount 8 /mnt"), "")                    # the boot disk itself would go stale: refused
                v._cmd("detach 8")
                v._cmd(f'attach "{other}" 8')
                self.assertEqual(v.run("mount 8 /mnt"), "")
                self.assertEqual(v.run("ls /mnt").split(), ["motd"])
                self.assertEqual(v.run("umount /mnt"), "")
                self.assertNotEqual(v.run("reattach"), "")                        # the wrong disk does not get in
                v._cmd("detach 8")
                v._cmd(f'attach "{img}" 8')
                v.run("touch /late | reattach")                                   # the writer sleeps until reattach lets it in
                self.assertIn("late", v.run("ls /"))
                self.assertEqual(v.run("cat /etc/motd")[:7], "welcome")


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

    def boot(self, *cmds, reu=2048):
        """Boot once with the shared REU image (2 MB unless reu says KB); run cmds, then `cache`: its counters."""
        with Vice(self.img, reu=reu, reu_image=self.reu) as v:
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

    def test_smaller_reus_keep_the_cache_above_a_smaller_tmp(self):
        """The cache takes the top 3 banks of an REU of 4 to 10 banks; /tmp gets the rest."""
        for kb, tmp_blocks_max in ((256, 256), (512, 1280)):
            with self.subTest(reu=kb):
                if os.path.exists(self.reu):
                    os.remove(self.reu)
                self.assertEqual(self.boot("echo hi > /tmp/x", "cat /tmp/x", "df", reu=kb)[1][0], "on")   # same programs, so the second boot is all hits
                outs, (state, hits, misses, errs) = self.boot("echo hi > /tmp/x", "cat /tmp/x", "df", reu=kb)
                self.assertEqual(outs[1], "hi")
                self.assertGreater(hits, 20)        # warm: the cache survived the reboot
                self.assertLess(misses, 5)
                self.assertEqual(errs, 0)
                m = re.search(r"(\d+)\s+\d+\s+\d+\s+\d+ /tmp", outs[2])
                self.assertTrue(m, outs[2])
                self.assertLessEqual(int(m.group(1)), tmp_blocks_max)

    def test_tiny_reu_has_no_cache(self):
        with Vice(self.img, reu=128) as v:      # 2 banks: all /tmp, no room for the cache
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


def pool_end():
    """First page the kernel owns (KSTART in src/kernel/k.inc): the user pool is $0800 up to it."""
    with open(os.path.join(ROOT, "src", "kernel", "k.inc")) as f:
        return int(re.search(r"^KSTART\s*=\s*\$([0-9A-Fa-f]+)", f.read(), re.M).group(1), 16) >> 8


class Pool(unittest.TestCase):
    """The user pool is $0800 to KSTART-1: pages above the old $8000 edge are usable."""

    @staticmethod
    def label(name):
        with open(os.path.join(ROOT, "build", "kernel.lbl")) as f:
            for line in f:
                m = re.match(r"al ([0-9A-F]+) \.%s$" % name, line.strip())
                if m:
                    return int(m.group(1), 16)
        raise KeyError(name)

    def test_processes_run_above_the_old_edge(self):
        pg_used = self.label("pg_used")        # index = page - 8
        with Vice(IMAGE) as v:
            v.wait_shell()
            npool = pool_end() - 8
            self.assertIn(str(npool // 4), v.run("free"))      # e.g. 144 pages = 36 K
            # pretend pages $08-$7F are taken: the next process must live at $80 or above
            v._cmd("fill %04x %04x 01" % (pg_used, pg_used + 0x77))
            v._cmd("x")
            self.assertEqual(v.run("echo above the old edge"), "above the old edge")
            v.run("sleep 300 &")
            top = v.mem(pg_used + 0x78, pg_used + npool - 1)   # pages $80 to the top
            self.assertTrue(any(top), "no page at or above $80 was allocated")
            self.assertIn("sleep", v.run("ps"))
            self.assertEqual(v.run("echo still fine | cat"), "still fine")


class Modules(unittest.TestCase):
    """Kernel modules: a CX image loaded at the top of the pool, called through init/fini."""

    def test_hello_module_loads_and_unloads(self):
        with Vice(IMAGE) as v:
            v.wait_shell()
            self.assertEqual(v.run("mod ls"), "")
            out = v.run("mod load /lib/km/hello")
            self.assertIn("hello from module", out)
            ls = v.run("mod ls")
            self.assertRegex(ls, r"slot 0: page \d+, pages 1, class 0")
            page = int(re.search(r"page (\d+)", ls).group(1))
            self.assertGreater(page, 100)                 # top of the pool, not the bottom
            self.assertIn("bye from module", v.run("mod unload 0"))
            self.assertEqual(v.run("mod ls"), "")

    def test_bad_module_is_refused(self):
        with Vice(IMAGE) as v:
            v.wait_shell()
            self.assertIn("exec format", v.run("mod load /etc/passwd"))      # not a CX file
            self.assertIn("no such file", v.run("mod load /lib/km/nothing"))
            self.assertEqual(v.run("mod ls"), "")


class Exec(unittest.TestCase):
    """exec: a process replaces its own image, keeping its pid, descriptors and directory."""

    @staticmethod
    def ps(text):
        rows = {}
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)\s+(\d+)\s+\S\s+(\d+)\s+(\S+)", line)
            if m:
                rows[int(m.group(1))] = (int(m.group(2)), int(m.group(3)), m.group(4))
        return rows

    def test_login_became_the_shell(self):
        with Vice(IMAGE) as v:
            v.wait_shell()
            rows = self.ps(v.run("ps"))
            names = sorted(r[2] for r in rows.values())
            self.assertNotIn("login", names)                # login exec'd into sh
            self.assertEqual(names, ["init", "ps", "sh"])
            sh = [pid for pid, r in rows.items() if r[2] == "sh"][0]
            self.assertEqual(rows[sh][0], 1)                # still init's child

    def test_exec_replaces_the_process(self):
        """`exec` is a program: it replaces itself, not the shell that ran it."""
        with Vice(IMAGE) as v:
            v.wait_shell()
            rows = self.ps(v.run("exec /bin/ps"))
            names = [r[2] for r in rows.values()]
            self.assertNotIn("exec", names)                 # no process left under that name
            outer = [p for p, r in rows.items() if r[2] == "sh" and r[0] == 1][0]
            psrows = [(p, r) for p, r in rows.items() if r[2] == "ps"]
            self.assertEqual(len(psrows), 1)
            self.assertEqual(psrows[0][1][0], outer)        # the shell is its parent

    def test_exec_keeps_descriptors_and_directory(self):
        with Vice(IMAGE) as v:
            v.wait_shell()
            self.assertEqual(v.run("exec /bin/echo piped | cat"), "piped")   # stdout and EOF intact
            v.run("cd /tmp")
            self.assertEqual(v.run("exec /bin/pwd"), "/tmp")                  # cwd carried over

    def test_failures_leave_the_caller_alone(self):
        with Vice(IMAGE) as v:
            v.wait_shell()
            self.assertIn("exec format", v.run("exec /etc/passwd"))
            self.assertIn("no such file", v.run("exec /bin/nothing").replace("\n", ""))
            self.assertEqual(v.run("echo alive"), "alive")


class Drives(unittest.TestCase):
    """mount: normal C64 disks and Breadbin disks on drive 9."""

    def test_cbm_module_is_not_a_program(self):
        """The module file is a CX image like any program. Running it (spawn or exec) must not
        repoint the filesystem vectors at the process's own pages, which are freed on exit."""
        cbm = os.path.join(ROOT, "build", "t_cbm9b.d64")
        if os.path.exists(cbm):
            os.unlink(cbm)
        subprocess.run(["c1541", "-format", "cbmdisk,cb", "d64", cbm,
                        "-write", os.path.join(ROOT, "rootfs", "etc", "motd"), "motd,s",
                        "-write", os.path.join(ROOT, "rootfs", "home", "readme"), "readme,s"],
                       capture_output=True, check=True)
        with Vice(IMAGE, extra=["-drive9type", "1541", "-9", cbm]) as v:
            v.wait_shell()
            self.assertEqual(v.run("mount 9 /mnt"), "")
            v.run("/lib/km/cbm")                              # as a program
            v.run("exec /lib/km/cbm")                         # and through exec
            self.assertEqual(v.run("ls /mnt").split(), ["motd", "readme"])   # vectors still good
            self.assertIn("welcome to breadbin.", v.run("cat /mnt/motd"))
            ls = v.run("mod ls")                              # one copy, loaded by the mount
            self.assertEqual(len(re.findall(r"class 1", ls)), 1, ls)
            self.assertRegex(ls, r"slot 0 \(cbm\): page \d+", ls)   # the module's name
            v.run("mod load /lib/km/cbm")                     # a second copy is refused
            ls = v.run("mod ls")
            self.assertEqual(len(re.findall(r"class 1", ls)), 1, ls)

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
            # a missing mount point says so, not a bare "no such file"
            out = v.run("mount 9 /nowhere")
            self.assertIn("/nowhere: mount point does not", out)   # 40 columns wrap the line
            self.assertNotIn("mount 9", v.run("mount"))
            # UCI v1: VICE has no Command Interface; the probe says so and changes nothing
            self.assertIn("no such device", v.run("mount uci /mnt"))
            self.assertIn("no such device", v.run("mount uci /nowhere"))
            self.assertIn("invalid argument", v.run("mount ufoo /mnt"))       # exactly "uci"
            self.assertNotIn("uci", v.run("mount"))
            self.assertEqual(v.run("ls /mnt"), "")
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


class Pipes(unittest.TestCase):
    """tee, tail and sort (ported from upstream commit 04f3a47): one VICE session."""

    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_pipes.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = make_target(cls.img)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def test_tee_copies_to_stdout_and_a_file(self):
        out = self.v.run("echo teed | tee /home/tee1")
        self.assertIn("teed", out)
        self.assertIn("teed", self.v.run("cat /home/tee1"))

    def test_tee_append(self):
        self.v.run("echo one | tee /home/tee2")
        self.v.run("echo two | tee -a /home/tee2")
        self.assertIn("one", self.v.run("cat /home/tee2"))
        self.assertIn("two", self.v.run("cat /home/tee2"))

    def test_tail_last_lines(self):
        self.v.run("echo a > /home/tl")
        self.v.run("echo b >> /home/tl")
        self.v.run("echo c >> /home/tl")
        self.assertEqual(self.v.run("tail -1 /home/tl").strip(), "c")

    def test_long_line_wraps_at_forty(self):
        # a 60-column command wraps at 40 columns; the harness must still find its end and output
        line = "echo " + "0123456789" * 5 + "0123456789ab"[:5]     # 60 columns, the echo wraps at 40
        self.assertEqual(len(line), 60)
        out = self.v.run(line).replace("\n", "")      # the output wraps at 40 columns too
        self.assertEqual(out.strip(), line[5:])

    def test_tee_five_files_leaves_an_existing_one_alone(self):
        # the count check runs before anything is opened: the existing file keeps its text
        self.v.run("echo keep > /k1")
        out = self.v.run("echo x | tee /k1 /k2 /k3 /k4 /k5")
        self.assertIn("too many files", out)
        self.assertIn("keep", self.v.run("cat /k1"))

    def test_tail_count_256_is_an_error(self):
        self.assertIn("too large", self.v.run("tail -256 /etc/help"))

    def test_tail_count_1000_is_an_error(self):
        # four digits: parse_dec keeps 16 bits, so the value check alone would not be the whole guard
        self.assertIn("too large", self.v.run("tail -1000 /etc/help"))

    def test_sort_empty_file(self):
        self.v.run("cat /dev/null > /home/se")
        self.assertEqual(self.v.run("sort /home/se").strip(), "")

    def test_tee_four_files_all_get_the_text(self):
        # short names: a command line longer than 40 columns wraps and the harness misses the prompt
        self.v.run("echo four | tee /a1 /a2 /a3 /a4")
        self.assertIn("four", self.v.run("cat /a4"))

    def test_tee_more_than_four_files_is_an_error(self):
        out = self.v.run("echo x | tee /b1 /b2 /b3 /b4 /b5")
        self.assertIn("too many files", out)

    def test_tail_more_than_the_ring(self):
        # six copies of /etc/help: 2448 bytes, over the 2 KB ring, so the wrap is exercised
        self.v.run("cat /etc/help > /home/big")
        for _ in range(5):
            self.v.run("cat /etc/help >> /home/big")
        self.assertEqual(self.v.run("tail -1 /home/big").strip(), "run/stop interrupts a command")

    def test_sort_lines(self):
        self.v.run("echo pear > /home/so")
        self.v.run("echo apple >> /home/so")
        self.v.run("echo fig >> /home/so")
        lines = [l.strip() for l in self.v.run("sort /home/so").splitlines() if l.strip()]
        self.assertEqual(lines[:3], ["apple", "fig", "pear"])


class Touch(unittest.TestCase):
    """touch (ported from upstream commit 4cc3c7e): creates a missing file, leaves an existing one alone."""

    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_touch.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = make_target(cls.img)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def test_creates_a_missing_file(self):
        self.v.run("touch /home/tch1")
        self.assertIn("tch1", self.v.run("ls /home").split())

    def test_existing_file_is_left_as_it_is(self):
        self.v.run("echo keep > /home/tch2")
        # a path that cannot be made: touch must report it, which proves touch ran at all
        self.assertIn("touch:", self.v.run("touch /home/tch2 /nodir/zz"))
        self.assertIn("keep", self.v.run("cat /home/tch2"))


class Readline(unittest.TestCase):
    """The shell's raw readline: TAB completion of command and file names
    (upstream 4abb291), DEL, and CTRL-D on an empty line. One VICE session."""

    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_readline.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = make_target(cls.img)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def clear(self):
        self.v.type("clear\n")
        self.v.wait_for("$")

    def tab(self):
        self.v._cmd("keybuf \\x09")
        self.v._cmd("x", wait=0.5)

    def test_tab_completes_a_command(self):
        self.clear()
        self.v.type("whoa")
        self.tab()
        self.v.type("\n")
        self.v.wait_for("root", after="$ whoami")

    def test_tab_completes_after_a_pipe(self):
        self.clear()
        self.v.type("echo hi | hexd")
        self.tab()
        self.v.type("\n")
        self.v.wait_for("68 69", after="$ echo hi | hexdump")

    def test_tab_adds_slash_after_a_directory(self):
        self.clear()
        self.v.type("echo /ho")
        self.tab()
        self.v.type("\n")
        self.v.wait_for("/home/", after="$ echo /home/\n")

    def test_tab_lists_ambiguous_matches(self):
        self.clear()
        self.v.type("echo /home/h")
        self.tab()                              # hello.bas, hello.s: "hello."
        self.tab()                              # lists them
        s = self.v.wait_for("$ echo /home/hello.", after="hello.bas")
        listing = [l for l in s.splitlines() if "hello.bas" in l][-1]
        self.assertEqual(sorted(listing.split()), ["hello.bas", "hello.s"])
        self.v.type("s")
        self.tab()
        self.v.type("\n")
        self.v.wait_for("$ echo /home/hello.s\n/home/hello.s")

    def test_tab_with_no_match_changes_nothing(self):
        self.clear()
        self.v.type("echo zzq")
        self.tab()
        self.v.type("\n")
        self.v.wait_for("zzq", after="$ echo zzq\n")

    def test_tab_on_an_empty_line_is_harmless(self):
        self.clear()
        self.tab()
        self.v.type("echo ok\n")
        self.v.wait_for("ok", after="$ echo ok\n")

    def test_del_erases_the_last_character(self):
        self.clear()
        self.v.type("echo abx")
        self.v.keybuf(b"\x14")                  # DEL
        self.v.type("c\n")
        self.v.wait_for("abc", after="$ echo abc\n")

    def test_ctrl_d_on_an_empty_line_ends_a_shell(self):
        self.clear()
        self.v.type("sh\n")
        self.v.wait_for("$", after="$ sh\n")
        self.v.type("echo inner\n")
        self.v.wait_for("inner", after="$ echo inner\n")
        self.v.keybuf(b"\x04")
        self.v.type("echo outer\n")
        self.v.wait_for("outer", after="$ echo outer\n")

    def test_tab_leaves_a_pattern_alone(self):
        self.clear()
        self.v.type("echo /home/h*.s")
        self.tab()                              # a pattern: nothing is added
        self.v.type("\n")
        self.v.wait_for("/home/hello.s", after="$ echo /home/h*.s\n")


class ShellOperators(unittest.TestCase):
    """Shell &&, || and $? expansion: one VICE session."""

    @classmethod
    def setUpClass(cls):
        cls.img = os.path.join(ROOT, "build", "test_shops.d64")
        with open(IMAGE, "rb") as f, open(cls.img, "wb") as g:
            g.write(f.read())
        cls.v = make_target(cls.img)
        cls.v.wait_shell()

    @classmethod
    def tearDownClass(cls):
        cls.v.close()

    def test_and_success(self):
        """echo ok && echo yes: second command runs."""
        out = self.v.run("echo ok && echo yes")
        self.assertIn("yes", out)

    def test_and_fail(self):
        """cat /nope && echo no: second command skipped."""
        out = self.v.run("cat /nope && echo no")
        self.assertNotIn("no", out)

    def test_or_success(self):
        """echo ok || echo no: second command skipped."""
        out = self.v.run("echo ok || echo no")
        self.assertNotIn("no", out)

    def test_or_fail(self):
        """cat /nope || echo yes: second command runs."""
        out = self.v.run("cat /nope || echo yes")
        self.assertIn("yes", out)

    def test_dollar_question_after_success(self):
        """$? after echo ok is 0."""
        self.v.run("echo ok")
        out = self.v.run("echo $?")
        self.assertEqual(out.strip(), "0")

    def test_dollar_question_after_fail(self):
        """$? after cat /nope is 1."""
        self.v.run("cat /nope")
        out = self.v.run("echo $?")
        self.assertEqual(out.strip(), "1")

    def test_chained_and_or(self):
        """echo ok && cat /nope || echo recovered: the || fires because last_status != 0."""
        out = self.v.run("echo ok && cat /nope || echo recovered")
        self.assertIn("recovered", out)

    def test_chained_or_and(self):
        """cat /nope || echo ok && echo yes: && fires because echo ok succeeded."""
        out = self.v.run("cat /nope || echo ok && echo yes")
        self.assertIn("yes", out)
