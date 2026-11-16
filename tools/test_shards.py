"""Host-only checks of the sharded VICE suite (tools/ci/shards.txt, sharded.sh): no VICE, no podman."""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "ci"))
import shards  # noqa: E402


class ShardList(unittest.TestCase):
    def test_every_vice_test_is_in_exactly_one_shard(self):
        ids = shards.discovered()
        self.assertGreater(len(ids), 50)
        self.assertEqual(shards.problems(shards.shards(), ids, 6), [])

    def test_a_new_test_would_be_caught(self):
        ids = shards.discovered() + ["tests.test_system.Boot2.test_new", "tests.test_x.X.test_y"]
        bad = shards.problems(shards.shards(), ids, 6)
        self.assertEqual(sorted(b.split()[-1] for b in bad),
                         ["tests.test_system.Boot2.test_new", "tests.test_x.X.test_y"])

    def test_overlap_and_dead_specs_are_caught(self):
        ids = ["a.A.t1", "a.A.t2", "a.B.t1"]
        self.assertEqual(shards.problems([("x", ["a.A"]), ("y", ["a.A.t2", "a.B"])], ids, 6),
                         ["in 2 shards (x, y): a.A.t2"])
        self.assertIn("x: spec matches no test: a.C", shards.problems([("x", ["a.A", "a.B", "a.C"])], ids, 6))
        self.assertIn("2 shards > 1 slots", shards.problems([("x", ["a.A"]), ("y", ["a.B"])], ids, 1))

    def test_a_prefix_is_not_a_match(self):
        # "Cache" must not claim "CacheX"
        self.assertEqual(shards.problems([("x", ["m.Cache"])], ["m.CacheX.t"], 6),
                         ["uncovered m.CacheX.t", "x: spec matches no test: m.Cache"])

    def test_rules_in_the_file(self):
        sl = dict(shards.shards())
        self.assertEqual(len(sl), len(shards.shards()))
        flat = {n: " ".join(s) for n, s in sl.items()}
        # Drives.test_boot_from_drive_9 writes the master image: nothing that boots from it may follow a
        # Drives spec in the same shard (the old check looked only between the first two "Drives")
        master = ("Cache", "Pipes", "Touch", "Pool", "Exec", "Modules", "REU", "Persistence", "Boot")
        for n, specs in sl.items():
            seen_drives = False
            for s in specs:
                if ".Drives" in s:
                    seen_drives = True
                elif seen_drives:
                    self.assertFalse(any(("." + m + ".") in s or s.endswith("." + m) for m in master),
                                     "%s: %s follows a Drives spec" % (n, s))
        # Console and Keyboard (real speed, fixed sleeps) run whole, never split by method; they may share
        # a container with other classes, since tests in one container run one after another
        for n, specs in sl.items():
            for s in specs:
                if s.startswith(("tests.test_console", "tests.test_keyboard")):
                    self.assertIn(s, ("tests.test_console", "tests.test_keyboard"), n)
        # Boot: if split, into contiguous halves, each in Boot's own (alphabetical) order
        boot = [(n, [s for s in specs if s.startswith("tests.test_system.Boot.")]) for n, specs in sl.items()]
        boot = [(n, s) for n, s in boot if s]
        flat = [m for _, ms in boot for m in ms]
        self.assertEqual(flat, sorted(flat))
        self.assertLessEqual(len(boot), 2)   # two halves at most: each extra half is another cold boot
        for n, ms in boot:
            self.assertEqual(ms, sorted(ms), n)


    def test_drives_is_split_by_method(self):
        # Drives is the long pole: each of its methods in exactly one shard, never the whole class
        ids = [i for i in shards.discovered() if i.startswith("tests.test_system.Drives.")]
        self.assertEqual(len(ids), 5, ids)
        specs = [s for _, ss in shards.shards() for s in ss if s.startswith("tests.test_system.Drives")]
        self.assertTrue(all(s.rsplit(".", 1)[1].startswith("test_") for s in specs), specs)
        self.assertEqual(sorted(specs), sorted(ids))
        drives = [(n, [s for s in ss if s.startswith("tests.test_system.Drives")]) for n, ss in shards.shards()]
        self.assertEqual(shards.problems([(n, ss) for n, ss in drives if ss], ids, 6), [])

class Strict(unittest.TestCase):
    def test_a_class_and_its_method_in_one_shard_count_twice(self):
        bad = shards.problems([("x", ["a.A", "a.A.t1"])], ["a.A.t1", "a.A.t2"], 6)
        self.assertEqual(bad, ["in 2 shards (x, x): a.A.t1"])

    def test_a_shard_line_without_specs_or_bar_is_refused(self):
        import tempfile
        for line in ("s1", "s1|", "|a.A"):
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
                f.write("# c\n" + line + "\n")
            self.addCleanup(os.unlink, f.name)
            with self.assertRaises(ValueError):
                shards.shards(f.name)

    def test_the_drives_rule_catches_a_split_drives(self):
        # the shape the old text check missed: Drives.a Drives.b then a master-image class
        specs = ["tests.test_system.Drives.a", "tests.test_system.Drives.b", "tests.test_system.Cache.x"]
        master = ("Cache", "Pipes", "Touch", "Pool", "Exec", "Modules", "REU", "Persistence", "Boot")
        seen, hit = False, False
        for s in specs:
            if ".Drives" in s:
                seen = True
            elif seen and any(("." + m + ".") in s or s.endswith("." + m) for m in master):
                hit = True
        self.assertTrue(hit)


