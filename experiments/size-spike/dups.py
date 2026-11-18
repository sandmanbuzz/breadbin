import re,sys,glob,collections
files=sorted(glob.glob('src/kernel/*.s'))
BR={'bne','beq','bcc','bcs','bpl','bmi','bvc','bvs'}
JMP={'jmp','jsr'}
def size(op,arg):
    if not arg: return 1
    if arg.startswith('#'): return 2
    if op in BR: return 2
    if op in JMP: return 3
    a=arg.replace(' ','')
    if re.match(r'^\(.*\)',a): return 2 if op!='jmp' else 3
    if re.match(r'^(tmp|p\d|k_|cur$|\$[0-9a-f]{2}$)',a.split(',')[0]): return 2
    return 3
seqs=[]
for f in files:
    ins=[]
    for ln in open(f):
        ln=ln.split(';')[0].strip()
        ln=re.sub(r'^[@\w.]+:\s*','',ln)
        if not ln or ln.startswith('.'): 
            if ln.startswith(('.segment','.proc','.endproc')): ins.append(None)
            continue
        p=ln.split(None,1); op=p[0].lower(); arg=p[1].strip() if len(p)>1 else ''
        if not re.match(r'^[a-z]{3}$',op): ins.append(None); continue
        if op in BR or op in JMP: key=(op,'L' if op in BR else arg)
        else: key=(op,arg)
        ins.append((key,size(op,arg),f,ln))
    seqs.append(ins)
N=int(sys.argv[1]) if len(sys.argv)>1 else 4
d=collections.defaultdict(list)
for ins in seqs:
    for i in range(len(ins)-N):
        w=ins[i:i+N]
        if any(x is None for x in w): continue
        k=tuple(x[0] for x in w)
        d[k].append((w[0][2],i,sum(x[1] for x in w)))
res=[]
for k,v in d.items():
    if len(v)<2: continue
    b=v[0][2]
    if b<8: continue
    res.append(((len(v)-1)*(b-3),b,len(v),k,v))
res.sort(reverse=True)
for s,b,n,k,v in res[:40]:
    print(s,b,n,[f"{o} {a}".strip() for (o,a) in k], sorted(set(x[0].split('/')[-1] for x in v)))
