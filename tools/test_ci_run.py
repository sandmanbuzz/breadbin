"""Tests for tools/ci/run.sh with a stub podman: no container starts. Checks which targets
take a VICE slot, the exclusive flag, the image rebuild on a stale label, words with spaces,
and that a signal removes the container. Skipped without flock(1)."""
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

STUB = r'''#!/bin/sh
# stub podman: log every call; "run" blocks while $STUB_RUN_SLEEP says so
echo "$@" >> "$STUB_LOG"
case "$1 $2" in
    "image exists") exit 0 ;;
    "image inspect") echo "$STUB_LABEL"; exit 0 ;;
    "build -q") exit 0 ;;
    "rm -f") echo "rm $3" >> "$STUB_LOG"; exit 0 ;;
esac
if [ "$1" = run ]; then
    for a in "$@"; do echo "ARG[$a]" >> "$STUB_LOG"; done
    [ -n "${STUB_RUN_SLEEP:-}" ] && sleep "$STUB_RUN_SLEEP"
fi
exit 0
'''


@unittest.skipUnless(shutil.which("flock"), "needs flock(1)")
class RunSh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        # a copy of the tools in a directory whose name has a space in it
        self.repo = os.path.join(t, "my repo")
        os.makedirs(os.path.join(self.repo, "tools"))
        shutil.copytree(os.path.join(HERE, "ci"), os.path.join(self.repo, "tools", "ci"))
        shutil.copy(os.path.join(HERE, "with-lock"), os.path.join(self.repo, "tools", "with-lock"))
        self.bin = os.path.join(t, "bin"); os.makedirs(self.bin)
        open(os.path.join(self.bin, "podman"), "w").write(STUB)
        os.chmod(os.path.join(self.bin, "podman"), 0o755)
        self.roms = os.path.join(t, "roms"); os.makedirs(os.path.join(self.roms, "C64"))
        open(os.path.join(self.roms, "C64", "kernal-901227-03.bin"), "w").close()
        self.log = os.path.join(t, "log"); open(self.log, "w").close()
        self.locks = os.path.join(t, "locks")
        self.env = dict(os.environ, PATH=self.bin + ":" + os.environ["PATH"], STUB_LOG=self.log,
                        BREADBIN_CI_ROMS=self.roms, BREADBIN_LOCKDIR=self.locks, STUB_LABEL="stale")
        for k in ("BREADBIN_LOCK_HELD", "BREADBIN_CI_EXCLUSIVE", "BREADBIN_VICE_ARGS", "BREADBIN_CI_JIFFY",
                  "BREADBIN_BROKER", "BREADBIN_CI_IMAGE", "BREADBIN_CI_MEM"):
            self.env.pop(k, None)
        self.run_sh = os.path.join(self.repo, "tools", "ci", "run.sh")
        self.label = self.current_label()

    def current_label(self):
        # what run.sh computes: the first 16 hex digits of the hash of Containerfile + entrypoint
        d = os.path.join(self.repo, "tools", "ci")
        out = subprocess.run(f'cat "{d}/Containerfile" "{d}/entrypoint.sh" | sha256sum | cut -c1-16',
                             shell=True, capture_output=True, text=True).stdout.strip()
        return out

    def run_ci(self, *args, **env):
        return subprocess.run([self.run_sh, *args], env=dict(self.env, STUB_LABEL=self.label, **env),
                              capture_output=True, text=True)

    def lock_files(self):
        return sorted(f for f in os.listdir(self.locks) if f.endswith(".lock")) if os.path.isdir(self.locks) else []

    def test_build_only_targets_take_no_slot_and_vice_targets_take_one(self):
        for target in ("size", "test-host", "all"):
            self.assertEqual(self.run_ci(target).returncode, 0)
        self.assertNotIn("vice.lock", self.lock_files())
        self.assertEqual(self.run_ci("test-smoke").returncode, 0)
        self.assertEqual(self.lock_files().count("vice.lock"), 1)
        self.assertNotIn("vice.1.lock", self.lock_files())      # one slot, not all

    def test_exclusive_only_when_set_to_1(self):
        self.run_ci("test-smoke", BREADBIN_CI_EXCLUSIVE="0")
        self.assertNotIn("vice.1.lock", self.lock_files())
        self.run_ci("test-smoke", BREADBIN_CI_EXCLUSIVE="1")
        self.assertIn("vice.1.lock", self.lock_files())

    def test_words_with_spaces_stay_whole(self):
        self.run_ci("test-only", "T=tests.a tests.b", BREADBIN_VICE_ARGS="-x -y")
        args = open(self.log).read().splitlines()
        self.assertIn(f"ARG[{self.repo}:/src:ro]", args)
        self.assertIn("ARG[T=tests.a tests.b]", args)
        self.assertIn("ARG[BREADBIN_VICE_ARGS=-x -y]", args)

    def test_image_rebuilt_only_when_the_label_is_stale(self):
        self.run_ci("size")
        self.assertEqual(open(self.log).read().count("build -q"), 0)        # label matches
        open(self.log, "w").close()
        r = subprocess.run([self.run_sh, "size"], env=dict(self.env, STUB_LABEL="old"), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(open(self.log).read().count("build -q"), 1)

    def test_sigterm_removes_the_container(self):
        p = subprocess.Popen([self.run_sh, "test-smoke"], env=dict(self.env, STUB_LABEL=self.label, STUB_RUN_SLEEP="20"),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):                                # wait until the stub 'run' is up
            if "ARG[test-smoke]" in open(self.log).read():
                break
            time.sleep(0.1)
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=15)
        self.assertEqual(p.returncode, 143)
        self.assertRegex(open(self.log).read(), r"rm breadbin-ci-run-\d+")


if __name__ == "__main__":
    unittest.main()
