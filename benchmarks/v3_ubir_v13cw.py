from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v11 as v11,ubir_v13ab as ab,ubir_v13cw as cw
CORPUS=Path(__file__).resolve().parent/'corpus'
for name in ('json_small.json','json_large.json'):
 data=(CORPUS/name).read_bytes();basep=compress(ab.encode(data,'json'),block_size=1<<20,level='BALANCED');print(name)
 for label,m in (('V1.3AB',ab),('V1.3CW',cw)):
  ir=m.encode(data,'json');assert m.decode(ir)==data
  p=compress(ir,block_size=1<<20,level='BALANCED')
  print(f'  {label:7s} {len(p):7d} B delta_vs_AB={len(p)-len(basep):+7d} IR={len(ir):8d} B')
