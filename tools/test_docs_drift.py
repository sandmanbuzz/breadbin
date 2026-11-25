"""Guards against the documents drifting from the tree: figures that live in code are checked
against it, and figures that would only go stale are kept out of the live documents.

Not a proofreader: it checks the few claims that were wrong before (the pool size, the module
name ids, files named in the live documents, test counts in the README)."""
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = ["README.md", "CLAUDE.md", "docs/README.md", "docs/wip.md", "docs/testing.md", "docs/process.md", "docs/roadmap.md",
        "docs/filesystem.md", "docs/ci.md"]


def read(p):
    with open(os.path.join(ROOT, p)) as f:
        return f.read()


def tracked():
    """git's file list; where git is missing or the tree is not a checkout it can read (the CI
    container mounts a worktree without its git directory), the files on disk."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
        if not out.returncode:
            return set(out.stdout.split())
    except FileNotFoundError:
        pass
    found = set()
    for top, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "build", "fleet", ".claude")]
        found.update(os.path.relpath(os.path.join(top, n), ROOT) for n in names)
    return found


class Drift(unittest.TestCase):
    def test_pool_size_claims_match_kstart(self):
        kstart = int(re.search(r"^KSTART\s*=\s*\$([0-9a-fA-F]+)", read("src/kernel/k.inc"), re.M).group(1), 16)
        kram = int(re.search(r"KRAM:\s*start\s*=\s*\$([0-9a-fA-F]+)", read("src/kernel.cfg")).group(1), 16)
        self.assertEqual(kstart, kram, "KSTART (k.inc) and KRAM (kernel.cfg) must move together")
        pages = (kstart - 0x800) // 256
        seen = 0
        for doc in LIVE + ["docs/why-this-fork.md"]:
            for m in re.finditer(r"(\d+) pages[^.;]{0,30}?([\d,]{6}) bytes", read(doc), re.I):
                seen += 1
                self.assertEqual((int(m.group(1)), int(m.group(2).replace(",", ""))), (pages, pages * 256),
                                 f"{doc}: pool claim {m.group(0)!r}")
        self.assertGreaterEqual(seen, 3, "no document states the pool size any more: update this check")

    def test_module_name_ids_match_the_mod_command(self):
        names = re.search(r"^names:\s*\.word (.*)$", read("src/bin/mod.s"), re.M).group(1).replace(" ", "").split(",")
        for fn in sorted(os.listdir(os.path.join(ROOT, "src", "mod"))):
            if not fn.endswith(".s"):
                continue
            m = re.search(r"\.byte \$([0-9a-fA-F])[0-9a-fA-F]\s*;\s*class", read(f"src/mod/{fn}"))
            if not m:
                continue
            ident = int(m.group(1), 16)
            want = "n_" + fn[:-2] if ident else None
            if ident:
                self.assertLess(ident, len(names), f"{fn}: name id {ident} is past the names table")
                self.assertEqual(names[ident], want, f"{fn}: name id {ident} is {names[ident]} in mod.s")
        cmp_ = int(re.search(r"cmp #(\d+)\s*\n\s*bcc @nm", read("src/bin/mod.s")).group(1))
        self.assertEqual(cmp_, len(names), "mod.s: the id bound (cmp #N) is not the table length")

    def test_files_named_in_live_documents_exist(self):
        files = tracked()
        base = {os.path.basename(t) for t in files}
        skip = re.compile(r"^build/|\.km$|NAME\.s$")      # build output, modules, a placeholder
        for doc in LIVE:
            for m in re.finditer(r"`([A-Za-z0-9_./-]+\.(?:s|py|md|sh|cfg|inc|txt|tsv|c))`", read(doc)):
                p = m.group(1)
                if skip.search(p) or p in files or os.path.basename(p) in base:
                    continue
                self.fail(f"{doc} names {p}, which is not in the tree")

    def test_readme_quotes_no_test_counts(self):
        """Counts go stale at once; the commands print them."""
        self.assertIsNone(re.search(r"\b\d+ tests\b", read("README.md")))


if __name__ == "__main__":
    unittest.main()
