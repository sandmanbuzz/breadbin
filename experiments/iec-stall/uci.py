"""Measure the Ultimate Command Interface from the C64 with uci.s (needs "Command Interface" enabled in the Ultimate's
configuration; no drives, no Breadbin). Builds a script of operations, loads the program by DMA, runs it, decodes the log.

    BREADBIN_ULTIMATE=host python3 uci.py GROUP [GROUP ...]
GROUPS: basic latency throughput errors dual irq net write (write creates /Temp/uci32k.bin, 32 KB, used by the others)
The report numbers match the questions in docs/hardware-notes.md ("UCI as measured").
"""
import os
import struct
import subprocess
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from bench_basic import feed, u  # noqa: E402

FILE = b"/Temp/uci32k.bin"


def cmd(*b):
    b = bytes(b)
    assert len(b) <= 255
    return bytes([1, len(b)]) + b


def rdloop(target, chunk, total):
    return bytes([2, target]) + struct.pack("<HH", chunk, total)


def rdtight(target, chunk, total, blind=False):
    return bytes([6 if blind else 5, target]) + struct.pack("<HH", chunk, total)


def ctrl(v):
    return bytes([3, v])


def wrfill(target, chunk, total, pat=0xFF):
    return bytes([4, target]) + struct.pack("<HH", chunk, total) + bytes([pat])


def open_read(t=1, name=FILE):
    return cmd(t, 0x02, 0x01, *name)


def close(t=1):
    return cmd(t, 0x03)


def seek(t, pos):
    return cmd(t, 0x06, *struct.pack("<I", pos))


