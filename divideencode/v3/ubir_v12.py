"""UBIR V1.2 research candidate.

V1.1 is frozen. V1.2 keeps the V1.1 lexical representation and byte-exact
semantics, but experiments with run-level integer coding: consecutive integer
tokens are emitted as one run with an initial absolute value followed by
Delta+ZigZag values. The candidate remains separate until benchmarked.
"""
from __future__ import annotations
from . import ubir_v11 as v11
from . import universal_binary_ir as v1

RUN_INT = 5


def encode_json(data: bytes) -> bytes:
    tokens = v1._json_tokens(data)
    from collections import Counter
    strings = Counter(t for t in tokens if t[:1] == b'"')
    dictionary = sorted((x for x,n in strings.items() if n >= 2), key=lambda x:(-strings[x]*len(x), x))
    ids = {x:i for i,x in enumerate(dictionary)}
    out = bytearray(v1._u(len(dictionary)))
    for s in dictionary: out += v1._s(s)
    out += v1._u(len(tokens))
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if v1._JSON_INT.fullmatch(t.decode('ascii')):
            vals=[]
            j=i
            while j < len(tokens) and v1._JSON_INT.fullmatch(tokens[j].decode('ascii')):
                vals.append(int(tokens[j])); j+=1
            if len(vals) >= 2:
                out.append(RUN_INT); out += v1._u(len(vals)); out += v1._u(v1._zz(vals[0]))
                prev=vals[0]
                for x in vals[1:]: out += v1._u(v1._zz(x-prev)); prev=x
                i=j; continue
        if t[:1] in b'{}[],:':
            out += bytes((v11.PUNCT,t[0])); i+=1
        elif t[:1] == b'"':
            k=ids.get(t)
            if k is None: out.append(v11.STRING); out += v1._s(t)
            else: out.append(v11.DICT); out += v1._u(k)
            i+=1
        elif v1._JSON_INT.fullmatch(t.decode('ascii')):
            out.append(v11.INT); out += v1._u(v1._zz(int(t))); i+=1
        else:
            out.append(v11.RAW); out += v1._s(t); i+=1
    return bytes(out)


def decode_json(payload: bytes) -> bytes:
    p=0; n,p=v1._r(payload,p); dictionary=[]
    for _ in range(n): x,p=v1._g(payload,p); dictionary.append(x)
    count,p=v1._r(payload,p); out=bytearray(); tokens=0
    while tokens < count:
        tag=payload[p]; p+=1
        if tag == RUN_INT:
            ln,p=v1._r(payload,p); z,p=v1._r(payload,p); prev=v1._uzz(z)
            out += str(prev).encode('ascii'); tokens += 1
            for _ in range(ln-1):
                z,p=v1._r(payload,p); prev += v1._uzz(z); out += str(prev).encode('ascii'); tokens += 1
        elif tag == v11.PUNCT:
            out.append(payload[p]); p+=1; tokens+=1
        elif tag == v11.DICT:
            k,p=v1._r(payload,p); out += dictionary[k]; tokens+=1
        elif tag in (v11.STRING,v11.RAW):
            x,p=v1._g(payload,p); out += x; tokens+=1
        elif tag == v11.INT:
            z,p=v1._r(payload,p); out += str(v1._uzz(z)).encode('ascii'); tokens+=1
        else: raise ValueError('unknown UBIR V1.2 tag')
    if p != len(payload): raise ValueError('trailing UBIR V1.2 bytes')
    return bytes(out)


def encode(data: bytes, kind: str) -> bytes:
    if kind != 'json': raise ValueError('UBIR V1.2 currently supports JSON only')
    payload=encode_json(data)
    return v1.MAGIC + bytes([v1.VERSION, v1.K_JSON]) + v1._u(len(data)) + payload


def decode(blob: bytes) -> bytes:
    if len(blob)<6 or blob[:4]!=v1.MAGIC or blob[4]!=v1.VERSION or blob[5]!=v1.K_JSON: raise ValueError('invalid UBIR V1.2 blob')
    raw,p=v1._r(blob,6); out=decode_json(blob[p:])
    if len(out)!=raw: raise ValueError('UBIR V1.2 length mismatch')
    return out
