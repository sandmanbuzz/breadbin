"""Copy a disk image onto the physical 1541 with the Keymaster nibbler, with no hands: the physical drive (wired as
device 8) is renumbered to 9 in software (M-W to its RAM at $77/$78: listen $29, talk $49), the emulated drive A is
given bus 8 and the image, the nibbler runs its default copy (8 to 9), and afterwards "UI" on device 9 resets the
drive, which reads its switches again and is back at 8. Run under tools/with-lock -r ultimate, on the stock KERNAL
host with Software IEC off (nibcopy.sh does the configuration and restores it).

    BREADBIN_ULTIMATE=host NIBBLER=path/to/keym.d.nibbler.prg python3 nibcopy.py IMAGE_PATH_ON_THE_ULTIMATE

The physical disk is OVERWRITTEN. Checks the directory of the result with LOAD"$",8 at the end (screen text printed).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_basic import feed, screen, u  # noqa: E402

image = sys.argv[1]
host = os.environ["BREADBIN_ULTIMATE"]


def put(path):
    import urllib.request
    urllib.request.urlopen(urllib.request.Request(f"http://{host}{path}", method="PUT"), timeout=10).read()


def step(text, wait):
    feed(text)
    time.sleep(wait)


u.resume()
put("/v1/drives/a:off")
u.reset()
time.sleep(8)
# 1. the physical drive (the only one on the bus now) becomes device 9
step('open15,8,15,"m-w"+chr$(119)+chr$(0)+chr$(2)+chr$(41)+chr$(73):close15\n', 4)
step('load"$",9\n', 8)
print("physical drive answers as 9:", "device not present" not in screen(), flush=True)
# 2. the emulated drive A becomes device 8 with the image
put("/v1/configs/Drive%20A%20Settings/Drive%20Bus%20ID?value=8")
u.mount("a", image, type="d64", mode="readonly")
put("/v1/drives/a:on")
time.sleep(4)
step("print chr$(147)\n", 2)
step('load"$",9\n', 7)
print("physical still 9 after A on and mount:", "device not present" not in screen(), flush=True)
# 3. the nibbler, default copy 8 -> 9
# Not u.run_prg / u.load_prg: both reset the machine, and the reset line takes the renumbered drive back to 8.
# Put the BASIC program in memory by DMA and RUN it from the keyboard buffer.
prg = open(os.environ["NIBBLER"], "rb").read()
assert prg[0] | prg[1] << 8 == 0x0801
end = 0x0801 + len(prg) - 2
u.pause()
u.writemem(0x0801, prg[2:])
for zp in (0x2D, 0x2F, 0x31, 0xAE):
    u.writemem(zp, bytes([end & 255, end >> 8]))
u.resume()
feed("run\n")
time.sleep(4)
feed("c")
time.sleep(3)
feed("\n")
t0 = time.time()
time.sleep(20)                      # no screen read during the transfer
done = False
while time.time() - t0 < 1500:
    row = bytes(u.readmem(0x0400 + 40 * 19, 40))               # "copy complete" is on screen row 19 (copying: row 16)
    if row[6] == 3 and row[7] == 15:                           # "co" in screen codes
        done = True
        break
    time.sleep(5)
print(f"{'finished' if done else 'TIMEOUT'} after {time.time() - t0:.0f} s", flush=True)
print(screen(), flush=True)
# 4. back to normal: A off, bus 9; the physical drive reset back to 8
feed(" ")
time.sleep(2)
feed("e")
time.sleep(3)
put("/v1/drives/a:off")
put("/v1/configs/Drive%20A%20Settings/Drive%20Bus%20ID?value=9")
step('open15,9,15,"ui":close15\n', 8)
step('load"$",8\n', 10)
step("list\n", 3)
print("physical drive back at 8, its directory:\n" + screen(), flush=True)
put("/v1/drives/a:on")
