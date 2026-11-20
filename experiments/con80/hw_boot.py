#!/usr/bin/env python3
"""Boot build/ with /etc/con80 on the Ultimate and leave it running for eyes-on checks.
    BREADBIN_ULTIMATE=host BREADBIN_ULTIMATE_BUS=9 tools/with-lock -r ultimate -- python3 experiments/con80/hw_boot.py [--wait S]
Prints one JSON line: whether the VIC reached the 80-column bitmap ($D011/$D018). Only 1-byte reads."""
import argparse, json, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
from tests.test_con80 import image_with_marker
from ultimatetest import UltimateTarget

ap = argparse.ArgumentParser()
ap.add_argument("--wait", type=float, default=150)
a = ap.parse_args()
with tempfile.TemporaryDirectory() as tmp:
    v = UltimateTarget(image_with_marker(tmp))
    t0, got = time.time(), None
    while time.time() - t0 < a.wait:
        time.sleep(2)
        if v.bus_idle():
            d11, d18 = v._read1(0xd011), v._read1(0xd018)
            if d11 == 0x3b:
                got = (d11, d18); break
    print(json.dumps({"bitmap": got is not None, "d011": got and hex(got[0]), "d018": got and hex(got[1]),
                      "secs": round(time.time() - t0)}))
    sys.exit(0 if got else 1)
