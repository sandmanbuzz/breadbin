#!/usr/bin/env python3
"""python3 -m unittest, with a per-test timer: `tools/ci/timed_unittest.py [unittest args]`.

Same arguments and exit status as `python3 -m unittest`. Each finished test (setUp to tearDown) adds one
line to stderr, `TIMING <seconds> <test id>`, written in one call, so the test's own output cannot split
it. tools/ci/pack.py reads these lines from a sharded run's logs to pack the next layout."""
import sys
import time
import unittest


class Timed(unittest.TextTestResult):
    def startTest(self, test):
        self._t0 = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        sys.stderr.write("\nTIMING %.1f %s\n" % (time.monotonic() - self._t0, test.id()))
        sys.stderr.flush()


class TimedRunner(unittest.TextTestRunner):
    def __init__(self, **kw):
        super().__init__(resultclass=Timed, **kw)


if __name__ == "__main__":
    sys.path.insert(0, "")          # as -m does: test modules come from the working directory
    unittest.main(module=None, argv=["unittest"] + sys.argv[1:], testRunner=TimedRunner)
