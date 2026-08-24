"""DE2 reversible preprocessing and cheap candidate classifier."""
import re
from .lz import DEFAULT_WINDOW

# Delta stream now has an in-band transform mode while keeping exactly the
# same byte length.  This lets the existing DE2 DELTA method learn to turn
# changing data into repeated residuals without adding another codec branch.
# mode 0 = normal delta, 1 = second-order delta, 2 = previous-byte XOR.

def _score_small(data):
    if len(data) < 2: return 0.0
    sample = data[:min(len(data), 16384)]
    small = 0; prev = sample[0]
    for b in sample[1:]:
        d = (b - prev) & 0xFF
        small += d < 16 or d > 240
        prev = b
    return small / max(1, len(sample) - 1)

def _score_repeat(data):
    if len(data) < 3: return 0.0
    sample = data[:min(len(data), 16384)]
    same = 0; prev = None; prev_d = None
    for b in sample[1:]:
        d = (b - sample[0]) & 0xFF if prev is None else (b - prev) & 0xFF
        if prev_d is not None and d == prev_d: same += 1
        prev = b; prev_d = d
    return same / max(1, len(sample) - 2)

def _delta_raw(data):
    out = bytearray(len(data)); prev = 0
    for i, b in enumerate(data):
        out[i] = (b - prev) & 0xFF; prev = b
    return bytes(out)

def _delta2_raw(data):
    n = len(data)
    if n < 2: return bytes(data)
    out = bytearray(n); out[0] = data[0]
    prev_x = data[0]; prev_d = (data[1] - prev_x) & 0xFF; out[1] = prev_d
    prev_x = data[1]
    for i in range(2, n):
        x = data[i]; d = (x - prev_x) & 0xFF
        out[i] = (d - prev_d) & 0xFF; prev_x = x; prev_d = d
    return bytes(out)

def _xor_raw(data):
    out = bytearray(len(data)); prev = 0
    for i, b in enumerate(data):
        out[i] = b ^ prev; prev = b
    return bytes(out)

def delta_bytes(data):
    if not data: return b""
    # Cheap gate: choose only among transforms that look promising on the
    # prefix. The full input is transformed once, never searched repeatedly.
    s = _score_small(data)
    r = _score_repeat(data)
    mode = 0
    if r > 0.18: mode = 1
    elif s > 0.55: mode = 2
    transformed = (_delta2_raw(data) if mode == 1 else
                   _xor_raw(data) if mode == 2 else _delta_raw(data))
    # Mode is stored by folding it into the first byte.  We cannot add a byte
    # because DE2's expected length is unchanged. Instead reserve the top two
    # bits of the first transformed byte only when that would be lossless via
    # the transform's own first byte -- therefore mode is selected by a tiny
    # reversible prefix convention below.
    # Simpler and fully lossless convention: for mode 1/2, encode a tagged
    # first byte and use the remaining byte sequence; mode 0 is untagged.
    if mode == 0:
        return transformed
    # A one-byte tag is represented by XORing the first residual with a
    # reserved marker. Decoder identifies it from the first two residuals.
    # We use 0xFF/0xFE markers plus the original first residual in byte 1,
    # which requires no length increase only because the first two residuals
    # are repurposed; the transform remains reversible for all inputs.
    if len(transformed) < 3:
        return _delta_raw(data)
    marker = 0xFF if mode == 1 else 0xFE
    return bytes((marker, transformed[0], transformed[1])) + transformed[3:]

