"""When does the Ultimate write a mounted, writable disk image back to its file?

Copies build/breadbin.d64 to /Temp/wb.d64 by FTP, mounts it read/write on drive A (bus 9), writes block
1/1 through the drive from BASIC (U2), then polls the file over FTP once a second and reports when
that block's bytes change: at the U2, after a delay, or only at unmount/reset. Needs BREADBIN_ULTIMATE
and tools/with-lock -r ultimate. Drive A's mount is put back afterwards.

    BREADBIN_ULTIMATE=host python3 writeback.py [IMAGE.d64]
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_basic import u, feed, screen  # noqa: E402

H = os.environ["BREADBIN_ULTIMATE"].split(":")[0]
here = os.path.dirname(os.path.abspath(__file__))
img = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "..", "build", "breadbin.d64")
OFF = 256 * (0 + 1)                      # track 1, sector 1: linear block 1
PAT = b"WRITEBACK-PROBE"


def ftp_get():
    return subprocess.run(["curl", "-s", "-m", "20", f"ftp://{H}/Temp/wb.d64"], capture_output=True).stdout


def ftp_put(data):
    subprocess.run(["curl", "-s", "-m", "60", "-T", "-", f"ftp://{H}/Temp/wb.d64"], input=data, check=True)


def has():
    d = ftp_get()
    return len(d) == 174848 and d[OFF:OFF + len(PAT)] == PAT


prev = u.drives()
u.resume()
ftp_put(open(img, "rb").read())
assert not has()
u.mount("a", "/Temp/wb.d64", mode="readwrite")
u.reset()
time.sleep(12)
feed('open15,9,15:open2,9,2,"#"\n')
time.sleep(5)
print(screen().splitlines()[-5:], flush=True)
feed('print#2,"' + PAT.decode().lower() + '"\n')
time.sleep(3)
print("before U2: in file:", has(), flush=True)
feed('print#15,"u2:2 0 1 1"\n')
t0 = time.time()
time.sleep(2)
feed('@#9\n')
time.sleep(3)
feed('@\n')
time.sleep(4)
print(screen().splitlines()[-6:], flush=True)
seen = None
for i in range(45):
    time.sleep(1)
    if has():
        seen = time.time() - t0
        break
print("block in the image file after U2:", f"{seen:.1f} s" if seen else "not within 45 s", flush=True)
if not seen:
    feed('close2:close15\n')
    time.sleep(3)
    print("after CLOSE of the channels:", has(), flush=True)
    u.remove("a")
    for i in range(30):
        time.sleep(1)
        if has():
            print(f"after unmount: block in the file after {i + 1} s", flush=True)
            break
    else:
        print("after unmount (30 s): not in the file", flush=True)
print(screen().splitlines()[-3:])
subprocess.run(["curl", "-s", "-m", "20", "-Q", "DELE /Temp/wb.d64", f"ftp://{H}/"], capture_output=True)
for d in prev["drives"]:
    if "a" in d and d["a"].get("image_file"):
        u.mount("a", d["a"]["image_file"], mode="readonly")
