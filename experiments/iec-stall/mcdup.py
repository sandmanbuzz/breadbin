"""Copy a D64 onto a drive with no keyboard: mount it as the Ultimate's Drive A (device 9), load mcdup.s by DMA
on the stock KERNAL's BASIC, SYS it, and watch it copy and verify all 683 sectors to the target drive.

    SCRATCH=dir BREADBIN_ULTIMATE=host python3 mcdup.py [--dst 8|10] [--image build/breadbin.d64] [--label TEXT]

--dst 10 first writes to a blank image mounted in an emulated Drive B (bus ID 10), a safe dry run; --dst 8 writes
to the physical drive, whose disk must already be formatted. Run it on the STOCK KERNAL host (Kernal ROM = "",
then machine:reboot) with Drive A at bus ID 9. Exit status 0 only if every listed sector was copied with no drive
error and no read-back mismatch.
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from bench_basic import feed, u  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--dst", type=int, default=10, choices=(8, 10))
ap.add_argument("--image", default=os.path.join(here, "..", "..", "build", "breadbin.d64"))
ap.add_argument("--base", help="the image that is already on the target disk: copy only the sectors that differ "
                "(trust it: if the disk holds something else the result is wrong; the read-back still checks what is written)")
ap.add_argument("--label", help="up to 16 characters written into the disk's BAM name (track 18 sector 0, $90): "
                "what is on the media. The two-character disk ID is never changed: the drive checks it against "
                "every sector header")
args = ap.parse_args()
work = os.environ.get("SCRATCH", ".")
host = os.environ["BREADBIN_ULTIMATE"]


def cfg(category, item, value):
    q = urllib.parse.quote
    req = urllib.request.Request(f"http://{host}/v1/configs/{q(category)}/{q(item)}?value={q(value)}", method="PUT")
    urllib.request.urlopen(req, timeout=10).read()


obj, binf = os.path.join(work, "mcdup.o"), os.path.join(work, "mcdup.bin")
subprocess.run(["ca65", os.path.join(here, "mcdup.s"), "-o", obj], check=True)
subprocess.run(["ld65", "-t", "none", "-S", "0xC000", "-o", binf, obj], check=True)
code = open(binf, "rb").read()
image = open(args.image, "rb").read()
assert len(image) == 174848, "expected a 35-track D64 (174848 bytes)"
if args.label:                  # track 18 starts at sector 17 * 21 = 357; the name field is $90-$9F, padded with $A0
    name = args.label.upper().encode("ascii")[:16].ljust(16, b"\xa0")
    off = 357 * 256 + 0x90
    image = image[:off] + name + image[off + 16:]
    print(f"label: {args.label.upper()[:16]!r}", flush=True)
a = [d["a"] for d in u.drives()["drives"] if "a" in d][0]
assert a["enabled"] and a["bus_id"] == 9, f"Drive A must be enabled at bus ID 9: {a}"
print(f"{len(code)} bytes of code; image {len(image)} bytes -> device {args.dst}", flush=True)
sec_per = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5          # tracks 1-35
pairs = [(t, sec) for t in range(1, 36) for sec in range(sec_per[t - 1])]
start = [sum(sec_per[:t]) for t in range(35)]                   # first linear sector of each track
if args.base:
    base = open(args.base, "rb").read()
    assert len(base) == len(image)
    pairs = [(t, sec) for t, sec in pairs
             if image[(start[t - 1] + sec) * 256:][:256] != base[(start[t - 1] + sec) * 256:][:256]]
print(f"{len(pairs)} sectors to copy" + (f" (differing from {os.path.basename(args.base)})" if args.base else ""), flush=True)
u.mount("a", image, type="d64", mode="readonly", name=os.path.basename(args.image))
if args.dst == 10:
    cfg("Drive B Settings", "Drive Bus ID", "10")
    cfg("Drive B Settings", "Drive", "Enabled")
    u.mount("b", bytes(174848), type="d64", mode="unlinked", name="dupdst.d64")
u.resume()
u.reset()
time.sleep(8)
u.pause()
u.writemem(0xC000, code)
total = len(pairs)
u.writemem(0xC7E0, bytes([9, args.dst, total & 255, total >> 8]))
u.writemem(0xC7F0, bytes(9))
if pairs:
    u.writemem(0xCA00, bytes(b for p in pairs for b in p))
u.resume()
feed("sys49152\n")
t0 = time.time()
last, lastt = -1, time.time()
ok = False
while time.time() - t0 < 1500:
    time.sleep(20)
    p = u.readmem(0xC7F0, 9)
    n = p[1] | p[2] << 8
    print(f"{time.time() - t0:5.0f}s  {n} of {total} sectors, drive errors {p[3]}, mismatches {p[4]}", flush=True)
    if p[0]:
        ok = n == total and p[3] == 0 and p[4] == 0
        if p[3]:
            print(f"first error at track {p[5]} sector {p[6]}: status {chr(p[7])}{chr(p[8])}")
        break
    if n == last and time.time() - lastt > 120:
        print("STALLED at sector", n)
        break
    if n != last:
        last, lastt = n, time.time()
print("RESULT:", f"{total} sectors copied and verified" if ok else "NOT clean")
sys.exit(0 if ok else 1)
