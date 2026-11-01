"""The control: with the STOCK KERNAL (Kernal ROM = "" in the Ultimate config, then machine:reboot;
a plain reset does not apply it) load the boot program from device 8 five times by BASIC's
LOAD"*",8,1 (standard protocol, ROM receive code) and compare every byte with the file.

    BREADBIN_ULTIMATE=host python3 stockload.py build/breadbin.prg
2026-10-31, physical 1541 (JiffyDOS 5.0 drive ROM), screen on: 5 of 5 identical (14,362 bytes each).
"""
import sys
import time

from bench_basic import feed, screen, u

prg = open(sys.argv[1], "rb").read()
addr, body = prg[0] | prg[1] << 8, prg[2:]
print(f"file: load addr ${addr:04x}, {len(body)} bytes", flush=True)
ok = 0
for n in range(1, 6):
    u.resume()
    u.reset()
    time.sleep(6)
    t0 = time.time()
    feed('load"*",8,1\n')
    time.sleep(40)
    done = False
    while time.time() - t0 < 200:
        sc = [l for l in screen().split("\n") if l.strip()]
        if sc[-1].strip() == "ready." and any(l.startswith("load") for l in sc):
            done = True
            break
        time.sleep(10)
    if not done:
        print(f"load {n}: HUNG after {time.time() - t0:.0f}s; screen tail {sc[-3:]}", flush=True)
        continue
    got = u.readmem(addr, len(body))
    bad = [i for i in range(len(body)) if got[i] != body[i]]
    print(f"load {n}: {'IDENTICAL' if not bad else f'{len(bad)} bytes differ, first at +{bad[0]}'}",
          flush=True)
    ok += not bad
print("identical loads:", ok, "of 5")
