"""Boot a kernel image by DMA (root on device 8) and report OK or STUCK; like dmaboot.py but with no state dump,
so it works for kernels that have no IEC variables (the upstream and early ones).
    BREADBIN_ULTIMATE=host python3 plainboot.py IMAGE.prg
"""
import sys,time,os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_basic import u
u.resume()
prg=open(sys.argv[1],'rb').read(); t0=time.time()
u.run_prg(prg)                                   # reset, load by DMA, RUN; $BA mimics device 8
def lines():
    d=u.readmem(0x0400,1000)
    from_codes=lambda c: chr(c+64) if 1<=c<=26 else chr(c) if 32<=c<64 else " "
    return [l for l in ("".join(from_codes(c) for c in d[r*40:(r+1)*40]).rstrip().lower() for r in range(25)) if l]
time.sleep(20)
while time.time()-t0<170:
    if any("login:" in l for l in lines()): print(f"OK    login after {time.time()-t0:.0f}s"); sys.exit(0)
    time.sleep(10)
dd=u.readmem(0xDD00,1)[0]
try:
    import re
    lbl={m.group(2):int(m.group(1),16) for l in open(sys.argv[1][:-4]+".lbl") for m in [re.match(r"al ([0-9A-F]{6}) \.(\S+)",l)] if m}
    base=lbl["io_out"]; v=u.readmem(base,15); nm="io_out io_base io_b io_n io_to io_pend io_held io_eoi io_inf io_sx io_sy ie_dev ie_sa ie_len ie_len2".split()
    assert lbl["io_n"]==base+3 and lbl["ie_dev"]==base+11, "variable layout changed: fix the dump"
    open(sys.argv[1]+".stall","a").write(str({n:f"{b:02x}" for n,b in zip(nm,v)})+" stack:"+u.readmem(0x1C0,64).hex()+"\n")
except Exception:
    pass
print(f"STUCK after 170s; last line {lines()[-1]!r}; $90={u.readmem(0x90,1).hex()} $BA={u.readmem(0xBA,1).hex()} $DD00={dd:02x}")
