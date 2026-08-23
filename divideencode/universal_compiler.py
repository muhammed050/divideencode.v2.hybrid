"""Universal Binary IR compiler for DE2."""
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
import math
import struct
from .universal_ir import Kind, transform, inverse

IR_MAGIC = b"UBIR"
IR_VERSION = 2
_BITPLANE_MAGIC = b"BP2\x00"

class Op(IntEnum):
    RAW=0; DELTA8=1; XOR8=2; NIBBLE=3; BITPLANE=4; TRANSPOSE4=5; TRANSPOSE8=6
    STRIDE2=7; STRIDE4=8; STRIDE8=9; DELTA16=10; DELTA32=11; DELTA64=12
    XOR16=13; XOR32=14; XOR64=15; SWAP16=16; SWAP32=17; SWAP64=18; RLE=19
    BYTE_LANES2=20; BYTE_LANES4=21; BYTE_LANES8=22

@dataclass(frozen=True)
class Instruction: op: Op
@dataclass(frozen=True)
class Pipeline:
    instructions: tuple[Instruction,...]
    @property
    def name(self): return "RAW" if not self.instructions else "+".join(i.op.name for i in self.instructions)
@dataclass(frozen=True)
class CompiledIR:
    payload: bytes; pipeline: Pipeline; original_size: int
class IRFormatError(ValueError): pass

def _word_transform(src,width,op,decode=False):
    src=bytes(src); out=bytearray(src); full=len(src)-len(src)%width; mask=(1<<(width*8))-1; prev=0
    for off in range(0,full,width):
        value=int.from_bytes(src[off:off+width],"little"); original=value
        if op=="delta":
            if decode: value=(prev+value)&mask; prev=value
            else: value=(value-prev)&mask; prev=original
        elif op=="xor":
            value ^= prev; prev=value if decode else original
        elif op=="swap": value=int.from_bytes(value.to_bytes(width,"little")[::-1],"little")
        else: raise IRFormatError(op)
        out[off:off+width]=value.to_bytes(width,"little")
    return bytes(out)

def _rle_encode(src):
    if not src:return b""
    out=bytearray(); i=0
    while i<len(src):
        b=src[i]; j=i+1
        while j<len(src) and src[j]==b and j-i<0xFFFFFFFF:j+=1
        out.append(b); out+=struct.pack("<I",j-i); i=j
    return bytes(out)

def _rle_decode(src):
    if len(src)%5: raise IRFormatError("invalid RLE IR")
    out=bytearray()
    for i in range(0,len(src),5):
        b=src[i]; count=struct.unpack_from("<I",src,i+1)[0]
        if not count: raise IRFormatError("zero RLE run")
        out.extend(bytes((b,))*count)
    return bytes(out)

