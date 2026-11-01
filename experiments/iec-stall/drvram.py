"""Run drvram.s against a drive: pattern-test its RAM ($0300-$06FF) through M-W / M-R.
Needs the STOCK KERNAL host (Kernal ROM = "", then machine:reboot), a clean bus, the drive on device 8.

    SCRATCH=dir BREADBIN_ULTIMATE=host [PASSES=25] [DRIVE=8] python3 drvram.py
One pass is eight patterns over 1 KB and takes about 25 s. Exit status 0 only for zero mismatches.
"""
import os
import subprocess
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from bench_basic import feed, u  # noqa: E402

work = os.environ.get("SCRATCH", ".")
obj, binf = os.path.join(work, "drvram.o"), os.path.join(work, "drvram.bin")
subprocess.run(["ca65", os.path.join(here, "drvram.s"), "-o", obj], check=True)
subprocess.run(["ld65", "-t", "none", "-S", "0xC000", "-o", binf, obj], check=True)
code = open(binf, "rb").read()
passes = int(os.environ.get("PASSES", "25"))
drive = int(os.environ.get("DRIVE", "8"))
print(f"{len(code)} bytes of code; {passes} passes on device {drive}", flush=True)
u.resume()
u.reset()
time.sleep(8)
u.pause()
u.writemem(0xC000, code)
u.writemem(0xC7E0, bytes([passes & 255, drive]))
u.writemem(0xC7F0, bytes(9))
u.resume()
feed("sys49152\n")
t0 = time.time()
last, lastt = -1, time.time()
ok = False
while time.time() - t0 < 3600:
    time.sleep(30)
    p = u.readmem(0xC7F0, 9)
    n, bad = p[1] | p[2] << 8, p[3] | p[4] << 8
    print(f"{time.time() - t0:5.0f}s  {n} of {passes} passes, mismatching bytes {bad}", flush=True)
    if p[0]:
        ok = bad == 0
        if bad:
            print(f"first mismatch at drive address ${p[5] | p[6] << 8:04X}: wrote ${p[7]:02X}, read ${p[8]:02X}")
        break
    if n == last and time.time() - lastt > 180:
        print("STALLED after", n, "passes")
        break
    if n != last:
        last, lastt = n, time.time()
print("RESULT:", f"{passes} passes, no mismatch" if ok else "NOT clean")
sys.exit(0 if ok else 1)
