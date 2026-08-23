"""Hybrid Statistical JSON IR candidate.

Research candidate: preserves the successful UBIR V1 dictionary + Delta idea,
but separates structure/text from the integer stream so DE2 sees cleaner
statistical streams. This is benchmark-only until it proves a win.
"""
from __future__ import annotations
import re
from collections import Counter

MAGIC = b"HJSON"
VERSION = 1
T_PUNCT=1; T_DICT=2; T_STR=3; T_INT=4; T_RAW=5
_INT = re.compile(rb"^-?(?:0|[1-9][0-9]*)$")
_TOKEN = re.compile(rb'(?:[ \t\r\n]+|[{}\[\],:]|"(?:\\.|[^"\\])*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)')

def u(n:int)->bytes:
    if n<0: raise ValueError("negative varint")
    out=bytearray()
    while n>=128: out.append((n&127)|128); n>>=7
    out.append(n); return bytes(out)

def r(d:bytes,p:int):
    n=0; sh=0
    while p<len(d):
        x=d[p]; p+=1; n|=(x&127)<<sh
        if not x&128:return n,p
        sh+=7
        if sh>4096:raise ValueError("varint too long")
    raise ValueError("truncated varint")

def g(d:bytes,p:int):
    n,p=r(d,p); e=p+n
    if e>len(d):raise ValueError("truncated field")
    return d[p:e],e

def zz(n:int)->int:return n<<1 if n>=0 else ((-n<<1)-1)
def uzz(n:int)->int:return n>>1 if not n&1 else -((n>>1)+1)

def tokens(d:bytes):
    out=[]; p=0
    for m in _TOKEN.finditer(d):
        if m.start()!=p:raise ValueError("invalid JSON lexical stream")
        out.append((m.group(0), d[p:m.start()]))
        p=m.end()
    if p!=len(d):raise ValueError("invalid JSON lexical stream")
    # Recompute whitespace before each token without relying on the zero slice
    # above; the lexer stores it explicitly for exact reconstruction.
    out=[]; p=0
    for m in _TOKEN.finditer(d):
        out.append((d[p:m.start()],m.group(0))); p=m.end()
    return out,d[p:]

def encode(data:bytes)->bytes:
    toks,tail=tokens(data)
    strings=Counter(t for _,t in toks if t[:1]==b'"')
    dictionary=sorted((s for s,n in strings.items() if n>=2),key=lambda s:(-strings[s]*len(s),s))
    sid={s:i for i,s in enumerate(dictionary)}
    ints=[]; stream=bytearray()
    for ws,t in toks:
        stream += u(len(ws))+ws
        if t[:1] in b"{}[],:":
            stream.append(T_PUNCT); stream += u(len(t))+t
        elif t[:1]==b'"':
            if t in sid: stream += bytes([T_DICT])+u(sid[t])
            else: stream += bytes([T_STR])+u(len(t))+t
        elif _INT.fullmatch(t):
            stream.append(T_INT); stream += u(len(ints)); ints.append(int(t))
        else:
            stream += bytes([T_RAW])+u(len(t))+t
    # Delta-code the integer stream independently. Store a mode bit per value:
    # absolute is retained when Delta+ZigZag would be larger.
    nums=bytearray(); prev=0
    for x in ints:
        raw=u(zz(x)); delta=u(zz(x-prev))
        if len(delta)<len(raw): nums+=b'\x01'+delta
        else: nums+=b'\x00'+raw
        prev=x
    out=bytearray(MAGIC+bytes([VERSION])+u(len(data)))
    out+=u(len(dictionary))
    for s in dictionary: out+=u(len(s))+s
    out+=u(len(ints))+u(len(nums))+nums
    out+=u(len(stream))+stream+u(len(tail))+tail
    return bytes(out)

def decode(blob:bytes)->bytes:
    if len(blob)<6 or blob[:5]!=MAGIC or blob[5]!=VERSION:raise ValueError("invalid HJSON")
    raw,p=r(blob,6); nd,p=r(blob,p); dictionary=[]
    for _ in range(nd):s,p=g(blob,p);dictionary.append(s)
    ni,p=r(blob,p); nn,p=r(blob,p); end=p+nn
    if end>len(blob):raise ValueError("truncated number stream")
    nums=[]; q=p; prev=0
    while q<end:
        mode=blob[q];q+=1; z,q=r(blob,q)
        prev += uzz(z) if mode else 0
        if not mode: prev=uzz(z)
        nums.append(prev)
    if len(nums)!=ni or q!=end:raise ValueError("bad number stream")
    slen,p=r(blob,end); stream_end=p+slen
    if stream_end>len(blob):raise ValueError("truncated token stream")
    out=bytearray(); q=p; ii=0
    while q<stream_end:
        ws,q=g(blob,q); out+=ws
        tag=blob[q];q+=1
        if tag==T_PUNCT or tag==T_STR or tag==T_RAW:
            x,q=g(blob,q);out+=x
        elif tag==T_DICT:
            i,q=r(blob,q)
            if i>=len(dictionary):raise ValueError("bad dictionary ref")
            out+=dictionary[i]
        elif tag==T_INT:
            i,q=r(blob,q)
            if i>=len(nums):raise ValueError("bad integer ref")
            out+=str(nums[i]).encode("ascii")
            ii+=1
        else:raise ValueError("bad token tag")
    tail,p=g(blob,stream_end);out+=tail
    if p!=len(blob) or len(out)!=raw:raise ValueError("HJSON length mismatch")
    return bytes(out)
