"""Open-file table full on a create: no file, no inode, EMFILE (py65 sim, tools/uci_sim.py).

sys_open on a new name takes the inode and the directory entry before the open-file entry
(file.s create path). With the table full, the call fails with EMFILE, but the file used to
stay behind as a zero-length entry with its inode allocated. These tests check that a failed
create leaves the volume exactly as it was. Skips when py65 is missing or the kernel is not built.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from uci_sim import Sim
except ImportError:
    Sim = None

O_WRONLY, O_CREAT = 0x01, 0x10      # include/breadbin.inc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
BUILT = all(os.path.exists(os.path.join(BUILD, f)) for f in ("breadbin.prg", "kernel.lbl", "breadbin.d64"))
SKIP = "py65 not installed" if Sim is None else ("kernel not built (make)" if not BUILT else None)


def kconst(name):
    """A constant from src/kernel/k.inc (decimal, or $hex)."""
    with open(os.path.join(ROOT, "src", "kernel", "k.inc")) as f:
        v = re.search(r"^%s\s*=\s*(\S+)" % name, f.read(), re.M).group(1)
    return int(v[1:], 16) if v.startswith("$") else int(v)


@unittest.skipIf(SKIP, SKIP)
class NfileCreate(unittest.TestCase):
    def setUp(self):
        self.s = Sim(None)
        self.s.errno(self.s.path_call("MKDIR", "/u"))
        self.nfile = kconst("NFILE")
        self.ft_null = kconst("FT_NULL")

    def used(self):
        """(used inodes, free blocks) of the root volume, from SYS_FSINFO on /."""
        s = self.s
        buf = 0x8100
        res = s.sys("FSINFO", r0=s.cstr("/"), r1=buf)
        self.assertFalse(res[0], "fsinfo failed")
        b = bytes(s.mem.b[buf:buf + 8])
        return b[4], b[0] | b[1] << 8

    def fill_open_table(self):
        m, L = self.s.mem.b, self.s.lbl
        for i in range(self.nfile):
            m[L["f_type"] + i] = self.ft_null

    def test_full_table_create_is_emfile_and_leaves_nothing(self):
        s = self.s
        before = self.used()
        self.fill_open_table()
        self.assertEqual(s.errno(s.open("/u/new", O_WRONLY | O_CREAT)), "EMFILE")
        self.assertEqual(self.used(), before, "inode or block left behind by the failed create")
        self.assertEqual(s.errno(s.open("/u/new")), "ENOENT", "a name was left behind")


if __name__ == "__main__":
    unittest.main()
