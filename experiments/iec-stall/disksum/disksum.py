"""Compare every sector of the physical 1541's disk with a d64 image, by checksum, with reads only.

disksum.s reads all 683 sectors through the stock KERNAL (U1 block reads on channel 2) and keeps a 3-byte checksum of
each (sum of the 256 bytes mod 65536, lo and hi, and their XOR) at $5000. This script computes the same checksums from
the image on the host and compares them. A mismatch names the first differing (track, sector).

    BREADBIN_ULTIMATE=host SCRATCH=dir python3 disksum.py [IMAGE.d64]       (stock KERNAL host, Software IEC off)

The configuration is changed for the run and restored in a finally block (nibsetup.sh down: JiffyDOS KERNAL, Software IEC on). The drive is
read only; nothing is written to it. A run that stops making progress for STALL_S seconds is reported and not retried.
Exit status 0 only if the state is "done" and every sector matches.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
IEC = os.path.join(HERE, "..")
sys.path.insert(0, IEC)

TABLE, COUNT, ERRCH, STATE = 0x5000, 0xC7F0, 0xC7F2, 0xC7F4
STALL_S = 150
CAP_S = 1200          # hard cap on a run that keeps moving
POLL_S = 30
END_S = 1200          # control run: the final read, after about 683 sectors at 1 to 1.5 s each
CONTROL = "--control" in sys.argv


def spt(track):
    """Sectors on a track of a 1541 disk: 21, 19, 18 or 17."""
    return 21 if track < 18 else 19 if track < 25 else 18 if track < 31 else 17


def layout():
    """The (track, sector) order of the d64 file, 683 entries."""
    return [(t, s) for t in range(1, 36) for s in range(spt(t))]


def checksum(sector):
    """What disksum.s stores: sum of the bytes mod 65536 (lo, hi) and their XOR."""
    total = sum(sector) & 0xFFFF
    x = 0
    for b in sector:
        x ^= b
    return total & 0xFF, total >> 8, x


def command_string(track, sector):
    """The text disksum.s sends on channel 15 for a block read: decimal, no leading zeros, a space between."""
    return f"U1:2 0 {track} {sector}"


def expected(image_bytes):
    """The checksum triples of every sector of a d64 image, in layout order."""
    out = []
    for i in range(len(layout())):
        out.append(checksum(image_bytes[i * 256:(i + 1) * 256]))
    return out


def compare(got, want):
    """got, want: lists of triples in layout order. Returns (matches, differ, first_differing_track_sector)."""
    lay = layout()
    diffs = [i for i in range(len(want)) if tuple(got[i]) != tuple(want[i])]
    first = lay[diffs[0]] if diffs else None
    return len(want) - len(diffs), diffs, first


def read_table(u, n):
    raw = bytes(u.readmem(TABLE, 3 * n))
    return [tuple(raw[3 * i:3 * i + 3]) for i in range(n)]


def run(image_path):
    from bench_basic import feed, u  # opens the Ultimate connection from BREADBIN_ULTIMATE

    n = len(layout())
    binf = os.path.join(os.environ.get("SCRATCH", "."), "disksum.bin")
    subprocess.run(["ca65", os.path.join(HERE, "disksum.s"), "-o", binf + ".o"], check=True)
    subprocess.run(["ld65", "-t", "none", "-S", "0xC000", "-o", binf, binf + ".o"], check=True)
    code = open(binf, "rb").read()
    want = expected(open(image_path, "rb").read())

    h = os.environ["BREADBIN_ULTIMATE"]
    import urllib.request

    def put(path, value):
        urllib.request.urlopen(urllib.request.Request(f"http://{h}/v1/configs/{path}?value={value}", method="PUT"),
                               timeout=10).read()

    def reboot():
        urllib.request.urlopen(urllib.request.Request(f"http://{h}/v1/machine:reboot", method="PUT"), timeout=10).read()
        time.sleep(15)

    kernal = "C64%20and%20Cartridge%20Settings/Kernal%20ROM"
    result = {"state": None}
    try:
        put("SoftIEC%20Drive%20Settings/IEC%20Drive", "Disabled")
        put(kernal, "")
        reboot()
        u.resume()
        u.reset()
        time.sleep(8)
        u.pause()
        u.writemem(0xC000, code)
        u.resume()
        feed("sys49152\n")
        t0 = time.time()
        last, last_t = -1, time.time()
        if CONTROL:
            # no polling during the run: one read at the watch time, one at the end (the control for DMA polling)
            time.sleep(STALL_S + 30)
            state = u.readmem(STATE, 1)[0]
            count = u.readmem(COUNT, 1)[0] | (u.readmem(COUNT + 1, 1)[0] << 8)
            print(f"{time.time() - t0:6.0f} s  (control, one read)  sectors {count:3d}/{n}  state {state:02X}", flush=True)
            if count == 0 and state == 0:
                result["state"] = "STALLED"
                result["at"] = 0
            else:
                time.sleep(max(0, END_S - (time.time() - t0)))
                state = u.readmem(STATE, 1)[0]
                count = u.readmem(COUNT, 1)[0] | (u.readmem(COUNT + 1, 1)[0] << 8)
                print(f"{time.time() - t0:6.0f} s  (control, final read)  sectors {count:3d}/{n}  state {state:02X}", flush=True)
        while not CONTROL:
            time.sleep(POLL_S)
            state = u.readmem(STATE, 1)[0]
            count = u.readmem(COUNT, 1)[0] | (u.readmem(COUNT + 1, 1)[0] << 8)
            print(f"{time.time() - t0:6.0f} s  sectors {count:3d}/{n}  state {state:02X}", flush=True)
            if state != 0:
                break
            if time.time() - t0 > CAP_S:
                result["state"] = "CAPPED"
                result["at"] = count
                break
            if count != last:
                last, last_t = count, time.time()
            elif time.time() - last_t > STALL_S:
                result["state"] = "STALLED"
                result["at"] = last
                break
        if result["state"] in ("STALLED", "CAPPED"):
            # before the restore (which reboots the C64): the reader's code, its pointers and the state bytes
            dump = {"code_ok": bytes(u.readmem(0xC000, len(code))) == code,
                    "code": bytes(u.readmem(0xC000, len(code))).hex(),
                    "zp_F0_FF": bytes(u.readmem(0xF0, 16)).hex(),
                    "c7f0_c7f4": bytes(u.readmem(0xC7F0, 5)).hex(),
                    "stack_top": bytes(u.readmem(0x1F0, 16)).hex(),
                    "state_c7e0_c7eb": bytes(u.readmem(0xC7E0, 12)).hex(),
                    "tp_fb_fc": bytes(u.readmem(0xFB, 2)).hex()}
            result["dump"] = dump
            result["zp_expected_init"] = {"TP": "00 50 (lo hi)", "TRK": "01 at F7 after init", "SECT": "00 at F8"}
            open(os.path.join(os.environ.get("SCRATCH", "."), "disksum-dump.bin"), "wb").write(bytes(u.readmem(0xC000, len(code))))
        if result["state"] is None:
            result["state"] = {1: "done", 0xEE: "block error", 0xEF: "open failed"}.get(state, f"{state:02X}")
        result["elapsed_s"] = round(time.time() - t0)
        result["err"] = bytes(u.readmem(ERRCH, 2)).decode("latin1", "replace")
        if result["state"] == "done":
            got = read_table(u, n)
            matches, diffs, first = compare(got, want)
            result.update(matches=matches, differ=len(diffs), first_differing=first,
                          differing=[layout()[i] for i in diffs[:20]])
    finally:
        subprocess.run(["sh", os.path.join(IEC, "nibsetup.sh"), "down"], check=False)
    print(json.dumps(result, indent=1))
    out = os.path.join(os.environ.get("SCRATCH", "."), "disksum-result.json")
    open(out, "w").write(json.dumps(result, indent=1))
    return 0 if result.get("state") == "done" and result.get("differ") == 0 else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--control"]
    img = args[0] if args else os.path.join(HERE, "..", "..", "..", "build", "breadbin.d64")
    sys.exit(run(img))
