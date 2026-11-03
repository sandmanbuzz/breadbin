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

    def test_lock_dir_with_spaces_and_a_neighbouring_file_survive(self):
        # the holder list used to be split on spaces: "<dir>/my locks" made -x write over
        # and then delete an unrelated file named "<dir>/my"
        base = tempfile.mkdtemp(dir=self.dir.name)
        neighbour = os.path.join(base, "my")
        open(neighbour, "w").write("keep")
        env = dict(self.env, BREADBIN_LOCKDIR=os.path.join(base, "my locks"))
        self.assertEqual(self.run_lock("-x", "--", "true", env=env).returncode, 0)
        self.assertEqual(open(neighbour).read(), "keep")

    def test_exclusive_wait_is_bounded_by_t(self):
        held = [self.start("--", "sleep", "4") for _ in range(2)]
        time.sleep(0.5)
        t0 = time.time()
        self.assertEqual(self.run_lock("-x", "-t", "2", "--", "true").returncode, 75)
        self.assertLess(time.time() - t0, 3.5)
        for p in held:
            p.wait()

    def test_plain_wait_is_bounded_by_t(self):
        held = [self.start("--", "sleep", "4") for _ in range(3)]
        time.sleep(0.5)
        t0 = time.time()
        self.assertEqual(self.run_lock("-t", "1", "--", "true").returncode, 75)
        self.assertLess(time.time() - t0, 2.5)
        for p in held:
            p.wait()

    def test_exclusive_covers_slot_files_beyond_its_own_cap(self):
        # a session whose environment says 3 slots must still exclude a holder of slot 5
        lf = os.path.join(self.dir.name, "vice.5.lock")
        holder = subprocess.Popen(["flock", lf, "sleep", "3"])
        time.sleep(0.5)
        self.assertEqual(self.run_lock("-x", "-t", "1", "--", "true").returncode, 75)
        holder.wait()

    def test_stale_holder_file_is_not_reported_as_busy(self):
        open(os.path.join(self.dir.name, "vice.holder"), "w").write("someone dead\n")
        r = self.run_lock("-x", "--", "true")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("busy", r.stderr)

    def test_internal_variables_do_not_leak_into_the_command(self):
        r = self.run_lock("-x", "--", "sh", "-c", "env | grep -c '^WITH_LOCK_' || true")
        self.assertEqual(r.stdout.strip(), "0")

    def test_non_integer_timeout_is_refused(self):
        r = self.run_lock("-t", "0.5", "--", "true")
        self.assertEqual(r.returncode, 2)
        self.assertIn("whole seconds", r.stderr)


if __name__ == "__main__":
    unittest.main()
