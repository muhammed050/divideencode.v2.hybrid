from pathlib import Path
import sys,time,re,json
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v13ab as base
CORPUS=Path(__file__).resolve().parent/'corpus'
# Conservative experimental transform: replace repeated JSON string tokens with local dictionary refs.
# It is accepted only if final DE2 improves and roundtrip is exact.
MAG=b'V15S'; TAG=0x7E

def u(n):
 o=bytearray()
 while n>=128:o.append((n&127)|128);n>>=7
 o.append(n);return bytes(o)
def r(b,p):
 n=0;s=0
 while True:
  x=b[p];p+=1;n|=(x&127)<<s
  if x<128:return n,p
  s+=7

def encode(data):
 toks=base.v1._json_tokens(data)
 vals=[t for t in toks if t.startswith(b'"') and t.endswith(b'"')]
 c=Counter(vals); chosen=sorted((x for x,n in c.items() if n>=3),key=lambda x:(-c[x],x))
 did={x:i for i,x in enumerate(chosen)}
 out=bytearray(MAG+u(len(data))+u(len(toks))+u(len(chosen)))
 for x in chosen:out+=u(len(x))+x+u(c[x])
 for t in toks:
  if t in did:out.append(TAG);out+=u(did[t])
  else:out.append(0);out+=u(len(t))+t
 return bytes(out)

def decode(blob):
 p=4;raw,p=r(blob,p);cnt,p=r(blob,p);dc,p=r(blob,p);d=[]
 for _ in range(dc):n,p=r(blob,p);x=blob[p:p+n];p+=n;_,p=r(blob,p);d.append(x)
 out=bytearray()
 for _ in range(cnt):
  tag=blob[p];p+=1
  if tag==TAG:i,p=r(blob,p);out+=d[i]
  else:n,p=r(blob,p);out+=blob[p:p+n];p+=n
 if len(out)!=raw:raise ValueError('V1.5 length mismatch')
 return bytes(out)

def run():
 for name in ('json_small.json','json_large.json'):
  data=(CORPUS/name).read_bytes()
  direct=compress(data,block_size=1<<20,level='BALANCED')
  # Baseline V1.3AB final packed representation
  irb=base.encode(data,'json'); bpacked=compress(irb,block_size=1<<20,level='BALANCED')
  ir=encode(data); assert decode(ir)==data
  packed=compress(ir,block_size=1<<20,level='BALANCED')
  print(f'{name}\n  V1.3AB={len(bpacked):7d} B V1.5={len(packed):7d} B delta_vs_AB={len(packed)-len(bpacked):+7d} direct={len(direct):7d} IR={len(ir):8d}')
if __name__=='__main__':run()