class Driver(unittest.TestCase):
    def test_script_parses_and_check_mode_runs(self):
        script = os.path.join(ROOT, "tools", "ci", "sharded.sh")
        self.assertEqual(subprocess.run(["bash", "-n", script]).returncode, 0)
        r = subprocess.run([script, "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"^count \d+\n")
        # per-shard expected counts are also emitted (H1 hardening)
        for line in r.stdout.strip().splitlines():
            if line.startswith("per_shard "):
                parts = line.split()
                self.assertEqual(len(parts), 3)
                self.assertGreaterEqual(int(parts[2]), 0)

    def test_check_mode_fails_when_slots_are_fewer_than_shards(self):
        script = os.path.join(ROOT, "tools", "ci", "sharded.sh")
        r = subprocess.run([script, "--check"], capture_output=True, text=True,
                           env=dict(os.environ, BREADBIN_VICE_SLOTS="2"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("shards > 2 slots", r.stderr)

    def test_bad_option(self):
        script = os.path.join(ROOT, "tools", "ci", "sharded.sh")
        self.assertEqual(subprocess.run([script, "--nope"], capture_output=True).returncode, 2)


class Verdict(unittest.TestCase):
    """The red/green judgement of sharded.sh on logs from REAL unittest runs (a stub run would only
    prove the stub): green, failing test, skipped test, crash with no Ran line, wrong count."""
    SCRIPT = os.path.join(ROOT, "tools", "ci", "sharded.sh")
    BODY = {
        "green": "def test_a(self): pass\n    def test_b(self): pass\n",
        "red": "def test_a(self): pass\n    def test_b(self): self.assertEqual(1, 2)\n",
        "skip": "def test_a(self): pass\n    def test_b(self): self.skipTest('no display')\n",
    }

    def real_log(self, d, name, kind):
        """Run a tiny real unittest module and store its stderr+stdout the way run.sh would,
        every line prefixed with an epoch stamp. Returns the exit code of the run."""
        src = "import unittest\nclass T(unittest.TestCase):\n    " + self.BODY[kind] + \
              "unittest.main()\n"
        r = subprocess.run([sys.executable, "-I", "-c", src, "-v"], capture_output=True, text=True,
                           cwd=d)
        lines = (r.stderr + r.stdout).splitlines()
        with open(os.path.join(d, name + ".log"), "w") as f:
            for l in lines:
                f.write("1700000000.5 %s\n" % l)
        with open(os.path.join(d, name + ".rc"), "w") as f:
            f.write("%d\n" % r.returncode)
        for ext in ("start", "end"):
            with open(os.path.join(d, name + "." + ext), "w") as f:
                f.write("1700000000\n")
        return r.returncode

    def judge(self, kinds, expect, drop=()):
        d = tempfile.mkdtemp(prefix="verdict-")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", "--", d]))
        names = ["s%d" % i for i in range(len(kinds))]
        with open(os.path.join(d, "names"), "w") as f:
            f.write("".join(n + "\n" for n in names))
        for n, k in zip(names, kinds):
            self.real_log(d, n, k)
        for n in drop:      # a shard that left no files at all (the container never ran)
            for ext in ("log", "rc", "end"):
                p = os.path.join(d, n + "." + ext)
                if os.path.exists(p):
                    os.remove(p)
        r = subprocess.run([self.SCRIPT, "--verdict", d, "--expect", str(expect)],
                           capture_output=True, text=True)
        return r, d

    def test_green_is_green(self):
        r, d = self.judge(["green", "green"], 4)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("sharded: PASS", r.stdout)

    def test_a_failing_test_is_red_and_its_block_comes_first(self):
        r, d = self.judge(["green", "red", "green"], 6)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL", r.stdout)
        self.assertIn("rc=1", r.stdout)
        with open(os.path.join(d, "merged.log")) as f:
            merged = f.read()
        first = merged.splitlines()[0]
        self.assertTrue(first.startswith("[s1] "), first)      # the failure section leads
        self.assertIn("AssertionError", merged)

    def test_a_skipped_test_is_red_even_with_rc_zero(self):
        r, d = self.judge(["green", "skip"], 4)
        with open(os.path.join(d, "s1.rc")) as f:
            self.assertEqual(f.read().strip(), "0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("SKIPS", r.stdout)

    def test_a_shard_that_never_ran_is_red(self):
        r, d = self.judge(["green", "green"], 4, drop=["s1"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no-Ran-line", r.stdout)
        self.assertIn("rc=99", r.stdout)

    def test_wrong_total_is_red(self):
        r, d = self.judge(["green", "green"], 5)
        self.assertEqual(r.returncode, 1)
        self.assertIn("test count mismatch", r.stderr)

    def test_compensating_per_shard_counts_are_red(self):
        """H1 regression: one shard under by N, another over by N, aggregate equal -> red."""
        r, d = self.judge(["green", "green"], 4)
        # Write expected_counts: shard s0 expects 2, shard s1 expects 2
        with open(os.path.join(d, "expected_counts"), "w") as f:
            f.write("s0 2\ns1 2\n")
        # Now make s0 report 1 (under by 1) and s1 report 3 (over by 1)
        # The aggregate is still 4 = expect, but per-shard counts don't match
        with open(os.path.join(d, "s0.log")) as f:
            content = f.read()
        content = content.replace("Ran 2 tests", "Ran 1 tests")
        with open(os.path.join(d, "s0.log"), "w") as f:
            f.write(content)
        with open(os.path.join(d, "s1.log")) as f:
            content = f.read()
        content = content.replace("Ran 2 tests", "Ran 3 tests")
        with open(os.path.join(d, "s1.log"), "w") as f:
            f.write(content)
        r = subprocess.run([self.SCRIPT, "--verdict", d, "--expect", "4"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("per-shard", r.stdout)
        self.assertIn("1/2", r.stdout)
        self.assertIn("3/2", r.stdout)

    def test_verdict_needs_expect(self):
        r = subprocess.run([self.SCRIPT, "--verdict", "/nonexistent"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


def _git_ok():
    try:       # the CI container has no git: these tests run on the host
        r = subprocess.run(["git", "-C", ROOT, "cat-file", "-e", "HEAD:tools/ci/shards.py"], capture_output=True)
    except OSError:
        return False
    return r.returncode == 0


STUB = """#!/bin/sh
# stand-in for tools/ci/run.sh: `all test-host` succeeds at once; `test-only` hangs until told to stop
case "$1" in all) echo "Ran 1 test in 0.1s"; echo OK; exit 0 ;; esac
d="$STUB_DIR"
trap 'echo stopped > "$d/stopped.$$"; kill $s 2>/dev/null; exit 143' TERM INT
echo started > "$d/started.$$"
sleep 120 &
s=$!
wait $s
"""


@unittest.skipUnless(_git_ok(), "needs the repo's git history")
class DriverRuns(unittest.TestCase):
    """The driver against a stub run.sh: a hung shard and Ctrl-C (no VICE, no podman)."""
    SCRIPT = os.path.join(ROOT, "tools", "ci", "sharded.sh")

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="sharded-test-")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", "--", self.d]))
        self.stub = os.path.join(self.d, "run.sh")
        with open(self.stub, "w") as f:
            f.write(STUB)
        os.chmod(self.stub, 0o755)
        self.out = os.path.join(self.d, "out")
        self.args = [self.SCRIPT, "--no-outer-lock", "--no-preflight", "--run-sh", self.stub,
                     "--stagger", "0", "--out", self.out, "--rev", "HEAD"]
        self.env = dict(os.environ, STUB_DIR=self.d)

    def test_a_hung_shard_is_killed_and_reads_red(self):
        r = subprocess.run(self.args + ["--shard-timeout", "3"], capture_output=True, text=True,
                           env=self.env, timeout=120)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("rc=124 timeout", r.stdout)
        self.assertIn("sharded: FAIL", r.stdout)

    def test_ctrl_c_stops_every_shard(self):
        import signal
        import time
        p = subprocess.Popen(self.args, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            n = len(shards.shards())
            deadline = time.time() + 60
            while time.time() < deadline and len([f for f in os.listdir(self.d) if f.startswith("started.")]) < n:
                time.sleep(0.2)
            self.assertEqual(len([f for f in os.listdir(self.d) if f.startswith("started.")]), n)
            p.send_signal(signal.SIGINT)
            p.wait(timeout=60)
        finally:
            if p.poll() is None:
                p.kill()
            p.stdout.close()
            p.stderr.close()
        self.assertEqual(p.returncode, 130)
        # each stub writes its stopped file from its TERM trap, after the driver's wait can already
        # have returned: poll for it (a fixed read right after p.wait was a race)
        deadline = time.time() + 60
        while time.time() < deadline and len([f for f in os.listdir(self.d) if f.startswith("stopped.")]) < n:
            time.sleep(0.2)
        stopped = [f for f in os.listdir(self.d) if f.startswith("stopped.")]
        self.assertEqual(len(stopped), n, "every shard's run.sh must get the signal and clean up")


if __name__ == "__main__":
    unittest.main()
