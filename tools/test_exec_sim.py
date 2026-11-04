"""exec (SP_EXEC) in the real kernel under py65 (tools/uci_sim.py): docs/design/next/exec.md section 6.

The simulator has one fake process (slot 0, pid 200) and no scheduler, so these tests drive
`SPAWN` with Y = SP_EXEC and look at the kernel's tables: the error paths must leave the caller
exactly as it was; the success path must stop on `jmp (k_entry)` of the new image with the frame
`proc_entry` builds; a signal pending when the load ends must kill the new image without a leak.
Skips when py65 is missing or the kernel is not built (`make`).
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import uci_sim
    from uci_sim import Sim, cx_image
except ImportError:
    uci_sim = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
BUILT = all(os.path.exists(os.path.join(BUILD, f)) for f in ("breadbin.prg", "kernel.lbl", "breadbin.d64"))
SKIP = "py65 not installed" if uci_sim is None else ("kernel not built (make)" if not BUILT else None)

SP_EXEC = 0x80
OLD_PAGE, OLD_LEN = 0x20, 2        # the fake caller's image: two pool pages


def kstart():
    with open(os.path.join(ROOT, "src", "kernel", "k.inc")) as f:
        return int(re.search(r"^KSTART\s*=\s*\$([0-9A-Fa-f]+)", f.read(), re.M).group(1), 16) >> 8


@unittest.skipIf(SKIP, SKIP)
class ExecSim(unittest.TestCase):
    IMAGE = None                                     # a subclass can boot a different disk image

    def setUp(self):
        self.s = Sim(None, image=self.IMAGE)
        s, m, L = self.s, self.s.mem.b, self.s.lbl
        self.m, self.L = m, L
        for i in range(OLD_LEN):                     # the caller's own image
            m[L["pg_used"] + OLD_PAGE - 8 + i] = 1
        m[L["free_pages"]] -= OLD_LEN
        m[L["p_mpage"]], m[L["p_mlen"]] = OLD_PAGE, OLD_LEN
        m[L["p_name"]:L["p_name"] + 4] = b"old\0"
        m[0x20:0x40] = bytes(range(0xA0, 0xC0))      # user zero page the kernel must not touch

    def state(self):
        m, L = self.m, self.L
        npool = kstart() - 8
        return {
            "pg_used": bytes(m[L["pg_used"]:L["pg_used"] + npool]),
            "free_pages": m[L["free_pages"]],
            "p_mpage": m[L["p_mpage"]], "p_mlen": m[L["p_mlen"]],
            "p_name": bytes(m[L["p_name"]:L["p_name"] + 11]),
            "p_fd": bytes(m[L["p_fd"]:L["p_fd"] + 8]),
            "p_pid": m[L["p_pid"]], "p_state": m[L["p_state"]], "p_uid": m[L["p_uid"]],
            "user_zp": bytes(m[0x20:0x40]),
        }

    def exec(self, path, until=None, argv=0):
        """SPAWN with SP_EXEC. Without `until` it must return (carry, A); with it, run to that pc."""
        s, m = self.s, self.m
        r0 = s.cstr(path)
        if until is None:
            return s.sys("SPAWN", y=SP_EXEC, r0=r0, r1=argv)
        m[2], m[3], m[4], m[5] = r0 & 0xFF, r0 >> 8, argv & 0xFF, argv >> 8
        addr = s.sysno["SPAWN"]
        m[s.TRAMP:s.TRAMP + 3] = bytes([0x20, addr & 0xFF, addr >> 8])
        s.mpu.pc, s.mpu.sp, s.mpu.a, s.mpu.x, s.mpu.y = s.TRAMP, 0xFF, 0, 1, SP_EXEC
        s.run(until, 4_000_000)

    def errno_of(self, res):
        carry, a, _ = res
        self.assertTrue(carry, "exec should have failed")
        return self.s.errno(res)

    # (a) a missing file
    def test_missing_file_is_enoent_and_changes_nothing(self):
        before = self.state()
        self.assertEqual(self.errno_of(self.exec("/bin/nothing-here")), "ENOENT")
        self.assertEqual(self.state(), before)

    # (b) not a CX file
    def test_text_file_is_enoexec_and_changes_nothing(self):
        before = self.state()
        self.assertEqual(self.errno_of(self.exec("/etc/passwd")), "ENOEXEC")
        self.assertEqual(self.state(), before)

    # (c) no pages for the new image
    def test_no_free_pages_is_enomem_and_changes_nothing(self):
        m, L = self.m, self.L
        for i in range(kstart() - 8):                # every page owned
            m[L["pg_used"] + i] = 1
        m[L["free_pages"]] = 0
        before = self.state()
        self.assertEqual(self.errno_of(self.exec("/bin/echo")), "ENOMEM")
        self.assertEqual(self.state(), before)

    # (d) success: the new image, the frame, the tables
    def test_success_lands_on_the_new_image(self):
        m, L, s = self.m, self.L, self.s
        before = self.state()
        free_before = before["free_pages"]
        self.exec("/bin/echo", until=0x0800)         # first fit: the new image starts at page $08
        with open(os.path.join(BUILD, "root", "bin", "echo"), "rb") as f:
            data = f.read()
        img, _bss = cx_image(data, 0x08)
        self.assertEqual(bytes(m[0x0800:0x0800 + len(img)]), bytes(img))   # relocated image in place
        self.assertEqual(s.mpu.sp, 0xFD)                                  # proc_entry's frame
        self.assertEqual(m[L["in_kernel"]], 0)
        st = self.state()
        self.assertEqual(st["p_pid"], before["p_pid"])
        self.assertEqual(st["p_fd"], before["p_fd"])
        self.assertEqual(st["p_uid"], before["p_uid"])
        self.assertEqual(st["p_state"], before["p_state"])
        self.assertEqual(st["p_name"].split(b"\0")[0], b"echo")
        self.assertEqual(st["p_mpage"], 0x08)
        new_len = st["p_mlen"]
        for i in range(OLD_LEN):                                           # the old image is back in the pool
            self.assertEqual(m[L["pg_used"] + OLD_PAGE - 8 + i], 0)
        self.assertEqual(st["free_pages"], free_before + OLD_LEN - new_len)
        self.assertEqual(m[0x22], 1)                                       # argc
        argv = m[0x20] | m[0x21] << 8
        self.assertEqual(argv >> 8 >= 0x08 and argv >> 8 < 0x08 + new_len, True)   # argv in the new run
        p0 = m[argv] | m[argv + 1] << 8
        self.assertEqual(bytes(m[p0:p0 + 10]).split(b"\0")[0], b"/bin/echo")
        self.assertEqual(m[argv + 2] | m[argv + 3], 0)                      # NULL-terminated
        self.assertEqual(bytes(m[0x02:0x1E]), bytes(0x1C))                  # the scratch zero page is clean

    # (e) a signal that is pending when the load ends kills the new image; nothing leaks
    def test_pending_signal_kills_the_new_image_without_a_leak(self):
        m, L = self.m, self.L
        base_free = m[L["free_pages"]] + OLD_LEN            # what the pool had before the caller's image
        m[L["p_sig"]] = 15
        self.exec("/bin/echo", until=L["sched"])
        self.assertEqual(m[L["p_state"]], 3)                # PS_ZOMBIE
        self.assertEqual(m[L["free_pages"]], base_free)     # old and new image both returned
        for i in range(OLD_LEN):
            self.assertEqual(m[L["pg_used"] + OLD_PAGE - 8 + i], 0)


def cx_file(img_size, bss_size):
    """A CX v1 file whose header declares `img_size` bytes of image (all `rts`) and `bss_size` of BSS."""
    assert img_size >= 1
    return b"CX\x01" + img_size.to_bytes(2, "little") + bss_size.to_bytes(2, "little") + \
        (0).to_bytes(2, "little") + b"\x60" * img_size


class _OversizeImage:
    """A disk image with programs whose headers declare a BSS the pool cannot hold, built once."""
    PROGRAMS = {}
    path = None

    @classmethod
    def build(cls):
        if cls.path:
            return cls.path
        import shutil
        import subprocess
        import tempfile
        tmp = tempfile.mkdtemp(prefix="bigbss-")
        root = os.path.join(tmp, "root")
        shutil.copytree(os.path.join(BUILD, "root"), root)
        for name, (img, bss) in cls.PROGRAMS.items():
            with open(os.path.join(root, "bin", name), "wb") as f:
                f.write(cx_file(img, bss))
        out = os.path.join(tmp, "bigbss.d64")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "build", out,
                        "--boot", os.path.join(BUILD, "breadbin.prg"), "--root", root,
                        "--dev", "console:1", "--dev", "null:0"], check=True, capture_output=True)
        cls.path = out
        return out


class Oversize(_OversizeImage):
    PROGRAMS = {
        "bss40000": (1, 40000),        # more than the whole pool (39,424 bytes)
        "bssffff": (1, 0xFFFF),        # img + bss = 65,536: the 16-bit sum carries
        "carry": (600, 65000),         # img + bss carries too
        "frag": (1, 95 * 256),         # 96 pages: free pages in total (144), but no contiguous run that long
        "fit": (1, 94 * 256 - 64),     # 94 pages with the arguments: exactly the longest free run in the simulator
    }


@unittest.skipIf(SKIP, SKIP)
class ExecOversizeBss(ExecSim):
    """exec of a program whose header declares more BSS than there is memory: a clean ENOMEM, nothing
    loaded, nothing zero-filled, the caller untouched (the unverified 'oversize BSS' nit from the S12a
    review; as can now write a big BSS into the header, so exec is the one that must refuse it)."""
    @classmethod
    def setUpClass(cls):
        cls.IMAGE = Oversize.build()

    def user_memory(self):
        # the pool, without the simulator's own scratch pages ($80-$87: the path string lives there)
        return bytes(self.m[0x0800:0x8000]) + bytes(self.m[0x8800:kstart() << 8])

    def test_a_bss_larger_than_the_pool_is_enomem_and_changes_nothing(self):
        for name in ("bss40000", "bssffff", "carry", "frag"):
            with self.subTest(name):
                self.setUp()
                for i in range(0x0800, kstart() << 8, 256):         # dirty memory: a zero-fill would show
                    self.m[i:i + 256] = bytes([0xFF]) * 256
                self.m[0x20:0x40] = bytes(range(0xA0, 0xC0))
                before, mem = self.state(), self.user_memory()
                self.assertEqual(self.errno_of(self.exec("/bin/" + name)), "ENOMEM")
                self.assertEqual(self.state(), before)
                self.assertEqual(self.user_memory(), mem)

    def test_the_longest_free_run_fits_and_its_bss_is_zeroed(self):
        for i in range(0x0800, kstart() << 8, 256):
            self.m[i:i + 256] = bytes([0xFF]) * 256
        # the simulator's free runs: $08-$1F (24), $22-$7F (94: the caller holds $20-$21, the test's
        # scratch pages are $80-$87), $88 to the pool's end (26). The longest is 94 pages from $22.
        used = self.m[self.L["pg_used"]:self.L["pg_used"] + kstart() - 8]
        runs, start = [], None
        for i, u in enumerate(list(used) + [1]):
            if not u and start is None:
                start = i
            elif u and start is not None:
                runs.append((i - start, start + 8))
                start = None
        self.assertEqual(max(runs), (94, 0x22), runs)
        self.exec("/bin/fit", until=0x2200)
        st = self.state()
        self.assertEqual(st["p_mpage"], 0x22)
        self.assertEqual(st["p_mlen"], 94)
        bss = bytes(self.m[0x2200 + 1:0x2200 + 1 + 94 * 256 - 64])
        self.assertEqual(bss, bytes(len(bss)), "the BSS must be zero at load, not whatever the pages held")


if __name__ == "__main__":
    unittest.main()
