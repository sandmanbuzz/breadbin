"""tools/ci/timed_unittest.py: same exit status and results as -m unittest, one TIMING line per test."""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TIMER = os.path.join(HERE, "ci", "timed_unittest.py")


class Timer(unittest.TestCase):
    def run_timed(self, body, *args):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "t_sample.py"), "w") as f:
                f.write(textwrap.dedent(body))
            return subprocess.run([sys.executable, TIMER, "t_sample", *args], cwd=d, capture_output=True, text=True)

    def test_one_timing_line_per_test_and_the_exit_status_is_kept(self):
        r = self.run_timed("""
            import time, unittest
            class A(unittest.TestCase):
                def test_slow(self):
                    time.sleep(0.3); print("interleaved output")
                def test_fails(self):
                    self.fail("no")
        """)
        self.assertEqual(r.returncode, 1, r.stderr)
        lines = [l for l in r.stderr.splitlines() if l.startswith("TIMING ")]
        self.assertEqual(len(lines), 2, r.stderr)
        secs = {l.split()[2]: float(l.split()[1]) for l in lines}
        self.assertGreaterEqual(secs["t_sample.A.test_slow"], 0.3)
        self.assertIn("FAILED (failures=1)", r.stderr)

    def test_passing_run_exits_zero(self):
        r = self.run_timed("import unittest\nclass B(unittest.TestCase):\n    def test_ok(self): pass\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("TIMING 0.0 t_sample.B.test_ok", r.stderr)


if __name__ == "__main__":
    unittest.main()
