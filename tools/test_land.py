"""Tests for tools/land.sh under the system /bin/sh: the dirty-tree refusal names each file and its owner."""
import os
import shutil
import subprocess
import tempfile
import unittest

LAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "land.sh")
MAIL = "344811358+sandmanbuzz@users.noreply.github.com"


@unittest.skipUnless(shutil.which("git"), "git is not in the CI image; land.sh is a host tool")
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


@unittest.skipUnless(shutil.which("git") and shutil.which("make"), "land.sh needs git and make")
class LandAnywhere(unittest.TestCase):
    """land.sh depends on neither where the clone sits nor which branch is checked out."""

    def test_lands_from_moved_clone_on_other_branch(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = dict(os.environ, GIT_AUTHOR_NAME="sandmanbuzz", GIT_AUTHOR_EMAIL=MAIL,
                   GIT_COMMITTER_NAME="sandmanbuzz", GIT_COMMITTER_EMAIL=MAIL,
                   GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
        old = os.path.join(tmp.name, "old")
        os.makedirs(old)

        def git(where, *args):
            subprocess.run(["git", "-C", where, *args], env=env, check=True, capture_output=True)

        git(old, "init", "-q", "-b", "main")
        git(old, "config", "commit.gpgsign", "false")
        with open(os.path.join(old, "Makefile"), "w") as f:
            f.write(".PHONY: clean all test-host\nclean all test-host:\n\t@true\n")
        git(old, "add", "Makefile")
        git(old, "commit", "-q", "-m", "base")
        git(old, "switch", "-q", "-c", "feature")
        with open(os.path.join(old, "f.txt"), "w") as f:
            f.write("f\n")
        git(old, "add", "f.txt")
        git(old, "commit", "-q", "-m", "feature")
        git(old, "switch", "-q", "-c", "elsewhere", "main")  # the checkout is not on main
        new = os.path.join(tmp.name, "moved", "deeper", "clone")
        os.makedirs(os.path.dirname(new))
        shutil.move(old, new)
        r = subprocess.run(["/bin/sh", LAND, "feature"], cwd=new, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("committed", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(new, "f.txt")))
        branch = subprocess.run(["git", "-C", new, "rev-parse", "--abbrev-ref", "HEAD"], env=env,
                                capture_output=True, text=True).stdout.strip()
        self.assertEqual(branch, "elsewhere")


if __name__ == "__main__":
    unittest.main()
