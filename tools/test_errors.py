"""perr's messages (src/lib/err.s built-ins + rootfs/etc/errors) against the strings the library
had before they moved out of the programs, and the order of the file (lookup cost)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The messages before the change (src/lib/err.s, errtab), by name.
OLD = {
    "EPERM": "operation not permitted", "ENOENT": "no such file or directory",
    "ESRCH": "no such process", "EIO": "i/o error", "E2BIG": "argument list too long",
    "ENOEXEC": "exec format error", "EBADF": "bad file descriptor", "ECHILD": "no child processes",
    "EAGAIN": "too many processes", "ENOMEM": "out of memory", "EBUSY": "device busy",
    "EEXIST": "file exists", "ENODEV": "no such device or no disk", "EXDEV": "cross-device link",
    "ENOTDIR": "not a directory", "EISDIR": "is a directory", "EINVAL": "invalid argument",
    "EMFILE": "too many open files", "EFBIG": "file too large", "ENOSPC": "no space left on device",
    "EPIPE": "broken pipe", "ENAMETOOLONG": "file name too long", "ENOTEMPTY": "directory not empty",
}
BUILTIN = {"EIO", "ENOENT", "ENODEV"}          # print without the disk


def errnos():
    out = {}
    with open(os.path.join(ROOT, "include", "breadbin.inc")) as f:
        for line in f:
            m = re.match(r"(E[A-Z0-9]+)\s*=\s*(\d+)", line)
            if m:
                out[m.group(1)] = int(m.group(2))
    return out


def builtins():
    src = open(os.path.join(ROOT, "src", "lib", "err.s")).read()
    names = re.findall(r"\.byte (E[A-Z0-9]+)\n\s*\.word (\w+)", src)
    text = dict(re.findall(r'^(e_\w+):\s*\.byte "([^"]*)", 0', src, re.M))
    return {n: text[lbl] for n, lbl in names}


def file_lines():
    with open(os.path.join(ROOT, "rootfs", "etc", "errors")) as f:
        return [(int(a), b) for a, b in (ln.rstrip("\n").split(" ", 1) for ln in f if ln.strip())]


class TestErrors(unittest.TestCase):
    def test_every_message_is_the_one_users_saw_before(self):
        num = errnos()
        by_num = {num[n]: n for n in OLD}
        got = dict(builtins())
        for n, text in file_lines():
            self.assertNotIn(by_num[n], got, "%s is both built in and in the file" % by_num[n])
            got[by_num[n]] = text
        self.assertEqual(got, OLD)

    def test_the_built_in_set_is_the_three_that_must_work_without_a_disk(self):
        self.assertEqual(set(builtins()), BUILTIN)

    def test_the_file_is_well_formed_and_ordered_by_how_common_the_errors_are(self):
        data = open(os.path.join(ROOT, "rootfs", "etc", "errors"), "rb").read()
        self.assertTrue(data.endswith(b"\n"))
        for n, text in file_lines():
            self.assertTrue(0 < n < 100 and text == text.strip() and text)
        ends, pos = {}, 0
        num = errnos()
        for ln in data.split(b"\n")[:-1]:
            pos += len(ln) + 1
            ends[int(ln.split(b" ", 1)[0])] = pos
        # the lookup reads one byte per syscall (about 1,900 cycles each, measured in the py65 sim):
        # the commonest file/dir errors must be found within the first 100 bytes (~0.2 s)
        for name in ("EEXIST", "EISDIR", "ENOTDIR", "EINVAL", "ENOTEMPTY"):
            self.assertLessEqual(ends[num[name]], 100, name)
        self.assertLessEqual(len(data), 512)           # two blocks


if __name__ == "__main__":
    unittest.main()
