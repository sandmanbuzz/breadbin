"""edit (src/bin/edit.s) on the host: the real program under py65 with keys on stdin (tools/asim.py), no VICE.

Ported from upstream Breadbin (kpatr1981/breadbin, MIT, Copyright 2026 Konstantinos Patronas; commits by
tuksutukio) tests a73842c, which drive VICE; here the same behaviours are checked on the host, plus a
screen model that follows the console escapes (ESC = row col, ESC K, ESC R/r, FF).

    python3 -m unittest tools.test_edit

Needs `make` (build/root/bin/edit) and py65; skips otherwise.
"""
import os
import random
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asim  # noqa: E402

ROOT = asim.ROOT
BUILT = os.path.exists(os.path.join(ROOT, "build", "root", "bin", "edit"))
SKIP = "py65 not installed" if asim.MPU is None else (None if BUILT else "not built (make)")

with open(os.path.join(ROOT, "src", "bin", "edit.s")) as _f:
    TEXTMAX = int(re.search(r"^TEXTMAX\s*=\s*(\d+)", _f.read(), re.M).group(1))

UP, DOWN, LEFT, RIGHT, HOME, DEL, RET = 0x10, 0x0E, 0x02, 0x06, 0x01, 0x08, 0x0A
SAVE, QUIT, KILL = 0x0F, 0x18, 0x0B
ESC = 0x1B
F = "/home/f"


def edit(data, keys, name=F, limit=40_000_000):
    files = {} if data is None else {name: data}
    return asim.run("edit", [name], files, stdin=bytes(keys), limit=limit)


class Screen:
    """The console as edit drives it: 40 columns, 25 rows, ESC = r c (+32), ESC K, ESC R/r, FF."""

    def __init__(self):
        self.rows = [[" "] * 40 for _ in range(25)]
        self.r = self.c = 0

    def feed(self, data):
        i = 0
        while i < len(data):
            b = data[i]
            i += 1
            if b == ESC:
                op = data[i]
                i += 1
                if op == ord("="):
                    self.r, self.c = data[i] - 32, data[i + 1] - 32
                    i += 2
                elif op == ord("K"):
                    for x in range(self.c, 40):
                        self.rows[self.r][x] = " "
                # R and r (reverse video on/off) change no characters
            elif b == 12:
                self.__init__()
            elif 32 <= b < 127:
                self.rows[self.r][self.c] = chr(b)
                self.c += 1
            else:
                raise AssertionError("unexpected byte %02x in the output" % b)

    def line(self, n):
        return "".join(self.rows[n]).rstrip()


def screen_of(out):
    s = Screen()
    s.feed(out)
    return s


@unittest.skipIf(SKIP, SKIP)
class Refusal(unittest.TestCase):
    def test_a_file_over_the_buffer_is_refused_and_left_alone(self):
        big = (b"x" * 99 + b"\n") * (TEXTMAX // 100) + b"y" * 99 + b"\n"      # past TEXTMAX
        self.assertGreater(len(big), TEXTMAX)
        r = edit(big, [SAVE])                       # a save would cut it to TEXTMAX bytes
        self.assertEqual(r.files[F], big, "the file was changed: %d of %d bytes left" % (len(r.files[F]), len(big)))
        self.assertEqual(r.exit, 1)
        self.assertEqual(r.err, b"edit: file too big\n")

    def test_one_byte_over_is_refused(self):
        r = edit(b"a" * (TEXTMAX + 1), [SAVE])
        self.assertEqual((r.exit, r.err), (1, b"edit: file too big\n"))
        self.assertEqual(r.files[F], b"a" * (TEXTMAX + 1))

    def test_a_file_that_fills_the_buffer_exactly_is_opened_and_saved_whole(self):
        full = (b"x" * 99 + b"\n") * (TEXTMAX // 100) + b"z" * (TEXTMAX % 100)
        self.assertEqual(len(full), TEXTMAX)
        r = edit(full, [SAVE])
        self.assertEqual((r.exit, r.err), (0, b""))
        self.assertEqual(r.files[F], full)

    def test_a_file_just_under_the_buffer_edits(self):
        data = b"a" * (TEXTMAX - 1)
        r = edit(data, [ord("b"), SAVE])
        self.assertEqual(r.exit, 0)
        self.assertEqual(r.files[F], b"b" + data)

    def test_a_small_file_and_a_new_file_are_not_refused(self):
        self.assertEqual(edit(b"hello\n", []).exit, 0)
        self.assertEqual(edit(None, [ord("q"), SAVE]).files[F], b"q")


if __name__ == "__main__":
    unittest.main()
