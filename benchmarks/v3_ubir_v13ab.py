from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v11 as v11,ubir_v13a as a,ubir_v13b as b,ubir_v13ab as ab
CORPUS=Path(__file__).resolve().parent/'corpus'
for name in ('json_small.json','json_large.json'):
 data=(CORPUS/name).read_bytes(); base=compress(v11.encode(data,'json'),block_size=1<<20,level='BALANCED')
 print(name)
 for label,m in (('V1.1',v11),('V1.3A',a),('V1.3B',b),('V1.3AB',ab)):
  ir=m.encode(data,'json'); assert m.decode(ir)==data
  p=compress(ir,block_size=1<<20,level='BALANCED')
  print(f'  {label:6s} {len(p):7d} B delta_vs_V11={len(p)-len(base):+7d} IR={len(ir):8d} B')
