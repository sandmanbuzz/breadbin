# Run from this directory after: ca65 p1.s -o p1.o && ld65 -C p1.cfg -o p1.bin -Ln p1.lbl p1.o
# (entry points $C015 blk_to_ts and $C043 ts_block come from p1.lbl)
from py65.devices.mpu6502 import MPU
b=open('p1.bin','rb').read()
def run(addr,a=0,x=0,y=0,mem=None):
    m=MPU(); m.memory[0xC000:0xC000+len(b)]=list(b)
    for k,v in (mem or {}).items(): m.memory[k]=v
    m.sp=0xfd; m.memory[0x01fe]=0xEF; m.memory[0x01ff]=0xFF  # the routine's rts lands on $FFF0
    m.pc=addr; m.a=a; m.x=x; m.y=y
    n=0
    while m.pc!=0xFFF0 and n<100000: m.step(); n+=1
    return m
spt=[21]*17+[19]*7+[18]*6+[17]*5
lo=[0]
for s in spt: lo.append(lo[-1]+s)
bt=0xC015; tb=0xC043
for blk in range(683):
    m=run(bt,mem={0x0300:blk&255,0x0301:blk>>8})
    t=max(i for i in range(35) if lo[i]<=blk)
    assert (m.memory[0x0302],m.memory[0x0303])==(t+1,blk-lo[t]),(blk,m.memory[0x302],m.memory[0x303])
for t in range(1,36):
    for s in range(spt[t-1]):
        m=run(tb,a=t,x=s); v=lo[t-1]+s
        assert m.x==v&255 and m.y==v>>8,(t,s)
print("ok 683 blocks + all t/s")
