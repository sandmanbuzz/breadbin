"""Hardware run of /lib/km/d81 against a PHYSICAL 1581 (no test_ prefix: not in the shards, needs the bench).

    BREADBIN_TARGET=ultimate BREADBIN_ULTIMATE_BUS=9 BREADBIN_D81_BUS=10 \\
        tools/with-lock -r ultimate -- python3 tests/d81_hw.py [--format]

Boots tests' image from the Ultimate's drive A (bus 9) and talks to the 1581 on BREADBIN_D81_BUS. Stage 1
(always) is read-only on the bus: the module loads, and a mount of the drive reports what it finds. Stage 2
(--format) FORMATS THE DISK IN THE 1581 (the owner's sacrificial media), then writes a file, remounts and reads
it back. Prints one JSON object (the screens of each step, abbreviated) and exits 0 when every check held.
"""
import argparse
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import make_target  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", action="store_true", help="format the disk in the 1581 and round-trip a file")
    ap.add_argument("--bus", type=int, default=int(os.environ.get("BREADBIN_D81_BUS", "10")))
    ap.add_argument("--format-timeout", type=int, default=3600)
    a = ap.parse_args()
    steps, ok = [], True

    def step(name, out, good=True):
        nonlocal ok
        ok = ok and good
        steps.append({"step": name, "ok": good, "out": out[-300:] if isinstance(out, str) else out})

    with make_target(IMAGE) as v:
        v.wait_shell()
        mnt = f"mount {a.bus} /mnt"
        r = v.run(mnt)
        step("mount before the module (expect: refused)", r, r != "")
        r = v.run("mod load /lib/km/d81")
        step("mod load d81", r, r == "")
        r = v.run("mod ls")
        step("mod ls", r, "(d81)" in r)
        r = v.run(mnt)
        step("mount with the module (blank or foreign media: the answer is data)", r, True)
        mounted = r == ""
        if a.format:
            if mounted:
                v.run("umount /mnt")
            v.type(f"clear\nformat {a.bus} c64fs vol\n")
            v.wait_for("(y/n)")
            v.type("y\n")
            s = v.wait_for("done", timeout=a.format_timeout)
            step("format", s, True)
            r = v.run(mnt)
            step("mount after format", r, r == "")
            v.run("mkdir /mnt/d")
            v.run("cp /etc/help /mnt/d/help")
            want = [v.run("wc /etc/help"), v.run("hexdump /etc/help | head -n 13"), v.run("hexdump /etc/help | tail -n 13")]
            got1 = [v.run("wc /mnt/d/help"), v.run("hexdump /mnt/d/help | head -n 13"), v.run("hexdump /mnt/d/help | tail -n 13")]
            step("read back before umount", got1[0], [w.replace("/etc/", "/mnt/d/") for w in want[:1]] == got1[:1] and want[1:] == got1[1:])
            r = v.run("umount /mnt")
            step("umount", r, r == "")
            r = v.run(mnt)
            step("remount", r, r == "")
            got2 = [v.run("wc /mnt/d/help"), v.run("hexdump /mnt/d/help | head -n 13"), v.run("hexdump /mnt/d/help | tail -n 13")]
            step("read back after remount", got2[0], got2 == got1)
            v.run("umount /mnt")
    print(json.dumps({"ok": ok, "steps": steps}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