GROUPS = {
    "basic": ([("identify", cmd(1, 0x01)), ("echo", cmd(1, 0xF0, *b"hello")),
               ("get path", cmd(1, 0x12)), ("get time", cmd(1, 0x26)),
               ("identify target 2", cmd(2, 0x01))]),
    "write": ([("create 32 KB file", cmd(1, 0x02, 0x0A, *FILE)), ("write 32 KB in 512-byte chunks", wrfill(1, 512, 32768)),
               ("close", close()), ("stat", cmd(1, 0x08, *FILE))]),
    "latency": ([(f"{n} {i}", op) for i in range(10) for n, op in
                 (("open", open_read()), ("seek 0", seek(1, 0)), ("file info", cmd(1, 0x07)), ("close", close()))]),
    "throughput": ([x for c in (256, 512, 4096, 32768)
                    for x in ((f"open", open_read()), (f"read 32 KB in {c}-byte requests", rdloop(1, c, 32768)),
                              ("close", close()))]),
    "tight": ([x for c, blind in ((512, False), (4096, False), (32768, False), (512, True), (4096, True), (32768, True))
               for x in (("open", open_read()), (f"tight {'blind' if blind else 'checked'} read 32 KB in {c}-byte requests",
                          rdtight(1, c, 32768, blind)), ("close", close()))]),
    "paths": ([("change dir /Temp", cmd(1, 0x11, *b"/Temp")), ("get path", cmd(1, 0x12)),
               ("file stat, relative name", cmd(1, 0x08, *b"uci32k.bin")),
               ("file stat, absolute name", cmd(1, 0x08, *FILE)), ("change dir /", cmd(1, 0x11, *b"/")),
               ("file stat, absolute name from /", cmd(1, 0x08, *FILE)), ("get path", cmd(1, 0x12))]),
    "create": ([x for i in range(5) for x in ((f"create {i}", cmd(1, 0x02, 0x0A, *b"/Temp/uci-c.bin")), ("close", close()))]),
    "reubig": ([x for name, size in (("128 KB", 128), ("512 KB", 512)) for x in
                ([(f"create {name}", cmd(1, 0x02, 0x0A, *(b"/Temp/uci-" + name[:3].encode() + b".bin")))] +
                 [(f"write {name} part {k}", wrfill(1, 512, 32768)) for k in range(size // 32)] +
                 [("close", close()), (f"open {name}", cmd(1, 0x02, 0x01, *(b"/Temp/uci-" + name[:3].encode() + b".bin"))),
                  (f"LOAD REU {name}", cmd(1, 0x21, *struct.pack("<I", 0x40000), *struct.pack("<I", size * 1024))),
                  ("close", close())])]),
    "errors": ([("open a missing file", open_read(1, b"/Temp/no-such-file")), ("read with no file open", cmd(1, 0x04, 16, 0)),
                ("close with no file open", close()), ("open", open_read()), ("open again, same target", open_read()),
                ("write to a read-only file", cmd(1, 0x05, 0, 0, 1, 2, 3)), ("seek to the end", seek(1, 32768)),
                ("read past the end", cmd(1, 0x04, 16, 0)), ("seek beyond the end", seek(1, 1 << 20)),
                ("close", close())]),
    "dual": ([("open on target 1", open_read(1)), ("open on target 2", open_read(2)), ("read 16 from target 1", cmd(1, 0x04, 16, 0)),
              ("read 16 from target 2", cmd(2, 0x04, 16, 0)), ("seek target 2 to 100", seek(2, 100)),
              ("read 16 from target 1 (continues at 16?)", cmd(1, 0x04, 16, 0)), ("read 16 from target 2 (at 100?)", cmd(2, 0x04, 16, 0)),
              ("close 1", close(1)), ("close 2", close(2))]),
    "irq": ([("control register: IRQ enable", ctrl(0x20)), ("identify with the IRQ bit set", cmd(1, 0x01)),
             ("control register: IRQ off", ctrl(0x00)), ("identify", cmd(1, 0x01))]),
    "reu": ([("load 32 KB into REU at $010000 (LOAD REU)", cmd(1, 0x21, *struct.pack("<II", 0x10000, 32768)) if False else
              cmd(1, 0x21, *struct.pack("<I", 0x10000), *struct.pack("<I", 32768))),
             ("open the file again", open_read()),
             ("load the same, again", cmd(1, 0x21, *struct.pack("<I", 0x20000), *struct.pack("<I", 32768))),
             ("close", close())]),
    "net": ([("target 3 identify", cmd(3, 0x01)), ("target 4 identify", cmd(4, 0x01))]),
}


def run(name, ops):
    script = b"".join(op for _, op in ops) + b"\x00"
    assert len(script) < 0x800
    obj, binf = os.path.join(work, "uci.o"), os.path.join(work, "uci.bin")
    subprocess.run(["ca65", os.path.join(here, "uci.s"), "-o", obj], check=True)
    subprocess.run(["ld65", "-t", "none", "-S", "0xC000", "-o", binf, obj], check=True)
    code = open(binf, "rb").read()
    u.resume()
    u.reset()
    time.sleep(8)
    u.pause()
    u.writemem(0xC000, code)
    u.writemem(0x4000, script)
    u.writemem(0xC7F0, bytes(2))
    u.resume()
    feed("sys49152\n")
    t0 = time.time()
    while time.time() - t0 < 600:
        time.sleep(2)
        d = u.readmem(0xC7F0, 2)
        if d[0]:
            break
    n = d[1]
    log = u.readmem(0x8000, 64 * n) if n else b""
    print(f"== {name}: {n} operations, {time.time() - t0:.0f} s")
    for i in range(n):
        e = log[64 * i:64 * i + 64]
        label = ops[i][0]
        us = struct.unpack("<I", e[2:6])[0]
        resp, stl, res, idr, nc = struct.unpack("<HBBBB", e[6:12])
        rbytes, status = bytes(e[12:36][:min(resp, 24)]), bytes(e[36:64][:min(stl, 28)])
        rate = f"  {resp / us * 1e6:,.0f} bytes/s" if resp > 24 and us else ""
        show = rbytes.decode("latin1") if rbytes and all(32 <= c < 127 for c in rbytes) else rbytes.hex()
        print(f"{i:3d} {label:44s} {us:>8d} us  cmds {nc:3d}  resp {resp:5d}{rate}  status {status.decode('latin1').strip()!r}"
              f"{' TIMEOUT' if res else ''}  regs {e[1]:02X}/{idr:02X}  {show[:48]}")


work = os.environ.get("SCRATCH", ".")
for g in sys.argv[1:]:
    run(g, GROUPS[g])
