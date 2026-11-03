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
        for n, text in flat.items():   # Drives writes the master image: nothing that boots it may follow
            if "Drives" in text:
                self.assertNotIn("Cache", text.split("Drives")[1], n)
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

class Driver(unittest.TestCase):
    def test_script_parses_and_check_mode_runs(self):
        script = os.path.join(ROOT, "tools", "ci", "sharded.sh")
        self.assertEqual(subprocess.run(["bash", "-n", script]).returncode, 0)
        r = subprocess.run([script, "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"^count \d+\n$")

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

    def test_verdict_needs_expect(self):
        r = subprocess.run([self.SCRIPT, "--verdict", "/nonexistent"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
