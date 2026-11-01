"""Boot the stage-2 kernel until it stalls, then run atnprobe.s on top of the hung CPU (see that file) and report whether
ATN frees the drive and whether a fresh TALK delivers data.

    BREADBIN_ULTIMATE=host SCRATCH=dir python3 atnprobe.py KERNEL.prg [STALLS]     # needs KERNEL.lbl next to it
Run it on a clean bus (emulated drive and Software IEC off). The kernel must keep its vectors in RAM ($FFFE): stage 2 does.
"""
import os
import re
import subprocess
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from bench_basic import u  # noqa: E402

img = sys.argv[1]
want = int(sys.argv[2]) if len(sys.argv) > 2 else 3
work = os.environ.get("SCRATCH", ".")
lbl = {m.group(2): int(m.group(1), 16) for l in open(img[:-4] + ".lbl")
       for m in [re.match(r"al ([0-9A-F]{6}) \.(\S+)", l)] if m}
defs = [f"-DBUS_UNTLK=${lbl['bus_untlk']:04X}", f"-DIN_BEGIN=${lbl['iec_in_begin']:04X}", f"-DIN_BYTE=${lbl['iec_in_byte']:04X}"]
obj, binf = os.path.join(work, "atnprobe.o"), os.path.join(work, "atnprobe.bin")
subprocess.run(["ca65", *defs, os.path.join(here, "atnprobe.s"), "-o", obj], check=True)
subprocess.run(["ld65", "-t", "none", "-S", "0x7000", "-o", binf, obj], check=True)
code = open(binf, "rb").read()
print(f"{len(code)} bytes of probe code; kernel {os.path.basename(img)}", flush=True)


def screen_lines():
    d = u.readmem(0x0400, 1000)
    row = lambda r: "".join(chr(c + 64) if 1 <= c <= 26 else chr(c) if 32 <= c < 64 else " "
                            for c in d[r * 40:(r + 1) * 40]).rstrip().lower()
    return [l for l in (row(r) for r in range(25)) if l]


def boot():
    u.resume()
    u.run_prg(open(img, "rb").read())
    t0 = time.time()
    time.sleep(25)
    while time.time() - t0 < 80:
        if any("login:" in l for l in screen_lines()):
            return True
        time.sleep(10)
    return False


line = lambda v: f"CLK {'released' if v & 0x40 else 'HELD LOW'}, DATA {'released' if v & 0x80 else 'HELD LOW'} (${v:02X})"
stalls = tries = 0
while stalls < want and tries < 14:
    tries += 1
    if boot():
        print(f"boot {tries}: passed (no stall)", flush=True)
        continue
    stalls += 1
    u.pause()
    u.writemem(0x7F00, bytes(32))
    u.writemem(0x7000, code)
    u.writemem(0xFFFE, bytes([0x00, 0x70]))      # the next IRQ runs the probe
    back = u.readmem(0xFFFE, 2)
    u.resume()
    done = False
    for _ in range(40):
        time.sleep(1)
        r = u.readmem(0x7F00, 17)
        if r[9]:
            done = True
            break
    r = u.readmem(0x7F00, 17)
    print(f"boot {tries}: STALL {stalls}; vector now ${back[1]:02X}{back[0]:02X}", flush=True)
    print(f"   before the probe : {line(r[0])}  ST ${r[1]:02X}")
    print(f"   after UNTALK     : {line(r[2])}  ST ${r[3]:02X}")
    if done:
        print(f"   fresh TALK       : {'the drive did NOT answer' if r[4] else 'answered'}  ST ${r[5]:02X}")
        print(f"   then read        : {r[6]} bytes{' (256, no EOI)' if r[16] else ''}, ST at the end ${r[7]:02X}"
              f" ({'EOI' if r[7] & 0x40 else 'no EOI'}{', TIMEOUT' if r[7] & 2 else ''}), first bytes {bytes(r[10:16]).hex()}", flush=True)
    else:
        print("   the probe did not finish within 40 s (the drive stayed wedged, or the CPU never took the interrupt)", flush=True)
print(f"{stalls} stalls probed in {tries} boots")
