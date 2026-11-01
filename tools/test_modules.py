"""Build the hello module and check the module contract (docs/design/next/modules-v1.md)."""
import os
import re
import shutil
import struct
import subprocess
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
BUILD = os.path.join(ROOT, "build")


def label(name):
    for line in open(os.path.join(BUILD, "kernel.lbl")):
        m = re.match(r"al ([0-9A-Fa-f]+) \.%s$" % re.escape(name), line.strip())
        if m:
            return int(m.group(1), 16)
    raise KeyError(name)


@unittest.skipUnless(shutil.which("ca65") and shutil.which("ld65"), "cc65 not installed")
class TestHelloModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["make", "-s", "build/root/lib/km/hello"], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cls.cx = open(os.path.join(BUILD, "root/lib/km/hello"), "rb").read()
        cls.hash = int(re.search(r"\$([0-9A-F]{4})", open(os.path.join(BUILD, "khash.inc")).read().split("\n")[1]).group(1), 16)

    def image(self):
        img, bss, nrel = struct.unpack("<HHH", self.cx[3:9])
        return self.cx[9:9 + img], bss, nrel

    def test_cx_container_and_header_layout(self):
        self.assertEqual(self.cx[:3], b"CX\x01")
        img, bss, nrel = self.image()
        self.assertEqual((img[0], img[3]), (0x4C, 0x4C))          # jmp init, jmp fini
        self.assertEqual(struct.unpack("<H", img[6:8])[0], self.hash)
        self.assertEqual(img[8], 0)                               # class
        self.assertGreater(nrel, 0)                               # init/fini jumps are relocated
        self.assertEqual(len(self.cx), 9 + len(img) + 2 * nrel)

    def test_header_hash_is_not_relocated_and_equals_the_kernels_word(self):
        # the kernel's word, found through the image layout (prg = load addr, then the LOAD area)
        prg = open(os.path.join(BUILD, "breadbin.prg"), "rb").read()
        addr = label("kapi_hash")
        off = 2 + (label("__RODATA_LOAD__") - 0x0801) + (addr - label("__RODATA_RUN__"))
        self.assertEqual(struct.unpack("<H", prg[off:off + 2])[0], self.hash)
        img, _, nrel = self.image()
        rel = struct.unpack("<%dH" % nrel, self.cx[9 + len(img):])
        self.assertNotIn(6, rel)
        self.assertNotIn(7, rel)

    def test_second_make_changes_nothing(self):
        # (make -n cannot tell: the FORCE cache.stamp rule makes a dry run assume a rebuild)
        files = [os.path.join(BUILD, f) for f in ("breadbin.prg", "kexp.s", "khash.inc", "root/lib/km/hello")]
        before = [os.stat(f).st_mtime_ns for f in files]
        r = subprocess.run(["make", "-s", "build/root/lib/km/hello", "build/breadbin.prg"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(before, [os.stat(f).st_mtime_ns for f in files])


if __name__ == "__main__":
    unittest.main()
