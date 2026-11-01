import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import kexports as k

LBL = """al 000058 .tmp0
al 009F88 .con_puts_ax
al 00B10E .iget
al 00404E .init_only
al 00404D .__INIT_RUN__
al 000475 .__INIT_SIZE__
"""
TOOL = os.path.join(os.path.dirname(__file__), "kexports.py")


class TestKexports(unittest.TestCase):
    def pairs(self, names, lbl=LBL):
        return k.resolve(k.parse_labels(lbl), names)

    def test_resolve_in_whitelist_order(self):
        self.assertEqual(self.pairs(["iget", "tmp0"]), [("iget", 0xB10E), ("tmp0", 0x58)])

    def test_missing_init_duplicate_and_linker_symbols_are_errors(self):
        for names, msg in ((["nope"], "not in the kernel"), (["init_only"], "INIT"),
                           (["iget", "iget"], "duplicate"), (["__INIT_RUN__"], "plain label")):
            with self.assertRaisesRegex(k.KapiError, msg):
                self.pairs(names)

    def test_zero_page_uses_exportzp_and_absolute_uses_export(self):
        s, inc, _, _ = k.render(self.pairs(["tmp0", "iget"]))
        self.assertIn(".exportzp tmp0 := $58", s)
        self.assertIn(".export iget := $B10E", s)
        self.assertIn(".importzp tmp0", inc)
        self.assertIn(".import iget", inc)
        self.assertIn(".export KAPI_HASH", s)

    def test_hash_is_stable_and_tracks_every_address_and_the_order(self):
        h = k.api_hash(self.pairs(["tmp0", "iget"]))
        self.assertEqual(h, k.api_hash(self.pairs(["tmp0", "iget"])))
        self.assertNotEqual(h, k.api_hash(self.pairs(["iget", "tmp0"])))
        self.assertNotEqual(h, k.api_hash(self.pairs(["tmp0", "iget"], LBL.replace("B10E", "B10F"))))
        self.assertEqual(k.crc16(b"123456789"), 0x29B1)      # CRC-16/CCITT-FALSE check value

    def test_gen_check_roundtrip_and_a_moved_address_fails_check(self):
        with tempfile.TemporaryDirectory() as d:
            lbl, kapi, out = (os.path.join(d, n) for n in ("k.lbl", "kapi.txt", "out"))
            open(lbl, "w").write(LBL)
            open(kapi, "w").write("# c\ncon_puts_ax\ntmp0  # zp\n")
            run = lambda *a: subprocess.run([sys.executable, TOOL, *a], capture_output=True, text=True)
            self.assertEqual(run("gen", lbl, kapi, out).returncode, 0)
            hinc = os.path.join(out, "khash.inc")
            self.assertEqual(run("check", lbl, kapi, hinc).returncode, 0)
            open(lbl, "w").write(LBL.replace("009F88", "009F89"))
            self.assertEqual(run("check", lbl, kapi, hinc).returncode, 1)
            open(kapi, "w").write("init_only\n")
            self.assertEqual(run("gen", lbl, kapi, out).returncode, 1)


if __name__ == "__main__":
    unittest.main()
