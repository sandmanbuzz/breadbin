"""VICE run of the 80-column console module (src/mod/con80.s).

    tools/ci/run.sh test-only T="tests.test_con80"

The screen is read back from the hires bitmap ($2000-$3F3F): every half cell is matched against the
module's font file, so what is checked is what the VIC would show, not what the driver believes.
The image is built with /etc/con80, so init loads the module before any shell (the fixed pages
$20-$3F must be free: a running shell usually sits across them, so loading from a shell can fail).
Boot to a login on 80 columns, shell output, unload back to the 40-column text screen, load again
(the claimed pages must have been released), unload.
"""
import shutil
import subprocess
import tempfile
import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import soft80_render as m  # noqa: E402
from vicetest import Vice  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")
with open(os.path.join(ROOT, "src", "mod", "con80.font"), "rb") as f:
    FONT = f.read()
BY_GLYPH = {}
for _a in range(0x20, 0x7f):
    _c = m.screen_code(chr(_a))
    if _c is not None and _c < m.NGLYPH:
        BY_GLYPH.setdefault(bytes(b >> 4 for b in FONT[_c * 8:_c * 8 + 8]), chr(_a))


def text80(v):
    """The 80 x 25 screen as text lines ('?' where a half cell is no glyph, e.g. the cursor)."""
    bmp = v.mem(0x2000, 0x3F3F)
    lines = []
    for r in range(25):
        row = ""
        for c in range(80):
            cell = bmp[(r * 40 + c // 2) * 8:(r * 40 + c // 2) * 8 + 8]
            g = bytes((b >> 4) if c % 2 == 0 else (b & 15) for b in cell)
            row += BY_GLYPH.get(g, " " if not any(g) else "?")
        lines.append(row.rstrip())
    return lines


def wait80(v, pred, what, timeout=60):
    deadline = v._time() + timeout
    while v._time() < deadline:
        ls = text80(v)
        if pred(ls):
            return ls
        v._pause(0.5)
    raise TimeoutError(what + ":\n" + "\n".join(ls))


def image_with_marker(tmp):
    root = os.path.join(tmp, "root")
    shutil.copytree(os.path.join(ROOT, "build", "root"), root)
    with open(os.path.join(root, "etc", "con80"), "w") as f:
        f.write("1\n")
    img = os.path.join(tmp, "c80.d64")
    with open(os.path.join(ROOT, "build", "rev.txt")) as f:
        rev = f.read().strip()
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "build", img,
                    "--boot", os.path.join(ROOT, "build", "breadbin.prg"), "--root", root,
                    "--dev", "console:1", "--dev", "null:0", "--rev", rev], check=True, capture_output=True)
    return img


class Con80(unittest.TestCase):
    def test_load_80_columns_unload_reload(self):
        long_line = "80 columns: " + "0123456789 " * 6          # 78 characters
        with tempfile.TemporaryDirectory() as tmp, Vice(image_with_marker(tmp)) as v:
            wait80(v, lambda ls: any(l.endswith("login:") for l in ls), "no login on the 80-column screen", 90)
            v.type("root\n")
            wait80(v, lambda ls: any(l.endswith("/ $") for l in ls), "no shell prompt")
            v.type("echo " + long_line.rstrip() + "\n")
            ls = wait80(v, lambda ls: long_line.rstrip() in ls, "no echo output")
            self.assertIn("/ $ echo " + long_line.rstrip()[:71], ls)        # the typed line wraps at 80
            v.type("mod ls\n")
            ls = wait80(v, lambda ls: any("(con80)" in l for l in ls), "mod ls does not list con80")
            slot = re.search(r"slot (\d+) \(con80\)", "\n".join(ls)).group(1)
            v.type("mod unload %s\n" % slot)
            v.wait_for(" $", timeout=30)
            self.assertEqual(v.run("echo 40 columns again"), "40 columns again")
            self.assertNotIn("con80", v.run("mod ls"))
            v.type("mod load /lib/km/con80\n")        # the pages $20-$3F must be free again
            wait80(v, lambda ls: ls[0].endswith("$"), "second load failed")
            v.type("mod ls\n")
            ls = wait80(v, lambda ls: any("(con80)" in l for l in ls), "mod ls does not list con80")
            slot = re.search(r"slot (\d+) \(con80\)", "\n".join(ls)).group(1)
            v.type("mod unload %s\n" % slot)
            v.wait_for(" $", timeout=30)
            self.assertEqual(v.run("echo done"), "done")


if __name__ == "__main__":
    unittest.main()