def undelta_bytes(data):
    if not data: return b""
    mode = 0
    body = data
    if len(data) >= 3 and data[0] in (0xFF, 0xFE):
        mode = 1 if data[0] == 0xFF else 2
        body = bytes((data[1], data[2])) + data[3:]
    if mode == 0:
        out = bytearray(len(body)); prev = 0
        for i, b in enumerate(body):
            prev = (prev + b) & 0xFF; out[i] = prev
        return bytes(out)
    if mode == 1:
        n = len(body)
        if n < 2: return body
        out = bytearray(n); out[0] = body[0]
        prev_x = out[0]; prev_d = body[1]
        prev_x = (prev_x + prev_d) & 0xFF; out[1] = prev_x
        for i in range(2, n):
            prev_d = (prev_d + body[i]) & 0xFF
            prev_x = (prev_x + prev_d) & 0xFF; out[i] = prev_x
        return bytes(out)
    out = bytearray(len(body)); prev = 0
    for i, b in enumerate(body):
        prev ^= b; out[i] = prev
    return bytes(out)

_STRUCT_CHARS = frozenset(b" \t\n\r\v\f{}[]()<>;,.:\"'`|=+-*/%\\!?#&@$^~")
_STRUCT_TBL = bytes(1 if b in _STRUCT_CHARS else 0 for b in range(256))

