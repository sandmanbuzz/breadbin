"""Read three 256-byte windows ($C000, $E000, $FF00) of a drive's DOS ROM with M-R and hash them.

    SCRATCH=dir BREADBIN_ULTIMATE=host python3 romwin.py TAG DEV [DEV ...]

Use the STOCK KERNAL as the host (Kernal ROM = "" in the Ultimate config, then machine:reboot): with the
JiffyDOS KERNAL against a JiffyDOS drive, GET# on the command channel returns a zero after most bytes and
the dump is garbage. 2026-10-31 results (windows C000 / E000 / FF00): the physical 1541 and the Ultimate's
JiffyDOS_1541-II.bin give aec2a25f / dbd462e1 / 562faa37 and 5709caf0; the stock 1541.rom gives
aec2a25f / dbd462e1 / 5e6f95c2. Only the $FF00 window tells stock from JiffyDOS (183 of 256 bytes differ).
Writes SCRATCH/win_TAG_DEV.bin; keep those out of the repository (they are ROM content).
"""
import sys,time,hashlib
import os
S=os.environ.get('SCRATCH','.')            # where the window files are written
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from bench_basic import feed, u
regions=[0xC000,0xE000,0xFF00]
def read(dev):
    u.resume(); u.reset(); time.sleep(6); feed("new\n"); time.sleep(0.5)
    prog=[f'10 open15,{dev},15',
     '20 for r=0 to 2',
     '25 ad=49152:if r=1 then ad=57344',
     '26 if r=2 then ad=65280',
     '30 for k=0 to 1:a2=ad+k*128:hi=int(a2/256):lo=a2-hi*256',
     '40 print#15,"m-r"chr$(lo)chr$(hi)chr$(128)',
     '50 for i=0 to 127:get#15,a$:poke16384+r*256+k*128+i,asc(a$+chr$(0)):next',
     '60 poke 2,r*2+k+1:next k,r',
     '70 poke 4,1:close15']
    for l in prog: feed(l+"\n"); time.sleep(0.3)
    for a in (2,4): u.pause(); u.writemem(a,b"\x00"); u.resume()
    feed("run\n"); t0=time.time()
    while time.time()-t0<300:
        time.sleep(10)
        if u.readmem(4,1)[0]: break
    return bytes(u.readmem(16384,768))
import os
tag=sys.argv[1]; devs=[int(x) for x in sys.argv[2:]]
for dev in devs:
    d=read(dev); open(f"{S}/win_{tag}_{dev}.bin","wb").write(d)
    print(f"{tag} dev {dev}: "+"  ".join(f"${regions[i]:04X}:{hashlib.sha1(d[i*256:(i+1)*256]).hexdigest()[:8]} zeros={d[i*256:(i+1)*256].count(0)}" for i in range(3)),flush=True)
