#!/usr/bin/env python3
"""The examples in docs/manual/*.md are run: a ```bas block is a program (ending in BUILD), the ```out
block after it is what brun prints for the built file, and RUN of the same program (without BUILD)
must print the same. The books cannot drift from the program."""
import glob
import os
import re
import unittest

from test_bas import bas, brun

MANUAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "manual")
BLOCK = re.compile(r"^```bas\n(.*?)^```\n+```out\n(.*?)^```", re.S | re.M)


def examples():
    for path in sorted(glob.glob(os.path.join(MANUAL, "*.md"))):
        with open(path) as f:
            for m in BLOCK.finditer(f.read()):
                yield os.path.basename(path), m.group(1), m.group(2)


class Manual(unittest.TestCase):
    def test_there_are_examples(self):
        self.assertGreaterEqual(len(list(examples())), 2)

    def test_the_examples_print_what_the_book_says(self):
        for name, prog, want in examples():
            self.assertTrue(prog.rstrip().endswith("BUILD"), (name, prog))
            bx, st = bas(prog)
            self.assertEqual(st, 0, (name, bx[:60]))
            self.assertEqual(brun(bx.encode("latin-1"))[0], want, (name, prog))
            ran, st = bas(prog.rstrip()[:-len("BUILD")] + "RUN\n")
            self.assertEqual(ran, want, (name, "RUN differs from brun"))


if __name__ == "__main__":
    unittest.main()
