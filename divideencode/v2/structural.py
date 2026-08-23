"""Structural transformation engine for Universal Divide.

Lossless, conservative transforms that turn structured byte streams into
simpler representations before compression. The adaptive path may explore
compositions because a representation that is neutral by itself can become
highly compressible after another transform.
"""
from __future__ import annotations
from dataclasses import dataclass
import struct

@dataclass(frozen=True)
class Candidate:
    kind: str
    payload: bytes
    meta: bytes
    score: int

@dataclass(frozen=True)
class Decision:
    kind: str
    blob: bytes
    structural_size: int
    downstream_size: int | None

MAGIC = b"SD1"
_KIND_TO_ID = {"delta": 1, "rle": 2, "dict": 3, "plane": 4, "pipeline": 5}
_ID_TO_KIND = {v: k for k, v in _KIND_TO_ID.items()}

def _varint(n: int) -> bytes:
    if n < 0: raise ValueError("negative structural varint")
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7f) | 0x80); n >>= 7
    out.append(n)
    return bytes(out)

def _read_varint(buf: bytes, p: int):
    n = 0; shift = 0
    while True:
        if p >= len(buf) or shift > 63: raise ValueError("invalid structural varint")
        b = buf[p]; p += 1; n |= (b & 0x7f) << shift
        if not (b & 0x80): return n, p
        shift += 7

def _signed_delta(values):
    if not values: return []
    return [values[0]] + [values[i] - values[i - 1] for i in range(1, len(values))]

def _undelta(values):
    out = []; total = 0
    for x in values:
        total += x; out.append(total)
    return out

def _encode_svarint(x: int) -> bytes:
    return _varint((x << 1) ^ (x >> 63))

def _decode_svarints(buf: bytes, count: int):
    out = []; p = 0
    for _ in range(count):
        u, p = _read_varint(buf, p); out.append((u >> 1) ^ -(u & 1))
    if p != len(buf): raise ValueError("trailing structural data")
    return out

def _numeric_sequence(data: bytes):
    for width, fmt in ((1,"B"),(2,"<H"),(4,"<I"),(8,"<Q"),(2,">H"),(4,">I"),(8,">Q")):
        if len(data) < width * 4 or len(data) % width: continue
        try: vals = [x[0] for x in struct.iter_unpack(fmt, data)]
        except struct.error: continue
        if len(vals) >= 4: yield width, fmt, vals

def _delta_candidate(data: bytes):
    best = None
    for width, fmt, vals in _numeric_sequence(data):
        packed = b"".join(_encode_svarint(x) for x in _signed_delta(vals))
        fb = fmt.encode("ascii")
        meta = bytes((width, len(fb))) + fb + _varint(len(vals))
        total = len(MAGIC)+1+len(_varint(len(meta)))+len(meta)+len(packed)
        if total < len(data):
            c = Candidate("delta", packed, meta, total)
            if best is None or c.score < best.score: best = c
    return best

def _rle_candidate(data: bytes):
    if not data: return None
    runs = []; i = 0
    while i < len(data):
        j = i + 1
        while j < len(data) and data[j] == data[i] and j-i < (1<<32): j += 1
        runs.append((data[i], j-i)); i = j
    packed = bytearray()
    for b,n in runs: packed.append(b); packed.extend(_varint(n))
    total = len(MAGIC)+1+len(packed)
    if total >= len(data): return None
    return Candidate("rle", bytes(packed), b"", total)

def _dictionary_candidate(data: bytes):
    best = None
    for size in (2,3,4,5,6,8,12,16,24,32):
        if len(data) < size*8 or len(data) % size: continue
        chunks = [data[i:i+size] for i in range(0,len(data),size)]
        uniq = {}; dictionary=[]; ids=bytearray()
        for c in chunks:
            idx=uniq.get(c)
            if idx is None:
                idx=len(dictionary)
                if idx >= 256: break
                uniq[c]=idx; dictionary.append(c)
            ids.append(idx)
        else:
            packed=bytearray(_varint(size)); packed.extend(_varint(len(dictionary)))
            for c in dictionary: packed.extend(c)
            packed.extend(ids); total=len(MAGIC)+1+len(packed)
            if total < len(data):
                c=Candidate("dict",bytes(packed),b"",total)
                if best is None or c.score < best.score: best=c
    return best

def _plane_candidate(data: bytes):
    """Transpose fixed-width records; adaptive scoring decides if it helps."""
    best=None
    for width in (2,4,8,16):
        if len(data) < width*16 or len(data)%width: continue
        count=len(data)//width; planes=bytearray(len(data)); out=0
        for bi in range(width):
            for record in range(count):
                planes[out]=data[record*width+bi]; out+=1
        meta=bytes((width,))+_varint(count); payload=bytes(planes)
        total=len(MAGIC)+1+len(_varint(len(meta)))+len(meta)+len(payload)
        c=Candidate("plane",payload,meta,total)
        if best is None or c.score < best.score: best=c
    return best

def _candidate_blob(c: Candidate) -> bytes:
    return MAGIC+bytes((_KIND_TO_ID[c.kind],))+_varint(len(c.meta))+c.meta+c.payload

