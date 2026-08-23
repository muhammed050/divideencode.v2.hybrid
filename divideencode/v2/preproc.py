"""DivideEncode V2 -- reversible preprocessing transforms + classifier (M3).

Three preprocessing pipelines feeding the DE2 LZE stage:
  DELTA   mod-256 sequential byte difference
  RLE     V1-style run-length blob
  STRUCT  character-class / stride plane split
"""
import re
from .lz import DEFAULT_WINDOW


def delta_bytes(data):
    out = bytearray(len(data)); prev = 0
    for i, b in enumerate(data):
        out[i] = (b - prev) & 0xFF; prev = b
    return bytes(out)


def undelta_bytes(data):
    out = bytearray(len(data)); prev = 0
    for i, b in enumerate(data):
        prev = (prev + b) & 0xFF; out[i] = prev
    return bytes(out)

_STRUCT_CHARS = frozenset(b" \t\n\r\v\f{}[]()<>;,.:\"'`|=+-*/%\\!?#&@$^~")
_STRUCT_TBL = bytes(1 if b in _STRUCT_CHARS else 0 for b in range(256))


def struct_pack(data):
    n=len(data); bitmap=bytearray((n+7)//8); s=bytearray(); v=bytearray(); acc=0; nb=0; bp=0
    for b in data:
        if _STRUCT_TBL[b]: s.append(b); acc |= 1 << nb
        else: v.append(b)
        nb += 1
        if nb == 8: bitmap[bp]=acc; bp += 1; acc=0; nb=0
    if nb: bitmap[bp]=acc
    return bytes(bitmap)+bytes(s)+bytes(v)


def struct_unpack(packed, expected_len):
    bl=(expected_len+7)//8
    if bl>len(packed): raise ValueError("struct bitmap truncated")
    bm=packed[:bl]; ns=sum(x.bit_count() for x in bm); nv=expected_len-ns
    s=packed[bl:bl+ns]; v=packed[bl+ns:]
    if len(s)!=ns or len(v)!=nv: raise ValueError("struct planes truncated")
    out=bytearray(expected_len); si=vi=0
    for i in range(expected_len):
        if (bm[i>>3]>>(i&7))&1: out[i]=s[si]; si+=1
        else: out[i]=v[vi]; vi+=1
    return bytes(out)


def plane_pack(data,k): return b"".join(data[c::k] for c in range(k))

def plane_unpack(packed, expected_len, k):
    out=bytearray(expected_len); pos=0
    for c in range(k):
        ln=(expected_len-c+k-1)//k; out[c::k]=packed[pos:pos+ln]; pos+=ln
    if pos!=len(packed): raise ValueError("plane payload truncated")
    return bytes(out)


def plane_lengths(n,k): return [(n-c+k-1)//k for c in range(k)]

def plane_delta_pack(data,k):
    packed=plane_pack(data,k); parts=[]; pos=0
    for ln in plane_lengths(len(data),k): parts.append(delta_bytes(packed[pos:pos+ln])); pos+=ln
    return b"".join(parts)

def plane_delta_unpack(packed,expected_len,k):
    planes=[]; pos=0
    for ln in plane_lengths(expected_len,k): planes.append(undelta_bytes(packed[pos:pos+ln])); pos+=ln
    if pos!=len(packed): raise ValueError("plane payload truncated")
    out=bytearray(expected_len)
    for c in range(k): out[c::k]=planes[c]
    return bytes(out)

from ..divide_transform import pack_bits, unpack_bits

def word_split(data,w,s):
    n=len(data); nw=n//w; tail=data[nw*w:]; ib=int.from_bytes; mq=0
    # Exact maximum is required: sampled maxima can cause OverflowError.
    for i in range(nw):
        q=ib(data[i*w:i*w+w],"little") >> s
        if q>mq: mq=q
    wq=max(1,(mq.bit_length()+7)//8); qb=bytearray(nw*wq); rs=[]; mask=(1<<s)-1
    for i in range(nw):
        v=ib(data[i*w:i*w+w],"little"); qb[i*wq:(i+1)*wq]=(v>>s).to_bytes(wq,"little"); rs.append(v&mask)
    return bytes(qb),rs,tail,wq

def word_join(q_bytes,r_values,tail,w,s,wq,expected_len):
    out=bytearray(); ib=int.from_bytes
    for i,r in enumerate(r_values):
        q=ib(q_bytes[i*wq:(i+1)*wq],"little"); out+=((q<<s)|r).to_bytes(w,"little")
    out+=tail
    if len(out)!=expected_len: raise ValueError("word join size mismatch")
    return bytes(out)

_RUN_RE=re.compile(rb"(.)\1{2,}",re.DOTALL)

def classify(data):
    n=len(data)
    if not n: return {"n":0,"printable":0.0,"run_frac":0.0,"big_run":False,"hi_zero2":0.0,"hi_zero4":0.0,"dist2":256,"dist4":256,"bd8_small":0.0}
    window=data[:65536]; nonp=sum(not(32<=b<127 or b in (9,10,13)) for b in window); printable=1-nonp/len(window)
    run_bytes=0; big=False
    for m in _RUN_RE.finditer(window):
        rl=m.end()-m.start(); run_bytes+=rl; big |= rl>=32
    usable2=n&~1; usable4=n&~3
    hz2=data[1:usable2:2].count(0)/max(1,usable2//2); hz4=data[3:usable4:4].count(0)/max(1,usable4//4)
    def distinct(start,step): return len(set(data[start:start+64*step:step]))
    dist2=distinct(1,2) if usable2>=2 else 256; dist4=distinct(3,4) if usable4>=4 else 256
    sample=window[:16384]; prev=0; small=0
    for b in sample:
        d=(b-prev)&255; prev=b; zz=((d<<1)^(d>>7))&255; small += zz<16
    return {"n":n,"printable":printable,"run_frac":run_bytes/len(window),"big_run":big,"hi_zero2":hz2,"hi_zero4":hz4,"dist2":dist2,"dist4":dist4,"bd8_small":small/max(1,len(sample))}

METHOD_STORED=0; METHOD_LZE=1; METHOD_DELTA=2; METHOD_RLE=3; METHOD_STRUCT=4; METHOD_WORD=5; METHOD_PLANE_DELTA=6
STRUCT_TEXT=1; WORD_DEFAULT=(2,7)

def plan_candidates(data):
    f=classify(data); n=f["n"]; c=[(METHOD_LZE,None),(METHOD_STORED,None)]
    structured=f["bd8_small"]>0.30 or f["hi_zero4"]>0.30 or f["hi_zero2"]>0.45 or f["dist2"]<=24 or f["dist4"]<=12 or f["run_frac"]>=0.02 or f["printable"]>0.90
    if n>=16384 and f["printable"]<0.85: c.insert(0,(METHOD_DELTA,None))
    if n>=16384 and f["printable"]<0.85 and structured:
        if f["hi_zero4"]>0.30 or f["dist4"]<=12: c.insert(0,(METHOD_PLANE_DELTA,4)); c.insert(0,(METHOD_STRUCT,4))
        if f["hi_zero2"]>0.45 or f["dist2"]<=24: c.insert(0,(METHOD_PLANE_DELTA,2)); c.insert(0,(METHOD_STRUCT,2))
    if n>=64 and structured and (f["big_run"] or f["run_frac"]>=0.02): c.insert(0,(METHOD_RLE,None))
    if n>=16384 and f["printable"]<0.85 and structured and (f["dist2"]<=24 or f["hi_zero2"]>0.45): c.insert(0,(METHOD_WORD,WORD_DEFAULT))
    if n>=8192 and f["printable"]>0.90 and f["run_frac"]<=0.30: c.insert(0,(METHOD_STRUCT,STRUCT_TEXT))
    seen=set(); out=[]
    for x in c:
        if x not in seen: seen.add(x); out.append(x)
    return out

__all__=["delta_bytes","undelta_bytes","struct_pack","struct_unpack","plane_pack","plane_unpack","plane_delta_pack","plane_delta_unpack","word_split","word_join","classify","plan_candidates","METHOD_STORED","METHOD_LZE","METHOD_DELTA","METHOD_RLE","METHOD_STRUCT","METHOD_WORD","METHOD_PLANE_DELTA","STRUCT_TEXT","WORD_DEFAULT","DEFAULT_WINDOW"]
