"""UBIR V1.3CW: V1.3AB plus whitespace-run encoding.

Whitespace runs are encoded as a compact opcode + run length + one-byte
whitespace pattern. A run is used only when two or more consecutive
whitespace bytes occur; single whitespace remains RAW. This preserves
byte-exact JSON and isolates the whitespace experiment from V1.3AB.
"""
from __future__ import annotations
from . import ubir_v13ab as base
from . import universal_binary_ir as v1
WS=set(b' \t\r\n'); WRUN=15

def encode_json(data:bytes)->bytes:
 tokens=v1._json_tokens(data); from collections import Counter
 strings=Counter(t for t in tokens if t[:1]==b'"'); dictionary=sorted((x for x,n in strings.items() if n>=2),key=lambda x:(-strings[x]*len(x),x)); ids={x:i for i,x in enumerate(dictionary)}
 out=bytearray(v1._u(len(dictionary)))
 for s in dictionary:out+=v1._s(s)
 out+=v1._u(len(tokens)); prev=0
 for t in tokens:
  if t[:1] in b'{}[],:':out.append(base.PBASE+base.PMAP[t[0]])
  elif t[:1]==b'"':
   i=ids.get(t);out.append(base.base.DICT if i is not None else base.base.STRING);out+=v1._u(i) if i is not None else v1._s(t)
  elif v1._JSON_INT.fullmatch(t.decode('ascii')):out.append(base.base.INT);x=int(t);out+=v1._u(v1._zz(x-prev));prev=x
  elif t==b'true':out.append(base.TRUE)
  elif t==b'false':out.append(base.FALSE)
  elif t==b'null':out.append(base.NULL)
  elif t and all(c in WS for c in t) and len(t)>=2:
   # preserve exact run; token itself is whitespace-only in the JSON tokenizer
   out.append(WRUN);out+=v1._u(len(t));out.append(t[0] if all(c==t[0] for c in t) else 255);out+=t if t[0]==255 else b''
  else:out.append(base.base.RAW);out+=v1._s(t)
 return bytes(out)

def decode_json(payload:bytes)->bytes:
 p=0;n,p=v1._r(payload,p);dictionary=[]
 for _ in range(n):x,p=v1._g(payload,p);dictionary.append(x)
 count,p=v1._r(payload,p);out=bytearray();prev=0
 for _ in range(count):
  tag=payload[p];p+=1
  if base.PBASE<=tag<base.PBASE+len(base.PUNCTS):out.append(base.PUNCTS[tag-base.PBASE])
  elif tag==base.base.DICT:i,p=v1._r(payload,p);out+=dictionary[i]
  elif tag in (base.base.STRING,base.base.RAW):x,p=v1._g(payload,p);out+=x
  elif tag==base.base.INT:z,p=v1._r(payload,p);prev+=v1._uzz(z);out+=str(prev).encode()
  elif tag==base.TRUE:out+=b'true'
  elif tag==base.FALSE:out+=b'false'
  elif tag==base.NULL:out+=b'null'
  elif tag==WRUN:
   ln,p=v1._r(payload,p);pat=payload[p];p+=1
   if pat!=255:out+=bytes([pat])*ln
   else:out+=payload[p:p+ln];p+=ln
  else:raise ValueError('unknown UBIR V1.3CW tag')
 if p!=len(payload):raise ValueError('trailing UBIR V1.3CW bytes')
 return bytes(out)

def encode(data:bytes,kind:str)->bytes:
 if kind!='json':raise ValueError('UBIR V1.3CW supports JSON only')
 payload=encode_json(data);return v1.MAGIC+bytes([v1.VERSION,v1.K_JSON])+v1._u(len(data))+payload

def decode(blob:bytes)->bytes:
 if len(blob)<6 or blob[:4]!=v1.MAGIC or blob[4]!=v1.VERSION or blob[5]!=v1.K_JSON:raise ValueError('invalid UBIR V1.3CW blob')
 raw,p=v1._r(blob,6);out=decode_json(blob[p:])
 if len(out)!=raw:raise ValueError('UBIR V1.3CW length mismatch')
 return out
