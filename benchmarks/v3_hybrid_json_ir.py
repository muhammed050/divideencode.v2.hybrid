from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from divideencode import de2
from divideencode.v3 import hybrid_json_ir as h
from divideencode.v3 import universal_binary_ir as ub

CORPUS=Path(__file__).parent/'corpus'; BS=1<<20
print('V3 HYBRID JSON IR — separated structure/text + integer stream -> DE2')
for name in ('json_small.json','json_large.json'):
    d=(CORPUS/name).read_bytes()
    t=time.perf_counter(); direct=de2.compress(d,block_size=BS,level='BALANCED'); dt=time.perf_counter()-t
    t=time.perf_counter(); ir=h.encode(d); et=time.perf_counter()-t
    assert h.decode(ir)==d
    t=time.perf_counter(); packed=de2.compress(ir,block_size=BS,level='BALANCED'); pt=time.perf_counter()-t
    old=ub.encode(d,'json'); oldp=de2.compress(old,block_size=BS,level='BALANCED')
    print(f'{name:18s} direct={len(direct):7,} UBIR={len(oldp):7,} hybrid={len(packed):7,} delta={len(packed)-len(direct):+7,} ({(len(packed)/len(direct)-1)*100:+.2f}%) ir={len(ir):9,} encode={et:.2f}s de2={pt:.2f}s')
