#!/usr/bin/env python3
# /// block
# name = "bin-diff"
# summary = "Compare two binary files: sizes, differing byte count, first differences, FNV-1a hashes."
# effects = "read"
# example = ["--a", "$FIXTURES/a.bin", "--b", "$FIXTURES/b.bin"]
# matches = ["open\\(.*'rb'\\)\\.read\\(\\).*open\\(.*'rb'\\)", "0x811C9DC5"]
#
# [returns]
# keys = ["size_a", "size_b", "differing", "first", "fnv_a", "fnv_b", "identical"]
# doc = "differing counts offsets that differ in the common length; first is up to 8 {off, a, b} hex entries; fnv is 32-bit FNV-1a of the whole file"
#
# [params]
# a = { type = "path", required = true, help = "First file" }
# b = { type = "path", required = true, help = "Second file" }
#
# [provenance]
# created = "2026-11-13"
# source = "local"
#
# [stamp]
# verified = "a9e8f99b84e6"
# ///
"""Binary compare without dumping either file."""
import argparse
import json
import sys


def fnv1a(data):
    """32-bit FNV-1a."""
    h = 0x811C9DC5
    for byte in data:
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    args = ap.parse_args()
    try:
        with open(args.a, "rb") as fa, open(args.b, "rb") as fb:
            da, db = fa.read(), fb.read()
    except OSError as err:
        print(json.dumps({"error": str(err)}))
        sys.exit(1)
    diffs = [i for i in range(min(len(da), len(db))) if da[i] != db[i]]
    first = [{"off": f"{i:X}", "a": f"{da[i]:02X}", "b": f"{db[i]:02X}"} for i in diffs[:8]]
    print(json.dumps({
        "size_a": len(da), "size_b": len(db), "differing": len(diffs), "first": first,
        "fnv_a": fnv1a(da), "fnv_b": fnv1a(db), "identical": da == db,
    }))


if __name__ == "__main__":
    main()
