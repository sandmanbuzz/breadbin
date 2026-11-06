"""Tests for tools/land.sh under the system /bin/sh: the dirty-tree refusal names each file and its owner."""
import os
import subprocess
import tempfile
import unittest

LAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "land.sh")
MAIL = "344811358+sandmanbuzz@users.noreply.github.com"


class LandDirty(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="sandmanbuzz", GIT_AUTHOR_EMAIL=MAIL,
                        GIT_COMMITTER_NAME="sandmanbuzz", GIT_COMMITTER_EMAIL=MAIL,
                        GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")

    def git(self, *args, env=None):
        subprocess.run(["git", "-C", self.dir.name, *args], env=env or self.env, check=True, capture_output=True)

    def test_refusal_names_file_and_owner(self):
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        with open(os.path.join(self.dir.name, "tracked.txt"), "w") as f:
            f.write("a\n")
        self.git("add", "tracked.txt")
        other = dict(self.env, GIT_AUTHOR_NAME="Alice Owner", GIT_COMMITTER_NAME="Alice Owner")
        self.git("commit", "-q", "-m", "x", env=other)
        with open(os.path.join(self.dir.name, "tracked.txt"), "w") as f:
            f.write("b\n")
        with open(os.path.join(self.dir.name, "new.txt"), "w") as f:
            f.write("n\n")
        r = subprocess.run(["/bin/sh", LAND, "main"], cwd=self.dir.name, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not clean", r.stderr)
        self.assertIn("tracked.txt  (Alice Owner)", r.stderr)
        self.assertIn("new.txt  (uncommitted (no owner))", r.stderr)


if __name__ == "__main__":
    unittest.main()