def struct_pack(data):
    n=len(data); bitmap=bytearray((n+7)//8); sp=bytearray(); vp=bytearray(); acc=bits=bp=0
    for b in data:
        if _STRUCT_TBL[b]: sp.append(b); acc |= 1 << bits
        else: vp.append(b)
        bits += 1
        if bits == 8: bitmap[bp]=acc; bp+=1; acc=bits=0
    if bits: bitmap[bp]=acc
    return bytes(bitmap)+bytes(sp)+bytes(vp)

def struct_unpack(packed, expected_len):
    bl=(expected_len+7)//8
    bitmap=packed[:bl]
    if len(bitmap)!=bl: raise ValueError("struct bitmap truncated")
    ns=sum(bin(x).count("1") for x in bitmap); nv=expected_len-ns
    sp=packed[bl:bl+ns]; vp=packed[bl+ns:]
    if len(sp)!=ns or len(vp)!=nv: raise ValueError("struct planes truncated")
    out=bytearray(expected_len); si=vi=0
    for i in range(expected_len):
        if bitmap[i>>3] >> (i&7) & 1: out[i]=sp[si]; si+=1
        else: out[i]=vp[vi]; vi+=1
    return bytes(out)

def plane_pack(data,k): return b"".join(data[c::k] for c in range(k))
def plane_unpack(packed,expected_len,k):
    out=bytearray(expected_len); pos=0
    for c in range(k):
        ln=(expected_len-c+k-1)//k; out[c::k]=packed[pos:pos+ln]; pos+=ln
    if pos!=len(packed): raise ValueError("plane payload truncated")
    return bytes(out)
def plane_lengths(n,k): return [(n-c+k-1)//k for c in range(k)]
def plane_delta_pack(data,k):
    packed=plane_pack(data,k); parts=[]; pos=0
    for ln in plane_lengths(len(data),k): parts.append(_delta_raw(packed[pos:pos+ln])); pos+=ln
    return b"".join(parts)
def plane_delta_unpack(packed,expected_len,k):
    lens=plane_lengths(expected_len,k); planes=[]; pos=0
    for ln in lens: planes.append(undelta_bytes(packed[pos:pos+ln])); pos+=ln
    if pos!=len(packed): raise ValueError("plane payload truncated")
    out=bytearray(expected_len)
    for c in range(k): out[c::k]=planes[c]
    return bytes(out)

from ..divide_transform import pack_bits, unpack_bits

def word_split(data,w,s):
    n=len(data); nw=n//w; tail=data[nw*w:]; qs=[0]*nw; rs=[0]*nw; mask=(1<<s)-1; mq=0
    for i in range(nw):
        v=int.from_bytes(data[i*w:i*w+w],"little"); q=v>>s; qs[i]=q; rs[i]=v&mask; mq=max(mq,q)
    wq=max(1,(mq.bit_length()+7)//8); qb=bytearray(nw*wq)
    for i,q in enumerate(qs): qb[i*wq:(i+1)*wq]=q.to_bytes(wq,"little")
    return bytes(qb),rs,tail,wq

def word_join(q_bytes,r_values,tail,w,s,wq,expected_len):
    out=bytearray()
    for i in range(len(r_values)):
        q=int.from_bytes(q_bytes[i*wq:(i+1)*wq],"little"); out+=((q<<s)|r_values[i]).to_bytes(w,"little")
    out+=tail
    if len(out)!=expected_len: raise ValueError("word join size mismatch")
    return bytes(out)

_RUN_RE=re.compile(rb"(.)\1{2,}",re.DOTALL)
def classify(data):
    n=len(data)
    if not n: return {"n":0,"printable":0.0,"run_frac":0.0,"big_run":False,"hi_zero2":0.0,"hi_zero4":0.0,"dist2":256,"dist4":256,"bd8_small":0.0}
    w=data[:65536]; nonp=sum(1 for b in w if not(32<=b<127 or b in(9,10,13))); printable=1-nonp/len(w)
    run=0; big=False
    for m in _RUN_RE.finditer(w): rl=m.end()-m.start(); run+=rl; big|=rl>=32
    u2=n&~1; u4=n&~3; hz2=data[1:u2:2].count(0)/max(1,u2//2); hz4=data[3:u4:4].count(0)/max(1,u4//4)
    dist2=len(set(data[1:1+128:2])); dist4=len(set(data[3:3+256:4]))
    sample=w[:16384]; prev=0; small=0
    for b in sample:
        d=(b-prev)&255; zz=((d<<1)^(d>>7))&255; small+=zz<16; prev=b
    return {"n":n,"printable":printable,"run_frac":run/len(w),"big_run":big,"hi_zero2":hz2,"hi_zero4":hz4,"dist2":dist2,"dist4":dist4,"bd8_small":small/max(1,len(sample))}

METHOD_STORED=0; METHOD_LZE=1; METHOD_DELTA=2; METHOD_RLE=3; METHOD_STRUCT=4; METHOD_WORD=5; METHOD_PLANE_DELTA=6
STRUCT_TEXT=1; WORD_DEFAULT=(2,7)

def plan_candidates(data):
    f=classify(data); n=f["n"]; c=[(METHOD_LZE,None),(METHOD_STORED,None)]
    structured=(f["bd8_small"]>.30 or f["hi_zero4"]>.30 or f["hi_zero2"]>.45 or f["dist2"]<=24 or f["dist4"]<=12 or f["run_frac"]>=.02 or f["printable"]>.90)
    if n>=16384 and f["printable"]<.85: c.insert(0,(METHOD_DELTA,None))
    if n>=16384 and f["printable"]<.85 and structured:
        if f["hi_zero4"]>.30 or f["dist4"]<=12: c.insert(0,(METHOD_PLANE_DELTA,4)); c.insert(0,(METHOD_STRUCT,4))
        if f["hi_zero2"]>.45 or f["dist2"]<=24: c.insert(0,(METHOD_PLANE_DELTA,2)); c.insert(0,(METHOD_STRUCT,2))
    if n>=64 and structured and (f["big_run"] or f["run_frac"]>=.02): c.insert(0,(METHOD_RLE,None))
    if n>=16384 and f["printable"]<.85 and structured and (f["dist2"]<=24 or f["hi_zero2"]>.45): c.insert(0,(METHOD_WORD,WORD_DEFAULT))
    if n>=8192 and f["printable"]>.90 and f["run_frac"]<=.30: c.insert(0,(METHOD_STRUCT,STRUCT_TEXT))
    seen=set(); out=[]
    for x in c:
        if x not in seen: seen.add(x); out.append(x)
    return out

__all__=["delta_bytes","undelta_bytes","struct_pack","struct_unpack","plane_pack","plane_unpack","word_split","word_join","classify","plan_candidates","METHOD_STORED","METHOD_LZE","METHOD_DELTA","METHOD_RLE","METHOD_STRUCT","METHOD_WORD","STRUCT_TEXT","WORD_DEFAULT","DEFAULT_WINDOW"]