def _pipeline_candidate(first: Candidate, second: Candidate):
    meta=(b"\x02"+bytes((_KIND_TO_ID[first.kind],))+_varint(len(first.meta))+first.meta+
          bytes((_KIND_TO_ID[second.kind],))+_varint(len(second.meta))+second.meta)
    total=len(MAGIC)+1+len(_varint(len(meta)))+len(meta)+len(second.payload)
    return Candidate("pipeline",second.payload,meta,total)

def analyze(data: bytes):
    """Bounded depth-2 structural search; no combinatorial explosion."""
    base=[]
    for fn in (_delta_candidate,_rle_candidate,_dictionary_candidate,_plane_candidate):
        c=fn(data)
        if c is not None: base.append(c)
    candidates=list(base)
    for first in base:
        transformed=first.payload
        for fn in (_rle_candidate,_dictionary_candidate,_delta_candidate):
            second=fn(transformed)
            if second is not None: candidates.append(_pipeline_candidate(first,second))
    unique={}
    for c in candidates:
        key=(c.kind,c.meta,c.payload)
        if key not in unique or c.score < unique[key].score: unique[key]=c
    return sorted(unique.values(),key=lambda x:x.score)

def _raw_blob(data: bytes) -> bytes:
    return MAGIC+b"\x00"+data

def transform(data: bytes) -> bytes:
    candidates=[c for c in analyze(data) if c.score < len(data)]
    return _raw_blob(data) if not candidates else _candidate_blob(candidates[0])

def adaptive_transform(data: bytes, scorer=None) -> Decision:
    candidates=analyze(data); raw_blob=_raw_blob(data)
    if scorer is None:
        blob=transform(data); kind="raw" if blob[3]==0 else _ID_TO_KIND.get(blob[3])
        if kind is None: raise ValueError("unknown structural kind")
        return Decision(kind,blob,len(blob),None)
    options=[("raw",raw_blob)]+[(c.kind,_candidate_blob(c)) for c in candidates]
    best_kind,best_blob=options[0]; best_cost=scorer(best_blob)
    for kind,blob in options[1:]:
        cost=scorer(blob)
        if cost < best_cost: best_kind,best_blob,best_cost=kind,blob,cost
    return Decision(best_kind,best_blob,len(best_blob),best_cost)

def _inverse_blob(kind: int, meta: bytes, payload: bytes) -> bytes:
    if kind==1:
        if len(meta)<2: raise ValueError("invalid delta metadata")
        width=meta[0]; fmt_len=meta[1]; a=2; b=a+fmt_len
        if b>len(meta): raise ValueError("truncated delta format metadata")
        fmt=meta[a:b].decode("ascii"); count,q=_read_varint(meta,b)
        if q!=len(meta): raise ValueError("trailing delta metadata")
        if width not in (1,2,4,8): raise ValueError("invalid delta width")
        vals=_undelta(_decode_svarints(payload,count))
        if width==1:
            if any(v<0 or v>255 for v in vals): raise ValueError("delta byte out of range")
            return bytes(vals)
        try: return b"".join(struct.pack(fmt,v) for v in vals)
        except struct.error as exc: raise ValueError("invalid delta value") from exc
    if kind==2:
        out=bytearray(); q=0
        while q<len(payload):
            b=payload[q]; q+=1; n,q=_read_varint(payload,q); out.extend(bytes((b,))*n)
        return bytes(out)
    if kind==3:
        size,q=_read_varint(payload,0); n,q=_read_varint(payload,q)
        if n>256: raise ValueError("dictionary too large")
        dictionary=[]
        for _ in range(n):
            end=q+size
            if end>len(payload): raise ValueError("truncated dictionary")
            dictionary.append(payload[q:end]); q=end
        ids=payload[q:]
        if any(i>=n for i in ids): raise ValueError("invalid dictionary id")
        return b"".join(dictionary[i] for i in ids)
    if kind==4:
        if not meta: raise ValueError("invalid plane metadata")
        width=meta[0]
        if width not in (2,4,8,16): raise ValueError("invalid plane width")
        count,q=_read_varint(meta,1)
        if q!=len(meta) or count*width!=len(payload): raise ValueError("invalid plane payload")
        out=bytearray(len(payload)); p=0
        for bi in range(width):
            for record in range(count): out[record*width+bi]=payload[p]; p+=1
        return bytes(out)
    raise ValueError("unknown structural stage")

def inverse(blob: bytes) -> bytes:
    if len(blob)<4 or blob[:3]!=MAGIC: raise ValueError("invalid structural stream")
    kind=blob[3]
    if kind==0: return blob[4:]
    mlen,p=_read_varint(blob,4); end=p+mlen
    if end>len(blob): raise ValueError("truncated structural metadata")
    meta=blob[p:end]; payload=blob[end:]
    if kind!=5: return _inverse_blob(kind,meta,payload)
    q=0
    if not meta or meta[q]!=2: raise ValueError("unsupported pipeline depth")
    q+=1; stages=[]
    for _ in range(2):
        if q>=len(meta): raise ValueError("truncated pipeline metadata")
        sk=meta[q]; q+=1; sl,q=_read_varint(meta,q); e=q+sl
        if e>len(meta): raise ValueError("truncated pipeline stage")
        stages.append((sk,meta[q:e])); q=e
    if q!=len(meta): raise ValueError("trailing pipeline metadata")
    current=_inverse_blob(stages[1][0],stages[1][1],payload)
    return _inverse_blob(stages[0][0],stages[0][1],current)
