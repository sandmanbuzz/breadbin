"""vprof against the machine's own counters: the tracepoint count at fast.km's success label equals
the blocks the module says it carried over the same command (VICE, real speed, host ROMs; slow)."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import vprof  # noqa: E402
import test_fast as tf  # noqa: E402


@unittest.skipUnless(os.path.exists(os.path.join(ROOT, "build", "mod", "fast.lbl")), "fast.km not built")
class Counters(unittest.TestCase):
    def test_trace_count_equals_blocks_carried(self):
        lbl = tf.labels()

        def peek(v, base_of):
            base = base_of("fast")
            ng = v.mem(base + lbl["ft_ng"], base + lbl["ft_ng"] + 1)
            return ng[0] | ng[1] << 8
        r = vprof.profile(os.path.join(ROOT, "build", "breadbin.d64"), "wc /bin/passwd",
                          ["fast:ft_good"], anchor="fast:ft_good", setup=["mod load /lib/km/fast"], peek=peek)
        carried = r["peek"][1] - r["peek"][0]
        self.assertGreater(carried, 20)             # a real multi-block read, not a trivial run
        self.assertEqual(r["events"], carried)
        self.assertEqual(r["anchors"], carried)


if __name__ == "__main__":
    unittest.main()
