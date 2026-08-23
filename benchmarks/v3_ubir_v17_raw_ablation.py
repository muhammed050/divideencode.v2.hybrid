from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v16 as v16

CORPUS=Path(__file__).resolve().parent/'corpus'

def u(buf,p): return v16.v1._r(buf,p)

def parse(data):
    ir=v16.encode(data,'json'); p=6+len(v16.v1._u(len(data))); b=ir[p:]; q=0
    nd,q=u(b,q)
    for _ in range(nd): _,q=v16.v1._g(b,q)
    count,q=u(b,q); cl,q=u(b,q); classes=b[q:q+cl]; q+=cl
    cc,q=u(b,q); lens=[]
    for _ in range(6): x,q=u(b,q); lens.append(x)
    lanes=[]
    for x in lens: lanes.append(b[q:q+x]); q+=x
    return ir,classes,lanes

def packed(b): return len(compress(b,block_size=1<<20,level='BALANCED'))

for name in ('json_small.json','json_large.json'):
    data=(CORPUS/name).read_bytes(); ir,classes,lanes=parse(data)
    print('\n'+'='*80+'\n'+name)
    print(f'V1.6 whole IR={len(ir):,} DE2={packed(ir):,} B')
    names=['punct','dict','string','int','raw','const']
    for n,b in zip(names,lanes): print(f'{n:7s}: {len(b):9,} -> {packed(b):8,} B')

    raw=lanes[4]
    try:
        vals=[]; q=0
        while q<len(raw):
            x,q=v16.v1._g(raw,q)
            vals.append(x)
        joined=b''.join(vals)
        lengths=b''.join(v16.v1._u(len(x)) for x in vals)
        payload=lengths+joined
        print(f'raw variants: current={packed(raw):,} concat={packed(joined):,} lengths+concat={packed(payload):,} B')
        heads=bytes((x[0] if x else 0) for x in vals)
        tails=b''.join(x[1:] for x in vals)
        split=heads+tails
        print(f'raw split(heads+tails)={packed(split):,} B')
    except Exception as e:
        print('raw variant analysis skipped:',e)
