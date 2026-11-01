"""Assemble mcscan.s, load it at $C000 by DMA on the stock KERNAL's BASIC, SYS it, and watch the progress.
Needs the STOCK KERNAL as the host (Kernal ROM = "", then machine:reboot) and the drive on device 8.

    SCRATCH=dir BREADBIN_ULTIMATE=host [BURN=n] python3 mcscan.py   # 512 blocks; STALLED if no progress for 90 s
"""
import os
import subprocess
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from bench_basic import feed, u  # noqa: E402

work = os.environ.get("SCRATCH", ".")
obj, binf = os.path.join(work, "mcscan.o"), os.path.join(work, "mcscan.bin")
subprocess.run(["ca65", os.path.join(here, "mcscan.s"), "-o", obj], check=True)
subprocess.run(["ld65", "-t", "none", "-S", "0xC000", "-o", binf, obj], check=True)
code = open(binf, "rb").read()
print(f"{len(code)} bytes of code", flush=True)
u.resume()
u.reset()
time.sleep(6)
u.pause()
u.writemem(0xC000, code)
burn = int(os.environ.get("BURN", "0"))      # IRQ handler delay in ~1.3 ms units; 0 = the stock environment
u.writemem(0xC7E0, bytes([burn]))
cr = int(os.environ.get("CR", "1"))                    # 0 = commands end with EOI only, like the kernel
u.writemem(0xC7E5, bytes([cr]))
print("commands end with:", "CR + EOI" if cr else "EOI only", flush=True)
u.writemem(0xC7F0, bytes(3))
print("slow IRQ handler:", burn * 1.3 if burn else "off", "ms per tick", flush=True)
u.resume()
feed("sys49152\n")
t0 = time.time()
last, lastt = -1, time.time()
while time.time() - t0 < 900:
    time.sleep(15)
    p = u.readmem(0xC7F0, 3)
    n = p[1] | p[2] << 8
    print(f"{time.time() - t0:5.0f}s  {n} of 512 blocks", flush=True)
    if p[0]:
        print("FINISHED all 512 blocks, no stall")
        break
    if n == last and time.time() - lastt > 90:
        print("STALLED at block", n)
        break
    if n != last:
        last, lastt = n, time.time()
