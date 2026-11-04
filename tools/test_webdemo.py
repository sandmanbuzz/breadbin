import os
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import webdemo as W  # noqa: E402


def fake_tool(root):
    """A stand-in for the external webdemo tool: no emulator, no ROMs."""
    t = Path(root) / "tool"
    (t / "kit" / "data" / "cores").mkdir(parents=True)
    (t / "kit" / "data" / "cores" / "vice_x64sc-wasm.data").write_bytes(b"core")
    (t / "kit" / "data" / "loader.js").write_text("//")
    (t / "kit" / "SOURCES.txt").write_text("sources")
    (t / "lic-a.txt").write_text("licence a")
    (t / "make_webdemo.py").write_text(f"LICENCES = {{'A.txt': {str(t / 'lic-a.txt')!r}}}\n")
    for f in ("build_core.sh", "strip_roms.py", "romscan.py"):
        (t / f).write_text("x")
    return t


class TestWebdemo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.tool = fake_tool(self.d)
        self.prg = self.d / "b.prg"
        self.prg.write_bytes(b"\x01\x08kernel")
        self.reu = self.d / "b.reu"
        self.reu.write_bytes(bytes(W.REU_SIZE))

    def tearDown(self):
        self.tmp.cleanup()

    def bundle(self, prg=None, reu=None):
        return W.bundle(self.tool, prg or self.prg, reu or self.reu, self.d / "out")

    def test_bundle_layout(self):
        game = self.bundle()
        out = self.d / "out"
        self.assertTrue((out / "data" / "loader.js").exists())
        self.assertTrue((out / "LICENSES" / "A.txt").exists())
        self.assertTrue((out / "LICENSES" / "build" / "webdemo.py").exists())
        self.assertIn(game, (out / "index.html").read_text())
        with zipfile.ZipFile(out / game) as z:
            self.assertEqual(sorted(z.namelist()), ["breadbin.prg", "breadbin.reu"])
            self.assertEqual(z.read("breadbin.prg"), self.prg.read_bytes())
            self.assertEqual(len(z.read("breadbin.reu")), W.REU_SIZE)
        self.assertTrue((self.d / "out.zip").exists())

    def test_game_name_follows_contents(self):
        a = self.bundle()
        self.assertRegex(a, r"^breadbin-web-[0-9a-f]{8}\.zip$")
        self.assertEqual(a, self.bundle())
        self.prg.write_bytes(b"\x01\x08other")
        self.assertNotEqual(a, self.bundle())
        # the stale game file does not survive into the new bundle
        self.assertEqual(len(list((self.d / "out").glob("breadbin-web-*.zip"))), 1)

    def test_no_kit_refuses(self):
        (self.tool / "kit" / "data" / "cores" / "vice_x64sc-wasm.data").unlink()
        with self.assertRaisesRegex(SystemExit, "build_core.sh"):
            self.bundle()

    def test_reu_must_be_the_right_size(self):
        self.reu.write_bytes(b"short")
        with self.assertRaisesRegex(SystemExit, "256 KB"):
            self.bundle()

    def test_page_has_no_private_paths(self):
        self.bundle()
        html = (self.d / "out" / "index.html").read_text()
        self.assertNotIn(str(self.d), html)
        self.assertNotIn("/home/", html)
        self.assertEqual(len(re.findall(r'EJS_gameUrl = "[^"]+"', html)), 1)


if __name__ == "__main__":
    unittest.main()
