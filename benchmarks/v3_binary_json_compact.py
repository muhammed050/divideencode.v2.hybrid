from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from divideencode import de2
from divideencode.v3 import binary_json_compact as c

CORPUS=Path(__file__).parent/'corpus'; BS=1<<20
for name in ('json_small.json','json_large.json'):
    d=(CORPUS/name).read_bytes(); t=time.perf_counter(); ir=c.encode(d); et=time.perf_counter()-t
    t=time.perf_counter(); direct=de2.compress(d,block_size=BS,level='BALANCED'); dt=time.perf_counter()-t
    t=time.perf_counter(); packed=de2.compress(ir,block_size=BS,level='BALANCED'); pt=time.perf_counter()
    print(f'{name:18s} source={len(d):9,} direct={len(direct):7,} compact_ir={len(ir):9,} packed={len(packed):7,} delta={len(packed)-len(direct):+7,} ({(len(packed)/len(direct)-1)*100:+.2f}%) encode={et:.2f}s de2={pt-t:.2f}s')
