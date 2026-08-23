from pathlib import Path
import sys,time
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import universal_binary_ir as v1
from divideencode.v3 import ubir_v13ab as base
CORPUS=Path(__file__).resolve().parent/'corpus'

def u(n):
 o=bytearray()
 while n>=128:o.append((n&127)|128);n>>=7
 o.append(n);return bytes(o)

def encode(data):
 toks=v1._json_tokens(data)
 # Preserve V1.3AB's layout; only change RAW token payloads.
 # Candidate: store raw tokens as a shared byte dictionary only when the
 # reference plus dictionary entry is cheaper than the original framing.
 raws=[t for t in toks if t[:1] not in b'{}[],:"' and not v1._JSON_INT.fullmatch(t.decode('ascii')) and t not in (b'true',b'false',b'null')]
 c=Counter(raws);d=sorted((x for x,n in c.items() if n>=2 and len(x)>=3 and len(x)+2 < n*2),key=lambda x:(-c[x]*len(x),x))
 ids={x:i for i,x in enumerate(d)}
 out=bytearray(v1._u(len(d)))
 for x in d:out+=v1._s(x)
 out+=v1._u(len(toks))
 for t in toks:
  if t in ids:out.append(0x7D);out+=v1._u(ids[t])
  else:out.append(0x00);out+=v1._s(t)
 return v1.MAGIC+bytes([v1.VERSION,v1.K_JSON])+v1._u(len(data))+bytes(out)

def decode(blob):
 p=6;raw,p=v1._r(blob,p);n,p=v1._r(blob,p);d=[]
 for _ in range(n):x,p=v1._g(blob,p);d.append(x)
 count,p=v1._r(blob,p);out=bytearray()
 for _ in range(count):
  tag=blob[p];p+=1
  if tag==0x7D:i,p=v1._r(blob,p);out+=d[i]
  else:x,p=v1._g(blob,p);out+=x
 if len(out)!=raw:raise ValueError('length mismatch')
 return bytes(out)

def run():
 for name in ('json_small.json','json_large.json'):
  data=(CORPUS/name).read_bytes(); b=compress(base.encode(data,'json'),block_size=1<<20,level='BALANCED')
  t=time.perf_counter();ir=encode(data);et=time.perf_counter()-t;assert decode(ir)==data
  p=compress(ir,block_size=1<<20,level='BALANCED')
  print(f'{name}\n  V1.3AB={len(b):7d} B raw-focused={len(p):7d} B delta={len(p)-len(b):+7d} IR={len(ir):8d} encode={et:.2f}s')
if __name__=='__main__':run()
