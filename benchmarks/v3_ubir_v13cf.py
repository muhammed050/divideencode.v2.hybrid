from pathlib import Path
import sys,time
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v13ab as ab,ubir_v13cf as cf
CORPUS=Path(__file__).resolve().parent/'corpus'
for name in ('json_small.json','json_large.json'):
 data=(CORPUS/name).read_bytes();base=compress(ab.encode(data,'json'),block_size=1<<20,level='BALANCED')
 t=time.perf_counter();ir=cf.encode(data,'json');et=time.perf_counter()-t;assert cf.decode(ir)==data
 p=compress(ir,block_size=1<<20,level='BALANCED')
 print(f'{name}\n  V1.3AB {len(base):7d} B\n  V1.3CF {len(p):7d} B delta={len(p)-len(base):+7d} IR={len(ir):8d} encode={et:.2f}s')
