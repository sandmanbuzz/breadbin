"""Drive the stock/JiffyDOS BASIC on the Ultimate without key injection: text goes into the
KERNAL keyboard buffer by DMA (what `UltimateTarget.type` does for Breadbin), the screen is
read back from $0400. Import `u`, `feed`, `screen`. Needs BREADBIN_ULTIMATE=host.

Probing the bus from BASIC: `OPEN n,dev,15` with no filename sends NOTHING on the bus, so it
cannot tell whether a device is there. Use a filename (`OPEN 1,dev,0,"$"`) or read the channel.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
from ultimate import Ultimate  # noqa: E402

u = Ultimate(os.environ["BREADBIN_ULTIMATE"])


def feed(text):
    """ASCII to PETSCII into the key buffer, 8 keys at a time, paused while it is written."""
    codes = [0x0D if c == "\n" else (ord(c.upper()) if c.isalpha() else ord(c)) for c in text]
    for i in range(0, len(codes), 8):
        chunk = bytes(codes[i:i + 8])
        while True:
            u.pause()
            if u.readmem(0xC6, 1)[0] == 0:
                u.writemem(0x0277, chunk)
                u.writemem(0xC6, bytes([len(chunk)]))
                u.resume()
                break
            u.resume()
            time.sleep(0.05)


def screen():
    d = u.readmem(0x0400, 1000)
    rows = ["".join(chr(c + 64) if 1 <= c <= 26 else chr(c) if 32 <= c < 64 else " " if c == 32
                    else "." for c in d[r * 40:(r + 1) * 40]).rstrip().lower() for r in range(25)]
    return "\n".join(l for l in rows if l)
