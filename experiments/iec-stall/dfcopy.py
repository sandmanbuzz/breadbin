#!/usr/bin/env python3
"""Copy a .d64 image onto the physical 1541 using Disk Forge (dforge.prg) from the Ultimate's
SD card, with no hands.

dforge uses a custom screen mode during the write (color-cycling progress bar), so we detect
completion by: (1) timing (~90s for turbo write) and (2) sending RUN/STOP to dforge.

Timing expectation (from dforge docs on real hardware):
  - Turbo write (formatted disk): ~1:35
  - Turbo format + write (blank disk): ~2:05
  vs nibbler: ~50s (formatted), ~2-3 min (blank)
"""
import os
import sys
import time
import ftplib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_basic import feed, screen, u  # noqa: E402

host = os.environ["BREADBIN_ULTIMATE"]
image = sys.argv[1]


def put(path):
    import urllib.request
    urllib.request.urlopen(urllib.request.Request(f"http://{host}{path}", method="PUT"), timeout=10).read()


def step(text, wait=1):
    feed(text)
    time.sleep(wait)


def send_key(key_code):
    """Send a single key code to the keyboard buffer."""
    u.pause()
    u.writemem(0x0277, bytes([key_code]))
    u.writemem(0xC6, bytes([1]))
    u.resume()
    time.sleep(0.5)


def send_arrows(count):
    """Send arrow down key (PETSCII $8A) count times."""
    for _ in range(count):
        send_key(0x8A)


def upload_to_sd(path, filename):
    """Upload the image to the SD card via FTP."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image not found: {path}")
    
    with open(path, "rb") as f:
        ftp = ftplib.FTP(host)
        ftp.login()
        ftp.cwd("SD")
        ftp.storbinary(f"STOR {filename}", f)
        ftp.quit()
    print(f"Uploaded {path} to SD/{filename} via FTP", flush=True)


def download_from_sd(filename):
    """Download a file from the SD card via FTP."""
    ftp = ftplib.FTP(host)
    ftp.login()
    ftp.cwd("SD")
    data = []
    ftp.retrbinary(f'RETR {filename}', data.append)
    ftp.quit()
    return b''.join(data)


def screen_all():
    """Read screen from multiple addresses and return the most interesting one."""
    best = ""
    best_count = 0
    for addr in [0x0400, 0x0800, 0x0A00, 0x0C00, 0x0E00, 0x1000, 0x1400, 0x1800, 0x1C00, 0x2000, 0x2400, 0x2800, 0x2C00, 0x3000, 0x3400, 0x3800, 0x3C00]:
        data = u.readmem(addr, 40)
        non_blank = sum(1 for b in data if b != 0 and b != 32)
        if non_blank > best_count:
            best_count = non_blank
            best = "".join(chr(c + 64) if 1 <= c <= 26 else chr(c) if 32 <= c < 64 else "." for c in data).rstrip()
    return best


def main():
    print("=== dfcopy.py: Disk Forge to physical 1541 ===", flush=True)

    # 0. Clear KERNAL ROM to get stock
    print("Switching to stock KERNAL...", flush=True)
    put("/v1/configs/C64%20and%20Cartridge%20Settings/Kernal%20ROM?value=")
    put("/v1/configs/Drive%20A%20Settings/ROM%20for%201541%20mode?value=JiffyDOS_1541-II.bin")
    time.sleep(2)
    print("Stock KERNAL set.", flush=True)

    # 1. Enable Drive A and mount the local image on it (mount API uploads the file)
    print("Enabling Drive A with image...", flush=True)
    put("/v1/drives/a:on")
    put("/v1/configs/Drive%20A%20Settings/Drive%20Bus%20ID?value=8")
    with open(image, "rb") as f:
        img_data = f.read()
    u.mount("a", img_data, type="d64", mode="readonly", name=os.path.basename(image))
    time.sleep(4)
    print("Drive A mounted with image.", flush=True)

    # 2. Reset
    u.reset()
    time.sleep(8)
    print("Reset complete.", flush=True)

    # 3. Download dforge.prg from SD via FTP and load into memory
    print("Downloading dforge.prg from SD...", flush=True)
    dforge_data = download_from_sd("dforge.prg")
    print(f"dforge.prg: {len(dforge_data)} bytes", flush=True)
    
    u.pause()
    u.writemem(0x0801, dforge_data[2:])
    u.resume()
    print("dforge.prg loaded into memory.", flush=True)

    # 4. Run dforge
    u.pause()
    for zp in (0x2D, 0x2F, 0x31, 0xAE):
        u.writemem(zp, bytes([0x01, 0x08]))
    u.resume()
    feed("run\n")
    time.sleep(5)

    # 5. dforge shows splash, then file browser
    print("Waiting for dforge to initialize...", flush=True)
    time.sleep(5)
    print("Screen:", screen_all(), flush=True)

    # 6. dforge should detect Drive A is mounted and offer to write from it
    #    Press F1 to scan the mounted disk
    print("Pressing F1 to scan Drive A...", flush=True)
    send_key(0x81)  # F1
    time.sleep(3)
    print("Screen after F1:", screen_all(), flush=True)

    # 7. Press F7 to write
    print("Pressing F7 to write...", flush=True)
    send_key(0x8F)  # F7
    time.sleep(3)
    print("Screen after F7:", screen_all(), flush=True)

    # 8. Wait for write to complete (~90s for turbo write on formatted disk)
    #    During the write, the machine is paused so we can't read screen/memory.
    #    We just wait for the expected duration.
    print("Waiting for write to complete...", flush=True)
    t0 = time.time()
    while time.time() - t0 < 120:
        try:
            s = screen_all()
            print(f"Screen at {time.time() - t0:.0f}s: {s}", flush=True)
            if "complete" in s.lower() or "written" in s.lower() or "done" in s.lower():
                print("Write complete!", flush=True)
                break
            if "error" in s.lower():
                print("Error detected!", flush=True)
                break
        except Exception as e:
            # Machine is paused, can't read memory - this is expected during write
            pass
        time.sleep(5)
    
    elapsed = time.time() - t0
    if elapsed < 90:
        print(f"Waiting {90 - elapsed:.0f}s for write to complete...", flush=True)
        time.sleep(90 - elapsed)

    # 9. Send RUN/STOP to dforge to complete (dforge docs: "press RUN/STOP to get back")
    print("Sending RUN/STOP to dforge...", flush=True)
    send_key(0x82)  # RUN/STOP
    time.sleep(3)

    # 10. Verify by checking physical drive (don't rely on screen which may be in dforge state)
    print("Verifying result...", flush=True)
    # Reset the machine to get back to BASIC
    u.reset()
    time.sleep(8)
    step = lambda t, w: (feed(t), time.sleep(w))
    step("print chr$(147)\n", 2)
    step('load"$",8\n', 10)
    step("list\n", 3)
    print("Physical drive directory:\n" + screen(), flush=True)

    # 11. Restore
    put("/v1/drives/a:on")
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
