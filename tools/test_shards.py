"""Host-only checks of the sharded VICE suite (tools/ci/shards.txt, sharded.sh): no VICE, no podman."""
import os
import subprocess
import sys
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
        # Console and Keyboard (real speed, fixed sleeps) never share a container with other classes
        for n, specs in sl.items():
            if any(s.startswith(("tests.test_console", "tests.test_keyboard")) for s in specs):
                self.assertTrue(all(s.startswith(("tests.test_console", "tests.test_keyboard")) for s in specs), n)
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
        drives = [(n, ss) for n, ss in shards.shards() if any(s.startswith("tests.test_system.Drives") for s in ss)]
        self.assertEqual(shards.problems(drives, ids, len(drives)), [])

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


if __name__ == "__main__":
    unittest.main()
