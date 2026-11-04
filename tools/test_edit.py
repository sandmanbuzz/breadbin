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

    def test_refusal_never_sets_console_mode_1(self):
        r = edit(b"a" * (TEXTMAX + 1), [])
        self.assertEqual(r.exit, 1)
        self.assertTrue(not r.conmodes or r.conmodes[-1] == 0, r.conmodes)
        self.assertNotIn(1, r.conmodes)

    def test_a_normal_quit_leaves_console_mode_0(self):
        r = edit(b"hello\n", [QUIT])
        self.assertEqual(r.exit, 0)
        self.assertEqual(r.conmodes, [1, 0])

    def test_a_full_buffer_says_so_and_the_save_is_unchanged(self):
        full = (b"x" * 99 + b"\n") * (TEXTMAX // 100) + b"z" * (TEXTMAX % 100)
        self.assertEqual(len(full), TEXTMAX)
        r = edit(full, [ord("q")])
        self.assertIn(" buffer full", screen_of(r.out[:r.marks[1]]).line(24))
        r = edit(full, [ord("q"), SAVE])
        self.assertEqual(r.files[F], full)


@unittest.skipIf(SKIP, SKIP)
class Redraw(unittest.TestCase):
    LINES = b"one\ntwo\nthree\nfour\n"

    def per_key(self, data, keys):
        """The bytes written after each key (marks[i+1] - marks[i]); keys end with a QUIT."""
        r = edit(data, list(keys) + [QUIT])
        out, m = r.out, r.marks
        return r, [out[m[i]:m[i + 1]] for i in range(len(keys))]

    def test_a_cursor_key_only_moves_the_cursor(self):
        r, outs = self.per_key(self.LINES, [RIGHT, DOWN, LEFT, UP, HOME, RIGHT, DOWN, DOWN, UP])
        for i, o in enumerate(outs):
            self.assertEqual(len(o), 4, "key %d wrote %d bytes, more than the cursor move: %r" % (i, len(o), o[:40]))
            self.assertEqual(o[:2], bytes([ESC, ord("=")]))

    def test_a_cursor_key_leaves_what_is_on_the_screen(self):
        # as upstream's test: put marks on the screen (row 10, and the status line's end); cursor
        # keys must not wipe them, typing a character redraws the text rows and wipes the one on row 10
        r, outs = self.per_key(self.LINES, [RIGHT, DOWN, ord("A")])
        s = screen_of(r.out[:r.marks[0]])
        s.rows[10][0] = "*"
        s.rows[24][39] = "*"
        s.feed(outs[0] + outs[1])
        self.assertEqual((s.rows[10][0], s.rows[24][39]), ("*", "*"))
        s.feed(outs[2])
        self.assertEqual(s.rows[10][0], " ")
        self.assertEqual(s.rows[24][39], " ")                          # the first change redraws the status line

    def test_typing_redraws_the_text(self):
        r, outs = self.per_key(self.LINES, [ord("A")])
        self.assertGreater(len(outs[0]), 24 * 4)
        self.assertEqual(screen_of(r.out[:r.marks[1]]).line(0), "Aone")

    def test_the_status_line_is_drawn_when_it_changes_only(self):
        r, outs = self.per_key(self.LINES, [ord("A"), ord("B"), RIGHT, ord("C")])
        has_status = [bytes([ESC, ord("R")]) in o for o in outs]
        self.assertEqual(has_status, [True, False, False, False])     # first edit: " *" appears
        r, outs = self.per_key(self.LINES, [ord("A"), SAVE, RIGHT, ord("B")])
        has_status = [bytes([ESC, ord("R")]) in o for o in outs]
        self.assertEqual(has_status, [True, True, True, True])        # " *", " saved", the message cleared, " *"
        r, outs = self.per_key(self.LINES, [ord("A"), SAVE, RIGHT, RIGHT, LEFT])
        has_status = [bytes([ESC, ord("R")]) in o for o in outs]
        self.assertEqual(has_status, [True, True, True, False, False])
        r, outs = self.per_key(self.LINES, [RIGHT, DEL, DEL])
        self.assertEqual([bytes([ESC, ord("R")]) in o for o in outs], [False, True, False])

    def test_the_status_line_follows_dirty_and_messages(self):
        r = edit(self.LINES, [ord("A"), QUIT])      # first ^X: warning, second (end of input): quits
        s = Screen()
        s.feed(r.out[:r.marks[2]])
        self.assertIn("unsaved changes", s.line(24))
        r = edit(self.LINES, [ord("A")])
        s = screen_of(r.out[:r.marks[1]])
        self.assertTrue(s.line(24).startswith(" edit: " + F), s.line(24))
        self.assertIn("*", s.line(24))
        r = edit(self.LINES, [ord("A"), SAVE, ord("B"), DEL])
        marks = r.marks
        self.assertIn("saved", screen_of(r.out[:marks[2]]).line(24))
        self.assertNotIn("saved", screen_of(r.out[:marks[3]]).line(24))   # typing clears the message

    def test_scrolling_redraws_the_text(self):
        many = b"".join(b"line%02d\n" % i for i in range(40))
        r, outs = self.per_key(many, [DOWN] * 30)
        big = [len(o) > 24 * 4 for o in outs]
        self.assertEqual(big[:23], [False] * 23)                      # the cursor goes down rows 1..23
        self.assertTrue(big[23] and big[24])                          # past row 23 the view scrolls
        s = screen_of(r.out[:r.marks[30]])
        self.assertEqual(s.line(0), "line07")
        self.assertEqual(s.line(23), "line30")
        # and back up
        r, outs = self.per_key(many, [DOWN] * 30 + [UP] * 23)
        s = screen_of(r.out[:r.marks[53]])
        self.assertEqual((s.line(0), s.line(23)), ("line07", "line30"))   # the cursor is on the top row: no scroll yet
        r, outs = self.per_key(many, [DOWN] * 30 + [UP] * 24)
        s = screen_of(r.out[:r.marks[54]])
        self.assertEqual((s.line(0), s.line(23)), ("line06", "line29"))

    def test_the_screen_matches_the_text_after_random_edits(self):
        rng = random.Random(1983)
        alphabet = [ord(c) for c in "abcxyz "]
        for trial in range(30):
            start = rng.choice([b"", b"one\ntwo\nthree", b"hello world\n\nlast line\n", b"x" * 45 + b"\nshort\n"])
            keys = []
            rets = 0
            for _ in range(rng.randint(5, 40)):
                k = rng.choice(["a", "a", "a", "ret", "del", "del", "up", "down", "left", "right", "home", "kill"])
                if k == "a":
                    keys.append(rng.choice(alphabet))
                elif k == "ret":
                    if rets < 6:
                        keys.append(RET)
                        rets += 1
                else:
                    keys.append({"del": DEL, "up": UP, "down": DOWN, "left": LEFT, "right": RIGHT,
                                 "home": HOME, "kill": KILL}[k])
            r = edit(start, keys + [SAVE])
            saved = r.files[F]
            lines = saved.decode("latin-1").split("\n")
            if saved.endswith(b"\n"):
                lines.pop()
            s = Screen()
            s.feed(r.out[:r.marks[len(keys) + 1]])     # up to the save (quitting clears the screen)
            if len(lines) > 24:
                continue                                # the view may have scrolled: the model is for one page
            for n in range(24):
                want = (lines[n][:39] if n < len(lines) else "").rstrip()
                self.assertEqual(s.line(n), want, "trial %d, row %d: start %r keys %s" % (
                    trial, n, start, bytes(keys).hex()))

    def test_the_screen_is_a_window_of_the_text_after_random_edits_in_a_long_file(self):
        # past one page the view scrolls: the rows must still be 24 consecutive lines of the saved file
        rng = random.Random(64)
        start = b"".join(b"line %02d %s\n" % (i, b"." * (i % 7 * 9)) for i in range(40))
        for trial in range(12):
            keys = []
            for _ in range(rng.randint(10, 60)):
                keys.append(rng.choice([DOWN] * 6 + [UP] * 4 + [KILL, RET, DEL, RIGHT, LEFT, HOME,
                                                               ord("a"), ord("b")]))
            r = edit(start, keys + [SAVE])
            lines = r.files[F].decode("latin-1").split("\n")
            if r.files[F].endswith(b"\n"):
                lines.pop()
            s = Screen()
            s.feed(r.out[:r.marks[len(keys) + 1]])
            rows = [s.line(n) for n in range(24)]
            want = [[l[:39].rstrip() for l in (lines[n:n + 24] + [""] * 24)[:24]] for n in range(len(lines))]
            self.assertIn(rows, want, "trial %d: keys %s\nscreen:\n%s" % (trial, bytes(keys).hex(), "\n".join(rows)))


@unittest.skipIf(SKIP, SKIP)
class Kill(unittest.TestCase):
    def test_line_kill(self):
        r = edit(b"one\ntwo\nthree", [DOWN, KILL, SAVE])
        self.assertEqual(r.files[F], b"one\nthree")
        r = edit(b"one\ntwo\nthree", [DOWN, KILL, KILL, SAVE])        # the last line, no newline
        self.assertEqual(r.files[F], b"one\n")
        r = edit(b"one\ntwo\nthree", [DOWN, KILL, KILL, KILL, SAVE])  # an empty last line: nothing
        self.assertEqual(r.files[F], b"one\n")
        self.assertEqual(r.exit, 0)

    def test_kill_each_line_of_a_file(self):
        data = b"a\nbb\nccc\n\ndddd\ne"
        for n in range(6):
            lines = data.split(b"\n")
            lines = [l + b"\n" for l in lines[:-1]] + [lines[-1]]
            r = edit(data, [DOWN] * n + [KILL, SAVE])
            self.assertEqual(r.files[F], b"".join(lines[:n] + lines[n + 1:]), "line %d" % n)

    def test_kill_only_line_and_empty_file(self):
        self.assertEqual(edit(b"just one", [KILL, SAVE]).files[F], b"")
        self.assertEqual(edit(b"", [KILL, SAVE]).files[F], b"")
        self.assertEqual(edit(b"\n", [KILL, SAVE]).files[F], b"")
        self.assertEqual(edit(b"\n\n", [KILL, SAVE]).files[F], b"\n")

    def test_kill_in_the_middle_of_a_line_takes_the_whole_line(self):
        r = edit(b"abc\ndef\nghi\n", [DOWN, RIGHT, RIGHT, KILL, SAVE])
        self.assertEqual(r.files[F], b"abc\nghi\n")

    def test_kill_across_a_page_boundary_of_the_buffer(self):
        # text longer than 256 bytes: the move down crosses a page of text
        lines = [(b"%03d" % i) * 30 + b"\n" for i in range(8)]       # 8 x 91 bytes
        r = edit(b"".join(lines), [DOWN, DOWN, KILL, SAVE])
        self.assertEqual(r.files[F], b"".join(lines[:2] + lines[3:]))

    def test_kill_moves_the_text_once(self):
        # 20 lines of 50 bytes: killing the first one moves the 950 bytes after it. Measured: 76,000 steps
        # for the whole run when the tail moves once, 606,000 when it moved once per character.
        data = (b"x" * 49 + b"\n") * 20
        r = edit(data, [KILL, SAVE])
        self.assertEqual(r.files[F], data[50:])
        self.assertLess(r.steps, 200_000, "steps: %d" % r.steps)


if __name__ == "__main__":
    unittest.main()
