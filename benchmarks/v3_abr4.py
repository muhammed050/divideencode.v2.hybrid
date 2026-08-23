from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from divideencode import de2
from divideencode.v3 import adaptive_binary_v3 as abr3
from divideencode.v3 import adaptive_binary_v4 as abr4
CORPUS=Path(__file__).parent/'corpus';BS=1<<20

def run():
 print('='*120);print('V3 ABR4 — DIRECT vs ABR1 vs ABR2 vs ABR4 NUMERIC/COLUMN TRANSFORMS -> DE2');print('='*120)
 td=ta=0
 for p in sorted(CORPUS.iterdir()):
  if not p.is_file():continue
  data=p.read_bytes();t=time.perf_counter();d=de2.compress(data,block_size=BS,level='BALANCED');dt=time.perf_counter()-t;assert de2.decompress(d)==data
  best=(len(d),'direct',len(data),dt)
  for label,mod in [('abr3',abr3),('abr4',abr4)]:
   for c in mod.candidates(data,p.suffix):
    if label=='abr3':
     kind,x=c.kind,c.payload
     decoded=mod.decode(kind,x)
    else:
     kind,x=c
     decoded=mod.decode(x)
    t=time.perf_counter();z=de2.compress(x,block_size=BS,level='BALANCED');et=time.perf_counter()-t
    assert decoded==data and de2.decompress(z)==x
    if len(z)<best[0]:best=(len(z),f'{label}:{kind}' if label=='abr4' else kind,len(x),et)
  td+=len(d);ta+=best[0]
  print(f'{p.name:24s} direct={len(d):9,d} best={best[0]:9,d} delta={best[0]-len(d):+9,d} choice={best[1]:16s} mid={best[2]:9,d} enc={best[3]:5.2f}s')
 print('-'*120);print(f'TOTAL direct={td:,} B ABR4={ta:,} B delta={ta-td:+,} B ({(ta/td-1)*100:+.2f}%)')
if __name__=='__main__':run()
