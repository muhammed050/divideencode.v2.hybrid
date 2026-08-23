from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v16 as v16

CORPUS=Path(__file__).resolve().parent/'corpus'

def read_u(buf,p): return v16.v1._r(buf,p)

def analyze(data):
    ir=v16.encode(data,'json')
    assert v16.decode(ir)==data
    p=6+len(v16.v1._u(len(data)))
    payload=ir[p:]
    q=0
    nd,q=read_u(payload,q)
    for _ in range(nd): _,q=v16.v1._g(payload,q)
    count,q=read_u(payload,q)
    class_len,q=read_u(payload,q)
    classes=payload[q:q+class_len]; q+=class_len
    const_count,q=read_u(payload,q)
    lengths=[]
    for _ in range(6): x,q=read_u(payload,q); lengths.append(x)
    lane_names=['punct','dict','string','int','raw','const']
    lane_data=[]
    for x in lengths:
        lane_data.append(payload[q:q+x]); q+=x

    print(f'IR={len(ir):,} B DE2={len(compress(ir,block_size=1<<20,level="BALANCED")):,} B')
    print(f'class_stream raw={class_len:,} DE2={len(compress(classes,block_size=1<<20,level="BALANCED")):,}')
    for name,x,b in zip(lane_names,lengths,lane_data):
        c=len(compress(b,block_size=1<<20,level='BALANCED'))
        print(f'  {name:7s} raw={x:9,} DE2={c:8,} ratio={c/x if x else 0:6.3f}')

for name in ('json_small.json','json_large.json'):
    print('\n'+'='*80+'\n'+name)
    analyze((CORPUS/name).read_bytes())
