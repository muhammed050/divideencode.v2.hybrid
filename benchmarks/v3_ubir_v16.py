from pathlib import Path
import sys, time
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v11 as v11, ubir_v13ab as ab, ubir_v16 as v16
CORPUS=Path(__file__).resolve().parent/'corpus'
for name in ('json_small.json','json_large.json'):
    data=(CORPUS/name).read_bytes()
    base=compress(ab.encode(data,'json'),block_size=1<<20,level='BALANCED')
    print(name)
    for label,m in (('V1.1',v11),('V1.3AB',ab),('V1.6',v16)):
        t=time.perf_counter(); ir=m.encode(data,'json'); et=time.perf_counter()-t
        assert m.decode(ir)==data
        t=time.perf_counter(); packed=compress(ir,block_size=1<<20,level='BALANCED'); dt=time.perf_counter()-t
        print(f'  {label:6s} packed={len(packed):7d} B delta_vs_AB={len(packed)-len(base):+7d} IR={len(ir):8d} B encode={et:.2f}s de2={dt:.2f}s')
