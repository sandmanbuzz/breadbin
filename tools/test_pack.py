"""tools/ci/pack.py: every VICE test in exactly one bin, the ordering rules hold, TIMING lines are read."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ci"))
import pack  # noqa: E402
import shards  # noqa: E402


class Pack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ids = shards.discovered()

    def durations(self, seconds=5.0):
        # uneven on purpose: a few long tests, the rest short
        return {i: (seconds * 40 if ("Drives" in i or "Cache" in i or "Compiled" in i) else seconds)
                for i in self.ids}

    def test_every_test_once_and_the_rules_hold(self):
        bins = pack.pack(self.ids, self.durations(), 6)
        named = [("s%d" % n, sp) for n, (_, sp) in enumerate(bins, 1)]
        self.assertEqual(shards.problems(named, self.ids, 6), [])     # every test in exactly one bin
        for _, sp in bins:
            seen_drives = False
            for s in sp:
                if ".Drives." in s:
                    seen_drives = True
                elif seen_drives:
                    self.fail("a spec follows a Drives spec: " + s)
        boot_order = [s for _, sp in bins for s in sp if ".Boot." in s]
        self.assertEqual(boot_order, sorted(boot_order))
        self.assertLessEqual(len([1 for _, sp in bins if any(".Boot." in s for s in sp)]), 2)

    def test_console_and_keyboard_stay_whole_modules(self):
        bins = pack.pack(self.ids, self.durations(), 6)
        specs = [s for _, sp in bins for s in sp]
        for s in specs:
            if s.startswith(("tests.test_console", "tests.test_keyboard")):
                self.assertIn(s, ("tests.test_console", "tests.test_keyboard"))

    def test_timing_lines_are_read_even_after_dots(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
            f.write("..FTIMING 1.5 tests.test_x.A.test_one\n")       # not at line start: still read
            f.write("\nTIMING 2.0 tests.test_x.A.test_two\nsomething else\n")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(pack.measured([f.name]), {"tests.test_x.A.test_one": 1.5, "tests.test_x.A.test_two": 2.0})


if __name__ == "__main__":
    unittest.main()
