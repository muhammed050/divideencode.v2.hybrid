from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v16 as v16

CORPUS=Path(__file__).resolve().parent/'corpus'

def varint(n):
    return len(v16.v1._u(n))

def analyze(data):
    ir=v16.encode(data,'json')
    assert v16.decode(ir)==data
    payload=ir[6+len(v16.v1._u(len(data))):]
    p=0
    nd,p=v16.v1._r(payload,p)
    dictionary=[]
    for _ in range(nd):
        x,p=v16.v1._g(payload,p); dictionary.append(x)
    count,p=v16.v1._r(payload,p)
    class_len,p=v16.v1._r(payload,p); classes=payload[p:p+class_len]; p+=class_len
    const_count,p=v16.v1._r(payload,p)
    lengths=[]
    for _ in range(6):
        x,p=v16.v1._r(payload,p); lengths.append(x)
    names=('punct','dict','string','int','raw','const')
    print(f'file={len(data):,} B tokens={count:,} dict={nd:,} IR={len(ir):,} B')
    print(f'class_stream={class_len:,} B const_count={const_count:,}')
    total=sum(lengths)+class_len
    for n,x in zip(names,lengths):
        packed=compress((v16.v1._u(x)+payload[0:0]),block_size=1<<20,level='BALANCED') if False else None
        print(f'  {n:7s} raw={x:9,} B {x/len(ir)*100:6.2f}%')
    print(f'  lane_total={total:,} B ({total/len(ir)*100:.2f}% of IR)')
    print('  DE2 whole IR=',len(compress(ir,block_size=1<<20,level='BALANCED')),'B')

for name in ('json_small.json','json_large.json'):
    print('\n'+'='*80+'\n'+name)
    analyze((CORPUS/name).read_bytes())
