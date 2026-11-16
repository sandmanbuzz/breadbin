#!/usr/bin/env python3
"""Shard list helper for tools/ci/sharded.sh (no VICE, no podman).

  shards.py list            print "name<TAB>specs" per shard
  shards.py check [N]       every VICE test is in exactly one shard, at most N shards (default 8);
                            prints "count <n>" and exits 0, or names the problems and exits 1
"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LIST = os.path.join(HERE, "shards.txt")


def shards(path=LIST):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, bar, specs = line.partition("|")
            if not bar or not name.strip() or not specs.split():
                raise ValueError("bad shard line (need name|specs): %r" % line)
            out.append((name.strip(), specs.split()))
    return out


def discovered():
    sys.path.insert(0, ROOT)
    ids = []
    tdir = os.path.join(ROOT, "tests")
    for fn in sorted(os.listdir(tdir)):
        if fn.startswith("test_") and fn.endswith(".py"):
            # by path, under the dotted name unittest gives them: another "tests" package
            # installed in site-packages would win a plain import
            name = "tests." + fn[:-3]
            spec = importlib.util.spec_from_file_location(name, os.path.join(tdir, fn))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
            stack = [suite]
            while stack:
                for t in stack.pop():
                    if isinstance(t, unittest.TestSuite):
                        stack.append(t)
                    else:
                        ids.append(t.id())
    return ids


def problems(shard_list, ids, nmax):
    bad = []
    names = [n for n, _ in shard_list]
    if len(set(names)) != len(names):
        bad.append("duplicate shard name")
    if len(shard_list) > nmax:
        bad.append(f"{len(shard_list)} shards > {nmax} slots")
    for i in ids:
        # one entry per matching SPEC, so a class and one of its methods in the same shard count twice
        hits = [n for n, specs in shard_list for s in specs if i == s or i.startswith(s + ".")]
        if not hits:
            bad.append(f"uncovered {i}")
        elif len(hits) > 1:
            bad.append(f"in {len(hits)} shards ({', '.join(hits)}): {i}")
    for n, specs in shard_list:
        for s in specs:
            if not any(i == s or i.startswith(s + ".") for i in ids):
                bad.append(f"{n}: spec matches no test: {s}")
    return bad


def per_shard_expected(shard_list, ids):
    """Return [(shard_name, expected_count), ...] for each shard.

    Each test ID is counted once per shard whose specs match it (a class spec
    and a method spec in the same shard both match the method, so it counts
    twice — matching the unittest loader's behaviour).
    """
    result = []
    for name, specs in shard_list:
        count = 0
        for i in ids:
            if any(i == s or i.startswith(s + ".") for s in specs):
                count += 1
        result.append((name, count))
    return result


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    try:
        sl = shards()
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    if cmd == "list":
        for n, specs in sl:
            print(f"{n}\t{' '.join(specs)}")
        return 0
    if cmd == "check":
        nmax = int(argv[2]) if len(argv) > 2 else 8
        ids = discovered()
        bad = problems(sl, ids, nmax)
        for b in bad:
            print(b, file=sys.stderr)
        print(f"count {len(ids)}")
        for name, count in per_shard_expected(sl, ids):
            print(f"per_shard {name} {count}")
        return 1 if bad else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