def _lanes_encode(src,width): return b"".join(src[i::width] for i in range(width))
def _lanes_decode(src,width,original_size=None):
    # BYTE_LANES is strictly length preserving.  It must reconstruct the
    # length of the payload at this stage, never the final source length:
    # variable-length transforms may exist before/after it in a pipeline.
    n=len(src) if original_size is None else original_size
    if n<0 or len(src)!=n: raise IRFormatError("lane payload size mismatch")
    lengths=[(n+width-1-i)//width for i in range(width)]
    groups=[]; pos=0
    for length in lengths: groups.append(src[pos:pos+length]); pos+=length
    if pos!=len(src): raise IRFormatError("lane payload size mismatch")
    out=bytearray(n); offsets=[0]*width
    for i in range(n):
        lane=i%width; out[i]=groups[lane][offsets[lane]]; offsets[lane]+=1
    return bytes(out)

def _bitplane_encode_compiler(src):
    """Encode BITPLANE with an exact source-size header."""
    return _BITPLANE_MAGIC + struct.pack("<Q", len(src)) + transform(src, Kind.BITPLANE)

def _bitplane_decode_compiler(src):
    if len(src)<12 or src[:4]!=_BITPLANE_MAGIC:
        raise IRFormatError("invalid BITPLANE IR header")
    original_size=struct.unpack_from("<Q",src,4)[0]
    body=src[12:]
    return inverse(body, Kind.BITPLANE, original_size=original_size)

def _apply_one(src,op,decode=False,original_size=None):
    if op==Op.RAW:return bytes(src)
    if op==Op.BITPLANE:
        return _bitplane_decode_compiler(bytes(src)) if decode else _bitplane_encode_compiler(bytes(src))
    if op in (Op.DELTA8,Op.XOR8,Op.NIBBLE,Op.TRANSPOSE4,Op.TRANSPOSE8,Op.STRIDE2,Op.STRIDE4,Op.STRIDE8):
        kind=Kind(op.value)
        if decode and op==Op.NIBBLE:
            # NIBBLE is exactly 2x on encode, so its own payload determines
            # the size of the stage being decoded. Do not use the pipeline's
            # final original_size here.
            return inverse(src,kind,original_size=len(src)//2)
        if decode and op in (Op.STRIDE2,Op.STRIDE4,Op.STRIDE8):
            return inverse(src,kind,original_size=len(src))
        # DELTA/XOR/TRANSPOSE are length-preserving. Passing the final
        # pipeline size here used to truncate composed pipelines such as
        # NIBBLE -> DELTA8. Let inverse preserve the current stage length.
        return inverse(src,kind) if decode else transform(src,kind)
    if op in (Op.DELTA16,Op.DELTA32,Op.DELTA64,Op.XOR16,Op.XOR32,Op.XOR64,Op.SWAP16,Op.SWAP32,Op.SWAP64):
        name=op.name; width=int(name[-2:])//8; action="delta" if name.startswith("DELTA") else "xor" if name.startswith("XOR") else "swap"
        return _word_transform(src,width,action,decode)
    if op==Op.RLE:return _rle_decode(src) if decode else _rle_encode(src)
    if op in (Op.BYTE_LANES2,Op.BYTE_LANES4,Op.BYTE_LANES8):
        width={Op.BYTE_LANES2:2,Op.BYTE_LANES4:4,Op.BYTE_LANES8:8}[op]
        return _lanes_decode(src,width) if decode else _lanes_encode(src,width)
    raise IRFormatError(f"unknown IR op {op}")

def encode_pipeline(src,pipeline):
    data=bytes(src)
    for instruction in pipeline.instructions:data=_apply_one(data,instruction.op)
    return data

def decode_pipeline(payload,pipeline,original_size):
    data=bytes(payload)
    for instruction in reversed(pipeline.instructions):
        data=_apply_one(data,instruction.op,decode=True,original_size=original_size)
    if len(data)!=original_size:raise IRFormatError("decoded IR size mismatch")
    return data

def serialize(compiled):
    if len(compiled.pipeline.instructions)>255:raise IRFormatError("pipeline too long")
    header=struct.pack("<4sBBQ",IR_MAGIC,IR_VERSION,len(compiled.pipeline.instructions),compiled.original_size)
    return header+bytes(int(i.op) for i in compiled.pipeline.instructions)+compiled.payload

def deserialize(blob):
    if len(blob)<14:raise IRFormatError("truncated universal IR")
    magic,version,count,original_size=struct.unpack_from("<4sBBQ",blob)
    if magic!=IR_MAGIC or version!=IR_VERSION:raise IRFormatError("not universal IR v2")
    pos=14
    if len(blob)<pos+count:raise IRFormatError("truncated universal IR instructions")
    try: instructions=tuple(Instruction(Op(v)) for v in blob[pos:pos+count])
    except ValueError as exc:raise IRFormatError("unknown universal IR opcode") from exc
    return CompiledIR(bytes(blob[pos+count:]),Pipeline(instructions),original_size)

def verify_pipeline(src,pipeline):
    restored=decode_pipeline(encode_pipeline(src,pipeline),pipeline,len(src))
    if restored!=bytes(src):raise AssertionError(f"universal IR roundtrip failed: {pipeline.name}")

def _entropy(data):
    if not data:return 0.0
    counts=[0]*256
    for b in data:counts[b]+=1
    n=len(data); return -sum((c/n)*math.log2(c/n) for c in counts if c)
def _zero_ratio(data):return data.count(0)/len(data) if data else 0.0
def _repeat_ratio(data):return sum(a==b for a,b in zip(data,data[1:]))/(len(data)-1) if len(data)>=2 else 0.0

def _candidate_pipelines(data):
    sample=bytes(data[:min(len(data),256*1024)])
    if not sample:return [Pipeline(())]
    candidates=[Pipeline(())]+[Pipeline((Instruction(op),)) for op in Op if op!=Op.RAW]
    preferred=[Op.DELTA8,Op.XOR8,Op.DELTA16,Op.DELTA32,Op.XOR16,Op.XOR32,Op.BYTE_LANES2,Op.BYTE_LANES4,Op.BYTE_LANES8,Op.STRIDE2,Op.STRIDE4,Op.STRIDE8]
    candidates.extend(Pipeline((Instruction(a),Instruction(b))) for a in preferred for b in preferred if a!=b)
    for width in (16,32,64):
        for action in ("DELTA","XOR"):
            word=Op[f"{action}{width}"]
            for lane in (Op.BYTE_LANES2,Op.BYTE_LANES4,Op.BYTE_LANES8):candidates.append(Pipeline((Instruction(word),Instruction(lane))))
    if _repeat_ratio(sample)>=.04 or _zero_ratio(sample)>=.08:
        candidates += [Pipeline((Instruction(Op.RLE),)),Pipeline((Instruction(Op.RLE),Instruction(Op.BYTE_LANES4)))]
    return candidates

def plan(data,max_candidates=32):
    src=bytes(data); sample=src[:min(len(src),64*1024)]; scored=[]
    for pipeline in _candidate_pipelines(src):
        try: transformed=encode_pipeline(sample,pipeline)
        except (ValueError,IRFormatError):continue
        score=_entropy(transformed)+.5*(1-_zero_ratio(transformed))+.15*len(transformed)/max(1,len(sample)); scored.append((score,pipeline))
    scored.sort(key=lambda x:(x[0],x[1].name)); result=[]; seen=set()
    for _,pipeline in scored:
        if pipeline.name in seen:continue
        seen.add(pipeline.name); result.append(pipeline)
        if len(result)>=max_candidates:break
    return result or [Pipeline(())]

def compile_ir(data,pipeline):
    src=bytes(data); payload=encode_pipeline(src,pipeline); verify_pipeline(src,pipeline); return CompiledIR(payload,pipeline,len(src))
