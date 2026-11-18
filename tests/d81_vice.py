"""VICE run of a c64fs volume on a 1581 (drive 9) through /lib/km/d81 (no test_ prefix: not in the shards).

    tools/ci/run.sh test-only T="tests.d81_vice"

Needs a 1581 drive ROM (tools/setup-vice-roms.sh fetches dos1581-318045-02.bin; run.sh copies the ROM dir into
the container's VICE DRIVES directory): the D81 class skips, saying so, unless a dos1581* image is in VICE's
DRIVES directory or BREADBIN_VICE_ARGS names one (-dos1581 PATH). The volume is
built with `tools/mkimage.py d81`; a file is copied onto it and off it, and both are compared on the host.
"""
import glob
import os
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")
DRIVE_DIRS = ["/usr/share/vice/DRIVES", "/usr/lib/vice/DRIVES", "/usr/local/share/vice/DRIVES",
              os.path.expanduser("~/.local/share/vice/DRIVES")]


def rom_1581():
    if "-dos1581" in os.environ.get("BREADBIN_VICE_ARGS", ""):
        return True
    return any(glob.glob(os.path.join(d, "dos1581*")) for d in DRIVE_DIRS)


class With1541(unittest.TestCase):
    """The module loaded, a real (emulated) 1541 DOS on drive 9: it refuses the probe and keeps its mapping."""

    def test_1541_volume_with_the_module_loaded(self):
        img9 = os.path.join(ROOT, "build", "t_d81_1541.d64")
        with open(IMAGE, "rb") as f, open(img9, "wb") as g:
            g.write(f.read())
        with Vice(IMAGE, extra=["-drive9type", "1541", "-9", img9]) as v:
            v.wait_shell()
            self.assertEqual(v.run("mod load /lib/km/d81"), "")
            self.assertIn("(d81)", v.run("mod ls"))
            self.assertEqual(v.run("mount 9 /mnt"), "")
            self.assertIn("drive 9 on /mnt (c64fs)", v.run("mount"))
            v.run("cp /etc/help /mnt/tmp/help")
            self.assertEqual(v.run("/mnt/bin/echo from drive 9"), "from drive 9")
            self.assertEqual(v.run("umount /mnt"), "")
            self.assertEqual(v.run("mod unload 0"), "")
            self.assertNotIn("d81", v.run("mod ls"))
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkimage.py"), "cat", img9, "/tmp/help"],
                             capture_output=True, check=True)
        with open(os.path.join(ROOT, "rootfs", "etc", "help"), "rb") as f:
            self.assertEqual(out.stdout, f.read())


@unittest.skipUnless(rom_1581(), "no 1581 drive ROM (dos1581*) in VICE's DRIVES directory: run "
                                 "tools/setup-vice-roms.sh or pass -dos1581 in BREADBIN_VICE_ARGS")
class D81(unittest.TestCase):
    def test_copy_to_and_from_a_1581_volume(self):
        mk = os.path.join(ROOT, "tools", "mkimage.py")
        root9 = os.path.join(ROOT, "build", "t_d81root")
        os.makedirs(root9, exist_ok=True)
        with open(os.path.join(ROOT, "rootfs", "home", "readme"), "rb") as f:
            readme = f.read()
        with open(os.path.join(root9, "readme"), "wb") as f:
            f.write(readme)
        img9 = os.path.join(ROOT, "build", "t_vol9.d81")
        subprocess.run([sys.executable, mk, "d81", img9, "--root", root9], check=True, capture_output=True)
        with Vice(IMAGE, extra=["-drive9type", "1581", "-9", img9]) as v:
            v.wait_shell()
            self.assertNotEqual(v.run("mount 9 /mnt"), "")             # without the module: no c64fs found
            self.assertEqual(v.run("mod load /lib/km/d81"), "")
            self.assertIn("(d81)", v.run("mod ls"))
            self.assertEqual(v.run("mount 9 /mnt"), "")
            self.assertIn("drive 9 on /mnt (c64fs)", v.run("mount"))
            self.assertEqual(v.run("ls /mnt").split(), ["readme"])
            v.run("cp /mnt/readme /tmp/r9")
            v.run("cp /tmp/r9 /mnt/back")                              # off the volume and back on
            v.run("cp /etc/help /mnt/help")
            self.assertIn("busy", v.run("mod unload 0"))
            self.assertEqual(v.run("umount /mnt"), "")
            v.run("mod unload 0")
            self.assertNotIn("d81", v.run("mod ls"))
        out = subprocess.run([sys.executable, mk, "cat", img9, "/help"], capture_output=True, check=True)
        with open(os.path.join(ROOT, "rootfs", "etc", "help"), "rb") as f:
            self.assertEqual(out.stdout, f.read())
        out = subprocess.run([sys.executable, mk, "cat", img9, "/readme"], capture_output=True, check=True)
        self.assertEqual(out.stdout, readme)
        out = subprocess.run([sys.executable, mk, "cat", img9, "/back"], capture_output=True, check=True)
        self.assertEqual(out.stdout, readme)


if __name__ == "__main__":
    unittest.main()
