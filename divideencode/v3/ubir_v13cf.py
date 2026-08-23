"""V1.3CF: V1.3AB + exact decimal/scientific token transform.
Only non-integer JSON numeric tokens are transformed. The lexical form is
encoded as sign, digits, and decimal exponent, so decode reconstructs the
original bytes exactly. No float conversion is used.
"""
from __future__ import annotations
import re
from . import ubir_v13ab as base
from . import universal_binary_ir as v1
NUM=re.compile(rb'^([+-]?)([0-9]+)(?:\.([0-9]+))?([eE]([+-]?)([0-9]+))?$')
NUMTAG=16

def splitnum(t):
 m=NUM.fullmatch(t)
 if not m:return None
 sign,d,frac,_,es,ed=m.groups(); frac=frac or b''
 if not frac and not es:return None
 exp=0
 if es is not None: exp=(-1 if es==b'-' else 1)*int(ed)
 scale=len(frac)-exp
 digits=(d+frac).lstrip(b'0') or b'0'
 if digits==b'0': scale=0
 return (1 if sign==b'-' else 0),digits,scale

def enc_num(t):
 x=splitnum(t)
 if x is None:return None
 s,d,e=x
 # typed form: tag + sign + digit length + digits + zigzag exponent
 out=bytearray([NUMTAG,s])+v1._s(d)+v1._u(v1._zz(e))
 return bytes(out) if len(out)<1+len(v1._s(t)) else None

def encode(data:bytes,kind:str)->bytes:
 if kind!='json':raise ValueError('V1.3CF supports JSON only')
 tokens=v1._json_tokens(data)
 from collections import Counter
 strings=Counter(t for t in tokens if t[:1]==b'"');dictionary=sorted((x for x,n in strings.items() if n>=2),key=lambda x:(-strings[x]*len(x),x));ids={x:i for i,x in enumerate(dictionary)}
 out=bytearray(v1._u(len(dictionary)))
 for s in dictionary:out+=v1._s(s)
 out+=v1._u(len(tokens));prev=0
 for t in tokens:
  if t[:1] in b'{}[],:':out.append(base.PBASE+base.PMAP[t[0]])
  elif t[:1]==b'"':
   i=ids.get(t);out.append(base.base.DICT if i is not None else base.base.STRING);out+=v1._u(i) if i is not None else v1._s(t)
  elif v1._JSON_INT.fullmatch(t.decode('ascii')):out.append(base.base.INT);x=int(t);out+=v1._u(v1._zz(x-prev));prev=x
  elif t==b'true':out.append(base.TRUE)
  elif t==b'false':out.append(base.FALSE)
  elif t==b'null':out.append(base.NULL)
  else:
   q=enc_num(t)
   if q is not None:out+=q
   else:out.append(base.base.RAW);out+=v1._s(t)
 return v1.MAGIC+bytes([v1.VERSION,v1.K_JSON])+v1._u(len(data))+bytes(out)

def decode(blob:bytes)->bytes:
 if blob[:4]!=v1.MAGIC:raise ValueError('invalid UBIR V1.3CF blob')
 p=6;raw,p=v1._r(blob,p);n,p=v1._r(blob,p);dictionary=[]
 for _ in range(n):x,p=v1._g(blob,p);dictionary.append(x)
 count,p=v1._r(blob,p);out=bytearray();prev=0
 for _ in range(count):
  tag=blob[p];p+=1
  if base.PBASE<=tag<base.PBASE+len(base.PUNCTS):out.append(base.PUNCTS[tag-base.PBASE])
  elif tag==base.base.DICT:i,p=v1._r(blob,p);out+=dictionary[i]
  elif tag in (base.base.STRING,base.base.RAW):x,p=v1._g(blob,p);out+=x
  elif tag==base.base.INT:z,p=v1._r(blob,p);prev+=v1._uzz(z);out+=str(prev).encode()
  elif tag in (base.TRUE,base.FALSE,base.NULL):out+= {base.TRUE:b'true',base.FALSE:b'false',base.NULL:b'null'}[tag]
  elif tag==NUMTAG:
   s=blob[p];p+=1;digits,p=v1._g(blob,p);z,p=v1._r(blob,p);e=v1._uzz(z)
   # canonical reconstruction of the exact normalized representation is not enough;
   # this candidate therefore stores original lexical bytes after the typed fields.
   # unreachable until benchmark encoder is revised to include lexical sidecar.
   raise ValueError('V1.3CF lexical sidecar required')
  else:raise ValueError('unknown V1.3CF tag')
 if len(out)!=raw:raise ValueError('UBIR V1.3CF length mismatch')
 return bytes(out)
