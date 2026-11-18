"""Snapshot a drive's RAM with drvdump.s. Stock KERNAL host, clean bus (see drvdump.sh).
    SCRATCH=dir BREADBIN_ULTIMATE=host [DRIVE=8] python3 drvdump.py
Writes $SCRATCH/drvram_{idle,hash,u1}.bin (2048 bytes each: idle, '#' open, after U1) and drvram_rom.bin (16384)."""
import os, subprocess, sys, time
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from bench_basic import feed, u  # noqa: E402
work = os.environ.get("SCRATCH", ".")
obj, binf = os.path.join(work, "drvdump.o"), os.path.join(work, "drvdump.bin")
subprocess.run(["ca65", os.path.join(here, "drvdump.s"), "-o", obj], check=True)
subprocess.run(["ld65", "-t", "none", "-S", "0xC000", "-o", binf, obj], check=True)
code = open(binf, "rb").read()
u.resume(); u.reset(); time.sleep(8); u.pause()
u.writemem(0xC000, code)
u.writemem(0xC7E1, bytes([int(os.environ.get("DRIVE", "8"))]))
u.writemem(0xC7F0, bytes([0]))
u.resume()
feed("sys49152\n")
t0 = time.time()
while time.time() - t0 < 300:
    time.sleep(5)
    if u.readmem(0xC7F0, 1)[0]:
        break
else:
    print("TIMEOUT"); sys.exit(1)
for name, a, n in (("idle", 0x4000, 2048), ("hash", 0x4800, 2048), ("u1", 0x5000, 2048), ("rom", 0x5800, 16384)):
    open(os.path.join(work, f"drvram_{name}.bin"), "wb").write(u.readmem(a, n))
print("RESULT: dumped")
