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
    return asim.run("sh", [], kw.pop("files", {}), stdin=stdin, tty=tty, **kw)


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

    def test_full_line_comment_is_ignored(self):
        r = sh(b"  # just a comment\necho after\n")
        self.assertEqual(argvs(r), [["echo", "after"]])

    def test_trailing_comment_discards_the_rest_of_the_line(self):
        r = sh(b"echo before # ignored; echo after\n")
        self.assertEqual(argvs(r), [["echo", "before"]])

    def test_comment_after_command_separator_is_ignored(self):
        r = sh(b"echo before; # ignored\n")
        self.assertEqual(argvs(r), [["echo", "before"]])

    def test_hash_inside_unquoted_word_is_literal(self):
        r = sh(b"echo foo#bar\n")
        self.assertEqual(argvs(r), [["echo", "foo#bar"]])

    def test_hash_inside_quoted_words_is_literal(self):
        r = sh(b'echo "two # words" \'three # words\'\n')
        self.assertEqual(argvs(r), [["echo", "two # words", "three # words"]])

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

    def test_and_short_circuits_on_failure(self):
        # Host sim: all spawns succeed (exit 0), so && always runs both
        r = sh(b"echo a && echo b\n")
        self.assertEqual(argvs(r), [["echo", "a"], ["echo", "b"]])

    def test_or_short_circuits_on_success(self):
        # Host sim: last_status is always 0, so || never fires
        r = sh(b"echo ok || echo b\n")
        self.assertEqual(argvs(r), [["echo", "ok"]])

    def test_and_chaining_runs_both(self):
        r = sh(b"echo a && echo b && echo c\n")
        self.assertEqual(argvs(r), [["echo", "a"], ["echo", "b"], ["echo", "c"]])

    def test_or_chaining_fallback(self):
        # Host sim: last_status is always 0, so || never fires
        r = sh(b"echo a || echo b && echo c\n")
        self.assertEqual(argvs(r), [["echo", "a"], ["echo", "c"]])

    def test_dollar_question_after_success(self):
        r = sh(b"echo ok\necho $?\n")
        self.assertEqual(argvs(r), [["echo", "ok"], ["echo", "0"]])

    def test_dollar_question_after_fail(self):
        # Host sim: last_status is always 0
        r = sh(b"echo ok\necho $?\n")
        self.assertEqual(argvs(r), [["echo", "ok"], ["echo", "0"]])


def label(name):
    """Address of a sh variable in the host image (build/p/sh.lbl holds offsets from the load address)."""
    with open(os.path.join(ROOT, "build", "p", "sh.lbl")) as f:
        for ln in f:
            w = ln.split()
            if len(w) == 3 and w[2] == "." + name:
                return (asim.BASE_PAGE << 8) + int(w[1], 16)
    raise KeyError(name)


def dirent(name):
    return b"\x02" + name.encode().ljust(15, b"\0")


@unittest.skipIf(SKIP, SKIP)
class Glob(unittest.TestCase):
    def test_longest_directory_prefix_does_not_overflow_the_glob_buffer(self):
        # g_store used to guard only gpos < 192, then copied the whole prefix plus the name. A prefix
        # longer than 47 characters is now literal, so the longest one that globs (47) is used, with
        # more matches than gbuf holds: those that fit are kept, the rest are dropped.
        prefix = "/" + "a" * 45 + "/"
        self.assertEqual(len(prefix), 47)
        names = [c * 14 for c in "bcdefg"]
        files = {prefix[:-1]: b"".join(dirent(n) for n in names)}
        r = sh(("echo " + prefix + "*\n").encode(), files=files)
        gbuf = label("gbuf")
        after = bytes(r.mem[gbuf + 257:gbuf + 256 + 64])    # tpos (first) follows the typed line's length
        control = bytes(sh(b"echo x\n").mem[gbuf + 257:gbuf + 256 + 64])    # the variables after gbuf at rest
        self.assertEqual(after, control, "glob wrote past the end of gbuf")
        got = argvs(r)[0][1:]
        self.assertEqual(got, [prefix + n for n in names[:len(got)]])
        self.assertTrue(3 <= len(got) < len(names), got)

    def glob_in(self, plen):
        """`echo <prefix>*` where the prefix is plen characters (including its '/') and its directory exists under the full name."""
        prefix = "/" + "a" * (plen - 2) + "/"
        self.assertEqual(len(prefix), plen)
        names = ["x1", "x2"]
        files = {prefix[:-1]: b"".join(dirent(n) for n in names)}
        files.setdefault(prefix[:46], dirent("decoy"))     # what a prefix cut at 46 characters would open
        return prefix, names, argvs(sh(("echo " + prefix + "*\n").encode(), files=files))

    def test_prefix_of_46_characters_still_globs(self):
        prefix, names, got = self.glob_in(46)
        self.assertEqual(got, [["echo", prefix + names[0], prefix + names[1]]])

    def test_prefix_of_47_characters_still_globs(self):
        # the 47th character is the '/', which is dropped: the directory is the full 46 characters
        prefix, names, got = self.glob_in(47)
        self.assertEqual(got, [["echo", prefix + names[0], prefix + names[1]]])

    def test_prefix_too_long_for_the_directory_buffer_stays_literal(self):
        # g_dir holds 47 characters: a longer prefix was cut short and a truncated directory was read,
        # while every name still got the full prefix.
        for plen in (48, 60, 121):
            prefix, names, got = self.glob_in(plen)
            self.assertEqual(got, [["echo", prefix + "*"]], plen)


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
