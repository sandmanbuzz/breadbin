"""The shell's behaviour on the host: `sh` runs under py65 (tools/asim.py), no VICE.

The children are recorded, not run (asim.run(...).spawns): a test checks what sh asked the kernel for,
not what the child printed. Pipelines are refused (PIPE answers ENOSYS). The console is a tty only with
tty=True: then sh edits lines in raw mode, and the keys are bytes on stdin (the cursor keys are K_UP $10
and K_DOWN $0E, from include/breadbin.inc).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asim  # noqa: E402

ROOT = asim.ROOT
BUILT = os.path.exists(os.path.join(ROOT, "build", "root", "bin", "sh"))
SKIP = "py65 not installed" if asim.MPU is None else (None if BUILT else "not built (make)")

UP, DOWN, RET = b"\x10", b"\x0e", b"\n"


def sh(stdin, tty=False, **kw):
    return asim.run("sh", [], {}, stdin=stdin, tty=tty, **kw)


def argvs(r):
    return [s[1] for s in r.spawns]


@unittest.skipIf(SKIP, SKIP)
class Commands(unittest.TestCase):
    def test_command_is_spawned_with_its_argv(self):
        r = sh(b"echo hi there\n")
        self.assertEqual(r.exit, 0)
        self.assertEqual(r.spawns[0][0], "/bin/echo")
        self.assertEqual(argvs(r)[0], ["echo", "hi", "there"])

    def test_prompt_is_the_cwd_then_a_space_dollar(self):
        r = sh(b"")
        self.assertEqual(r.out, b"/ $ ")

    def test_empty_line_runs_nothing(self):
        r = sh(b"\n\n")
        self.assertEqual(r.spawns, [])

    def test_semicolon_runs_two_commands(self):
        r = sh(b"echo a ; echo b\n")
        self.assertEqual(argvs(r), [["echo", "a"], ["echo", "b"]])

    def test_quoted_words_keep_their_spaces(self):
        r = sh(b'echo "two words" x\n')
        self.assertEqual(argvs(r)[0], ["echo", "two words", "x"])

    def test_cd_changes_the_cwd_the_prompt_shows(self):
        r = sh(b"cd /x\npwd\n", dirs=("/x",))
        self.assertEqual(r.cwd, "/x")
        self.assertIn(b"/x $ ", r.out)

    def test_cd_to_a_missing_directory_stays_put(self):
        r = sh(b"cd /nope\n")
        self.assertEqual(r.cwd, "/")

    def test_redirect_out_opens_the_file_and_uses_its_fd(self):
        r = sh(b"echo hi > /o\n")
        self.assertIn("/o", r.files)
        self.assertNotEqual(r.spawns[0][3], 1)          # pout is the file, not the console

    def test_pipeline_is_refused_not_faked(self):
        r = sh(b"echo a | echo b\n")
        self.assertEqual(r.spawns, [])                    # PIPE failed: nothing is spawned


@unittest.skipIf(SKIP, SKIP)
class History(unittest.TestCase):
    def test_tty_echoes_the_typed_line_and_switches_raw_mode(self):
        r = sh(b"echo hi\n", tty=True)
        self.assertIn(b"/ $ echo hi\n", r.out)
        self.assertEqual(r.conmodes, [1, 0, 1, 0])     # raw on, off for the line; again for the prompt

    def test_up_recalls_the_last_line_and_return_runs_it(self):
        r = sh(b"echo one\n" + UP + RET, tty=True)
        self.assertEqual(argvs(r), [["echo", "one"], ["echo", "one"]])

    def test_up_up_down_walks_back_and_forward(self):
        r = sh(b"echo a\necho b\n" + UP + UP + DOWN + RET, tty=True)
        self.assertEqual(argvs(r), [["echo", "a"], ["echo", "b"], ["echo", "b"]])

    def test_up_stops_at_the_oldest_line(self):
        r = sh(b"echo one\n" + UP * 5 + RET, tty=True)
        self.assertEqual(argvs(r), [["echo", "one"], ["echo", "one"]])

    def test_empty_lines_are_not_remembered(self):
        r = sh(b"\n" + UP + RET, tty=True)
        self.assertEqual(r.spawns, [])

    def test_only_the_last_four_lines_are_kept(self):
        # five lines: "a" has been pushed out; five ups reach the oldest kept line, "b"
        r = sh(b"a\nb\nc\nd\ne\n" + UP * 5 + RET, tty=True)
        self.assertEqual(argvs(r)[-1], ["b"])


if __name__ == "__main__":
    unittest.main()
