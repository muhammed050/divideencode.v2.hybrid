"""V1.4 decimal packed research candidate."""
from __future__ import annotations
import re
from . import ubir_v13ab as base
from . import universal_binary_ir as v1
NUM=re.compile(rb'^(-?)([0-9]+)\.([0-9]+)$')
TAG=16

def parse(t):
 m=NUM.fullmatch(t)
 if not m:return None
 sign,a,b=m.groups();digits=(a+b).lstrip(b'0') or b'0';mant=int(digits);scale=len(b)
 if sign==b'-':mant=-mant
 if mant==0:scale=0
 return mant,scale

def fixed_bytes(mant,scale):
 neg=mant<0;d=str(abs(mant)).encode()
 if scale:
  if len(d)<=scale:d=b'0.'+b'0'*(scale-len(d))+d
  else:d=d[:-scale]+b'.'+d[-scale:]
 if neg:d=b'-'+d
 return d

def enc_num(t):
 x=parse(t)
 if x is None:return None
 mant,scale=x;lexical=fixed_bytes(mant,scale)
 side=b'' if lexical==t else b'\x01'+v1._s(t)
 q=bytes([TAG])+v1._u(v1._zz(mant))+v1._u(scale)+b'\x00'+side
 return q if len(q)<1+len(t) else None

def encode(data,kind='json'):
 if kind!='json':raise ValueError('JSON only')
 tokens=v1._json_tokens(data);out=bytearray(v1._u(0)+v1._u(len(tokens)));prev=0
 for t in tokens:
  if t[:1] in b'{}[],:':out.append(base.PBASE+base.PMAP[t[0]])
  elif t[:1]==b'"':out.append(base.base.STRING);out+=v1._s(t)
  elif v1._JSON_INT.fullmatch(t.decode('ascii')):
   out.append(base.base.INT);x=int(t);out+=v1._u(v1._zz(x-prev));prev=x
  elif t==b'true':out.append(base.TRUE)
  elif t==b'false':out.append(base.FALSE)
  elif t==b'null':out.append(base.NULL)
  else:
   q=enc_num(t)
   if q is not None:out+=q
   else:out.append(base.base.RAW);out+=v1._s(t)
 return v1.MAGIC+bytes([v1.VERSION,v1.K_JSON])+v1._u(len(data))+bytes(out)

def decode(blob):
 if blob[:4]!=v1.MAGIC:raise ValueError('invalid V1.4 blob')
 p=6;raw,p=v1._r(blob,p);_,p=v1._r(blob,p);count,p=v1._r(blob,p);out=bytearray();prev=0
 for _ in range(count):
  tag=blob[p];p+=1
  if base.PBASE<=tag<base.PBASE+len(base.PUNCTS):out.append(base.PUNCTS[tag-base.PBASE])
  elif tag in (base.base.STRING,base.base.RAW):x,p=v1._g(blob,p);out+=x
  elif tag==base.base.INT:z,p=v1._r(blob,p);prev+=v1._uzz(z);out+=str(prev).encode()
  elif tag in (base.TRUE,base.FALSE,base.NULL):out+={base.TRUE:b'true',base.FALSE:b'false',base.NULL:b'null'}[tag]
  elif tag==TAG:
   z,p=v1._r(blob,p);mant=v1._uzz(z);scale,p=v1._r(blob,p)
   if p>=len(blob):raise ValueError('truncated decimal')
   has=blob[p];p+=1
   if has:x,p=v1._g(blob,p);out+=x
   else:out+=fixed_bytes(mant,scale)
  else:raise ValueError('unknown V1.4 tag')
 if len(out)!=raw:raise ValueError('V1.4 length mismatch')
 return bytes(out)
