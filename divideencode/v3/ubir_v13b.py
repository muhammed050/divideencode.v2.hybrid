"""UBIR V1.3B: compact punctuation representation.

Only punctuation changes from V1.1: punctuation is encoded as a single
opcode carrying the punctuation byte in the low bits. Other V1.1 choices
remain unchanged.
"""
from __future__ import annotations
from . import ubir_v11 as base
from . import universal_binary_ir as v1
PBASE=5
PUNCTS=b'{}[],: '
MAP={c:i for i,c in enumerate(PUNCTS)}

def encode_json(data:bytes)->bytes:
    tokens=v1._json_tokens(data); from collections import Counter
    strings=Counter(t for t in tokens if t[:1]==b'"'); dictionary=sorted((x for x,n in strings.items() if n>=2),key=lambda x:(-strings[x]*len(x),x)); ids={x:i for i,x in enumerate(dictionary)}
    out=bytearray(v1._u(len(dictionary)))
    for s in dictionary: out+=v1._s(s)
    out+=v1._u(len(tokens)); prev=0
    for t in tokens:
        if t[:1] in b'{}[],:': out.append(PBASE+MAP[t[0]])
        elif t[:1]==b'"':
            i=ids.get(t); out.append(base.DICT if i is not None else base.STRING); out+=v1._u(i) if i is not None else v1._s(t)
        elif v1._JSON_INT.fullmatch(t.decode('ascii')): out.append(base.INT); x=int(t); out+=v1._u(v1._zz(x-prev)); prev=x
        else: out.append(base.RAW); out+=v1._s(t)
    return bytes(out)

def decode_json(payload:bytes)->bytes:
    p=0;n,p=v1._r(payload,p);dictionary=[]
    for _ in range(n):x,p=v1._g(payload,p);dictionary.append(x)
    count,p=v1._r(payload,p);out=bytearray();prev=0
    for _ in range(count):
        tag=payload[p];p+=1
        if PBASE<=tag<PBASE+len(PUNCTS):out.append(PUNCTS[tag-PBASE])
        elif tag==base.DICT:i,p=v1._r(payload,p);out+=dictionary[i]
        elif tag in (base.STRING,base.RAW):x,p=v1._g(payload,p);out+=x
        elif tag==base.INT:z,p=v1._r(payload,p);prev+=v1._uzz(z);out+=str(prev).encode('ascii')
        else:raise ValueError('unknown UBIR V1.3B tag')
    if p!=len(payload):raise ValueError('trailing UBIR V1.3B bytes')
    return bytes(out)

def encode(data:bytes,kind:str)->bytes:
    if kind!='json':raise ValueError('UBIR V1.3B currently supports JSON only')
    payload=encode_json(data);return v1.MAGIC+bytes([v1.VERSION,v1.K_JSON])+v1._u(len(data))+payload

def decode(blob:bytes)->bytes:
    if len(blob)<6 or blob[:4]!=v1.MAGIC or blob[4]!=v1.VERSION or blob[5]!=v1.K_JSON:raise ValueError('invalid UBIR V1.3B blob')
    raw,p=v1._r(blob,6);out=decode_json(blob[p:])
    if len(out)!=raw:raise ValueError('UBIR V1.3B length mismatch')
    return out
