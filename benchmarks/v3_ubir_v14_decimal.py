from pathlib import Path
import sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v13ab as ab,ubir_v14_decimal as v14
CORPUS=Path(__file__).resolve().parent/'corpus'
for name in ('json_small.json','json_large.json'):
 data=(CORPUS/name).read_bytes()
 t=time.perf_counter();ir=v14.encode(data);et=time.perf_counter()-t
 assert v14.decode(ir)==data
 base=compress(ab.encode(data,'json'),block_size=1<<20,level='BALANCED')
 packed=compress(ir,block_size=1<<20,level='BALANCED')
 print(f'{name}\n  V1.3AB={len(base):7d} B V1.4={len(packed):7d} B delta={len(packed)-len(base):+7d} IR={len(ir):8d} encode={et:.2f}s')
