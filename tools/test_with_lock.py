"""Tests for tools/with-lock under the system /bin/sh (dash on Debian: no file descriptors
above 9, which the first exclusive mode needed). Sleeps are short; -t takes whole seconds; skipped without flock(1)."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "with-lock")


@unittest.skipUnless(shutil.which("flock"), "needs flock(1)")
class WithLock(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.env = dict(os.environ, BREADBIN_LOCKDIR=self.dir.name, BREADBIN_VICE_SLOTS="3")
        self.env.pop("BREADBIN_LOCK_HELD", None)

    def run_lock(self, *args, env=None, **kw):
        return subprocess.run([LOCK, *args], env=env or self.env, capture_output=True, text=True, **kw)

    def start(self, *args, env=None):
        return subprocess.Popen([LOCK, *args], env=env or self.env, stderr=subprocess.DEVNULL)

    def test_exit_status_passes_through(self):
        self.assertEqual(self.run_lock("--", "sh", "-c", "exit 5").returncode, 5)
        self.assertEqual(self.run_lock("-x", "--", "sh", "-c", "exit 7").returncode, 7)

    def test_exclusive_works_with_many_slots(self):
        env = dict(self.env, BREADBIN_VICE_SLOTS="12")       # slots past fd 9
        self.assertEqual(self.run_lock("-x", "--", "true", env=env).returncode, 0)

    def test_plain_runs_share_up_to_the_cap(self):
        held = [self.start("--", "sleep", "2.5") for _ in range(3)]
        time.sleep(0.4)
        self.assertEqual(self.run_lock("-t", "1", "--", "true").returncode, 75)
        for p in held:
            p.wait()
        self.assertEqual(self.run_lock("-t", "5", "--", "true").returncode, 0)

    def test_exclusive_waits_for_runners_and_is_not_overtaken(self):
        log = os.path.join(self.dir.name, "order")
        sh = lambda tag, nap: ["--", "sh", "-c", f"echo {tag}-start >>{log}; sleep {nap}; echo {tag}-end >>{log}"]
        a = self.start(*sh("A", 1.2)); time.sleep(0.4)
        x = self.start("-x", *sh("X", 0.5)); time.sleep(0.4)
        b = self.start(*sh("B", 0))
        for p in (a, x, b):
            p.wait()
        self.assertEqual(open(log).read().split(), ["A-start", "A-end", "X-start", "X-end", "B-start", "B-end"])

    def test_exclusive_times_out_while_a_plain_run_holds_a_slot(self):
        held = self.start("--", "sleep", "2.5"); time.sleep(0.4)
        self.assertEqual(self.run_lock("-x", "-t", "1", "--", "true").returncode, 75)
        held.wait()

    def test_nesting(self):
        self.assertEqual(self.run_lock("--", LOCK, "--", "true").returncode, 0)
        self.assertEqual(self.run_lock("-x", "--", LOCK, "--", LOCK, "-x", "--", "true").returncode, 0)
        r = self.run_lock("--", LOCK, "-x", "--", "true")
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot take it exclusively", r.stderr)

    def test_ultimate_is_a_single_holder_and_no_holder_files_are_left(self):
        held = self.start("-r", "ultimate", "--", "sleep", "2.5"); time.sleep(0.4)
        self.assertEqual(self.run_lock("-r", "ultimate", "-t", "1", "--", "true").returncode, 75)
        held.wait()
        self.assertEqual([f for f in os.listdir(self.dir.name) if f.endswith(".holder")], [])


if __name__ == "__main__":
    unittest.main()
