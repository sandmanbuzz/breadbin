"""Tests for tools/workspace.py: the manifest sees what tar carries, verify catches damage."""
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workspace as ws  # noqa: E402


def build_tree(root):
    t = os.path.join(root, "tree")
    os.makedirs(os.path.join(t, "sub dir", ".hidden"))
    os.makedirs(os.path.join(t, "empty"))
    deep = os.path.join(t, *["d" * 40] * 5)          # a path well over 100 characters
    os.makedirs(deep)
    for rel, data, mode in [("a.txt", b"alpha\n", 0o644), ("run.sh", b"#!/bin/sh\n", 0o755),
                            ("sub dir/.hidden/x", b"\x00\x01\xff" * 1000, 0o600),
                            (os.path.join("d" * 40, "d" * 40, "d" * 40, "d" * 40, "d" * 40, "f"), b"deep", 0o644)]:
        p = os.path.join(t, rel)
        with open(p, "wb") as f:
            f.write(data)
        os.chmod(p, mode)
    os.symlink("a.txt", os.path.join(t, "link-to-file"))
    os.symlink("sub dir", os.path.join(t, "link-to-dir"))
    os.symlink("missing", os.path.join(t, "dangling"))
    os.link(os.path.join(t, "a.txt"), os.path.join(t, "hard"))
    return t


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tree = build_tree(self.tmp.name)
        self.base, self.items = self.tmp.name, ["tree"]

    def pack(self, out):
        os.makedirs(os.path.join(out, "manifests"))
        lines = ws.manifest(self.base, self.items)
        tarball = os.path.join(out, "w.tar")
        subprocess.run(ws.tar_cmd(tarball, self.base, self.items), check=True, env=ws.TAR_ENV)
        open(os.path.join(out, "manifests", "w.txt"), "w").write("\n".join(lines) + "\n")
        open(os.path.join(out, "SHA256SUMS"), "w").write(f"{ws.sha256_file(tarball)}  w.tar\n")
        json.dump([dict(name="w", items=self.items, note="", files=len(lines))], open(os.path.join(out, "packages.json"), "w"))
        return tarball

    def verify(self, out, dest):
        with self.assertRaises(SystemExit) as r, contextlib.redirect_stdout(io.StringIO()):
            ws.cmd_verify(argparse.Namespace(outdir=out, dest=dest))
        return r.exception.code

    def test_file_and_symlink_items(self):
        open(os.path.join(self.base, "one.log"), "w").write("x")
        os.symlink("tree", os.path.join(self.base, "toplink"))
        self.items = ["tree", "one.log", "toplink"]
        out = os.path.join(self.tmp.name, "out")
        self.pack(out)
        self.assertEqual(self.verify(out, os.path.join(self.tmp.name, "dest")), 0)

    def test_item_named_like_an_option(self):
        os.makedirs(os.path.join(self.base, "-Users-x-proj"))
        open(os.path.join(self.base, "-Users-x-proj", "m"), "w").write("memory")
        self.items = ["tree", "-Users-x-proj"]
        out = os.path.join(self.tmp.name, "out")
        self.pack(out)
        self.assertEqual(self.verify(out, os.path.join(self.tmp.name, "dest")), 0)

    def test_manifest_covers_every_kind(self):
        kinds = {l[0] for l in ws.manifest(self.base, self.items)}
        self.assertEqual(kinds, {"f", "d", "l"})
        text = "\n".join(ws.manifest(self.base, self.items))
        self.assertIn("link-to-file -> a.txt", text)
        self.assertIn("dangling -> missing", text)
        self.assertIn(".hidden/x", text)

    def test_round_trip_matches(self):
        out = os.path.join(self.tmp.name, "out")
        self.pack(out)
        self.assertEqual(self.verify(out, os.path.join(self.tmp.name, "dest")), 0)

    def test_damaged_unpack_is_caught(self):
        out = os.path.join(self.tmp.name, "out")
        tarball = self.pack(out)
        # a tarball with one changed byte keeps its size but not its hash
        data = bytearray(open(tarball, "rb").read())
        data[len(data) // 2] ^= 0xFF
        open(tarball, "wb").write(bytes(data))
        self.assertEqual(self.verify(out, os.path.join(self.tmp.name, "dest")), 1)

    def test_changed_file_after_manifest_is_caught(self):
        out = os.path.join(self.tmp.name, "out")
        os.makedirs(os.path.join(out, "manifests"))
        lines = ws.manifest(self.base, self.items)
        with open(os.path.join(self.tree, "a.txt"), "ab") as f:      # a writer got in before the tar
            f.write(b"late write\n")
        tarball = os.path.join(out, "w.tar")
        subprocess.run(ws.tar_cmd(tarball, self.base, self.items), check=True, env=ws.TAR_ENV)
        open(os.path.join(out, "manifests", "w.txt"), "w").write("\n".join(lines) + "\n")
        open(os.path.join(out, "SHA256SUMS"), "w").write(f"{ws.sha256_file(tarball)}  w.tar\n")
        json.dump([dict(name="w", items=self.items, note="", files=len(lines))], open(os.path.join(out, "packages.json"), "w"))
        self.assertEqual(self.verify(out, os.path.join(self.tmp.name, "dest")), 1)

    def test_mode_change_is_caught(self):
        a = ws.manifest(self.base, self.items)
        os.chmod(os.path.join(self.tree, "run.sh"), 0o700)
        self.assertNotEqual(a, ws.manifest(self.base, self.items))

    def test_nonempty_destination_refused(self):
        out = os.path.join(self.tmp.name, "out")
        self.pack(out)
        dest = os.path.join(self.tmp.name, "dest")
        os.makedirs(os.path.join(dest, "w"))
        open(os.path.join(dest, "w", "x"), "w").close()
        with self.assertRaises(SystemExit) as r:
            ws.cmd_verify(argparse.Namespace(outdir=out, dest=dest))
        self.assertIn("not empty", str(r.exception.code))


if __name__ == "__main__":
    unittest.main()
