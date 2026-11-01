#!/usr/bin/env python3
"""Compare src/kernel/keytab.inc with the key tables in a C64 KERNAL ROM.

    tools/check_keytab.py [kernal.bin]     (default: VICE's kernal-901227-03.bin)

The four tables sit at $EB81, $EBC2, $EC03 and $EC78 of the 8 KB ROM. Entries
for the modifier keys and RUN/STOP are $FF in ours by design and are skipped.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEAD = {15, 52, 58, 61, 63}
BASES = [0xEB81, 0xEBC2, 0xEC03, 0xEC78]


def load_ours():
    with open(os.path.join(ROOT, "src", "kernel", "keytab.inc")) as f:
        vals = [int(x, 16) for x in re.findall(r"\$([0-9a-f]{2})", re.sub(r";.*", "", f.read()))]
    return [vals[i * 64:(i + 1) * 64] for i in range(4)]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/vice/C64/kernal-901227-03.bin"
    rom = open(path, "rb").read()
    ours = load_ours()
    bad = 0
    for t, base in enumerate(BASES):
        for i in range(64):
            if i in DEAD:
                continue
            want = rom[base - 0xE000 + i]
            if ours[t][i] != want:
                bad += 1
                print(f"table {t} index {i}: ours ${ours[t][i]:02x}, ROM ${want:02x}")
    print("keytab matches the ROM" if not bad else f"{bad} differences")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
