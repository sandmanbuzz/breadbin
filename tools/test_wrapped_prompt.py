"""Host-only: the VICE harness finds the end of a typed command even when the line wraps at 40 columns.

    python3 -m unittest discover -s tools -p 'test_wrapped_prompt.py'
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vicetest import command_end_row  # noqa: E402

PROMPT = "/ $"


class CommandEndRow(unittest.TestCase):
    def test_a_short_line_is_one_row(self):
        lines = ["/ $ echo two | tee /c1 /c2", "two", PROMPT]
        self.assertEqual(command_end_row(lines, "$ echo two | tee /c1 /c2"), 0)

    def test_a_wrapped_line_ends_on_its_last_row(self):
        # the 42-column line from the three-file tee: row 0 is 40 columns, row 1 the rest
        lines = ["/ $ echo three | tee /home/p1 /home/p2 /", "home/p3", "three", PROMPT]
        self.assertEqual(command_end_row(lines, "$ echo three | tee /home/p1 /home/p2 /home/p3"), 1)

    def test_a_wrap_on_a_space_still_matches(self):
        # the break falls on a space: the screen drops the trailing space of row 0
        lines = ["/ $ echo a | tee /home/x1 /home/x2", "/home/x3", "a", PROMPT]
        self.assertEqual(command_end_row(lines, "$ echo a | tee /home/x1 /home/x2 /home/x3"), 1)

    def test_a_long_command_wrapping_over_three_rows(self):
        command = "echo " + "abcdefghij" * 9
        want = "$ " + command
        screen = "/ " + want                       # the prompt and the echo, as the screen holds them
        rows = [screen[i:i + 40] for i in range(0, len(screen), 40)]
        lines = rows + ["out", PROMPT]
        self.assertGreaterEqual(len(rows), 3)     # it really wraps over three or more rows
        self.assertEqual(command_end_row(lines, want), (len(screen) - 1) // 40)

    def test_an_old_echo_is_not_the_one(self):
        lines = ["/ $ echo x", "x", "/ $ echo y", "y", PROMPT]
        self.assertEqual(command_end_row(lines, "$ echo x"), 0)

    def test_missing_command_is_none(self):
        self.assertIsNone(command_end_row(["/ $ ls", "bin", PROMPT], "$ echo nothere"))


if __name__ == "__main__":
    unittest.main()
