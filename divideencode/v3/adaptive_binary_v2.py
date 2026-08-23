"""ABR2: class-aware, RLE-aware reversible text representation.

This is an experiment only. It preserves the exact UTF-8 source bytes and is
kept separate from production DE2 until the end-to-end benchmark proves a win.
"""
from __future__ import annotations
import re
from collections import Counter

MAGIC = b"ABR2"
RX = re.compile(r"\w+|\s+|[^\w\s]+", re.UNICODE)


def u(n: int) -> bytes:
    if n < 0: raise ValueError("negative")
    out=bytearray()
    while n >= 128:
        out.append((n & 127) | 128); n >>= 7
    out.append(n); return bytes(out)


def r(b: bytes, p: int) -> tuple[int,int]:
    n=0; s=0
    while p < len(b):
        x=b[p]; p+=1; n |= (x & 127) << s
        if not x & 128: return n,p
        s += 7
        if s > 63: break
    raise ValueError("bad varint")


def put(out: bytearray, x: bytes) -> None:
    out += u(len(x)); out += x


def get(b: bytes, p: int) -> tuple[bytes,int]:
    n,p=r(b,p); e=p+n
    if e>len(b): raise ValueError("truncated")
    return b[p:e],e


def cls(x: str) -> int:
    if x.isspace(): return 1
    if x.isalnum() or x == "_": return 2
    if x.isdigit(): return 3
    if all(not c.isalnum() and not c.isspace() for c in x): return 4
    return 5


def encode(data: bytes, kind: str = "text") -> bytes:
    text=data.decode("utf-8")
    toks=RX.findall(text)
    groups={i:[] for i in range(1,6)}
    for t in toks: groups[cls(t)].append(t)
    dicts={}
    ids={}
    for c, vals in groups.items():
        cnt=Counter(vals)
        # Only keep entries that can beat literal+tag overhead.
        es=[x for x,n in cnt.items() if n>=2 and len(x.encode('utf-8'))>=3]
        es.sort(key=lambda x:(-(cnt[x]*(len(x.encode('utf-8'))-2)),x))
        dicts[c]=es; ids[c]={x:i for i,x in enumerate(es)}
    out=bytearray(MAGIC + bytes([1]) + u(len(data)))
    for c in range(1,6):
        es=dicts[c]; out += u(len(es))
        for x in es: put(out,x.encode('utf-8'))
    # opcode 0=literal, 1=dict, 2=RLE of previous token.
    i=0; prev=None
    while i < len(toks):
        t=toks[i]; c=cls(t); did=ids[c].get(t)
        j=i+1
        while j<len(toks) and toks[j]==t: j+=1
        rep=j-i
        if rep>=3:
            out.append(2); out += u(rep)
        elif did is not None:
            out.append(1); out.append(c); out += u(did)
            for _ in range(rep-1):
                out.append(1); out.append(c); out += u(did)
        else:
            out.append(0); put(out,t.encode('utf-8'))
            for k in range(1,rep): out.append(0); put(out,t.encode('utf-8'))
        prev=t; i=j
    return bytes(out)


def decode(blob: bytes) -> bytes:
    if len(blob)<5 or blob[:4]!=MAGIC: raise ValueError("bad ABR2")
    raw,p=r(blob,5)
    dicts={}
    for c in range(1,6):
        n,p=r(blob,p); es=[]
        for _ in range(n): x,p=get(blob,p); es.append(x.decode('utf-8'))
        dicts[c]=es
    out=[]; prev=None
    while p<len(blob):
        op=blob[p]; p+=1
        if op==0:
            x,p=get(blob,p); prev=x; out.append(x)
        elif op==1:
            if p>=len(blob): raise ValueError("truncated ref")
            c=blob[p]; p+=1; i,p=r(blob,p)
            if c not in dicts or i>=len(dicts[c]): raise ValueError("bad ref")
            prev=dicts[c][i].encode('utf-8'); out.append(prev)
        elif op==2:
            if prev is None: raise ValueError("RLE without previous")
            n,p=r(blob,p)
            if n<1: raise ValueError("bad RLE")
            out.extend([prev]*n)
        else: raise ValueError("bad opcode")
    result=b''.join(out)
    if len(result)!=raw: raise ValueError("length mismatch")
    result.decode('utf-8')
    return result


def candidates(data: bytes, suffix: str):
    s=suffix.lower()
    if s in {'.csv','.json','.jsonl','.txt','.log','.html','.css','.c','.h','.cpp','.py','.js','.ts'}:
        try:
            b=encode(data,s); 
            if decode(b)==data: return [('abr2',b)]
        except (UnicodeDecodeError,ValueError): pass
    return []
