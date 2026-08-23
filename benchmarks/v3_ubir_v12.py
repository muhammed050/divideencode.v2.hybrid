from pathlib import Path
import time, sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v11 as v11, ubir_v12 as v12
CORPUS=Path(__file__).resolve().parent/'corpus'
for name in ('json_small.json','json_large.json'):
 data=(CORPUS/name).read_bytes()
 b11=v11.encode(data,'json'); p11=compress(b11,block_size=1<<20,level='BALANCED'); assert v11.decode(b11)==data
 t=time.perf_counter(); b12=v12.encode(data,'json'); et=time.perf_counter()-t; assert v12.decode(b12)==data
 t=time.perf_counter(); p12=compress(b12,block_size=1<<20,level='BALANCED'); dt=time.perf_counter()-t
 print(f'{name:18s} V1.1={len(p11):7d} V1.2={len(p12):7d} delta={len(p12)-len(p11):+7d} ir={len(b12):8d} encode={et:.2f}s de2={dt:.2f}s')
