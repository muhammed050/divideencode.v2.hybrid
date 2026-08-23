"""Universal Binary IR compiler for DE2.

Any input is bytes, then compiled into a reversible Universal Binary IR
program. The IR may grow without limit; only final DE2 size is authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
import struct

from .universal_ir import Kind, transform, inverse

IR_MAGIC = b"UBIR"
IR_VERSION = 2


class Op(IntEnum):
    RAW = 0
    DELTA8 = 1
    XOR8 = 2
    NIBBLE = 3
    BITPLANE = 4
    TRANSPOSE4 = 5
    TRANSPOSE8 = 6
    STRIDE2 = 7
    STRIDE4 = 8
    STRIDE8 = 9
    DELTA16 = 10
    DELTA32 = 11
    DELTA64 = 12
    XOR16 = 13
    XOR32 = 14
    XOR64 = 15
    SWAP16 = 16
    SWAP32 = 17
    SWAP64 = 18
    RLE = 19
    BYTE_LANES2 = 20
    BYTE_LANES4 = 21
    BYTE_LANES8 = 22


@dataclass(frozen=True)
class Instruction:
    op: Op


@dataclass(frozen=True)
class Pipeline:
    instructions: tuple[Instruction, ...]

    @property
    def name(self) -> str:
        return "RAW" if not self.instructions else "+".join(i.op.name for i in self.instructions)


@dataclass(frozen=True)
class CompiledIR:
    payload: bytes
    pipeline: Pipeline
    original_size: int


class IRFormatError(ValueError):
    pass


def _word_transform(src: bytes, width: int, op: str, decode: bool = False) -> bytes:
    src = bytes(src)
    out = bytearray(src)
    full = len(src) - len(src) % width
    mask = (1 << (width * 8)) - 1
    prev = 0
    for off in range(0, full, width):
        value = int.from_bytes(src[off:off + width], "little")
        original = value
        if op == "delta":
            if decode:
                value = (prev + value) & mask
                prev = value
            else:
                value = (value - prev) & mask
                prev = original
        elif op == "xor":
            if decode:
                value ^= prev
                prev = value
            else:
                value ^= prev
                prev = original
        elif op == "swap":
            value = int.from_bytes(value.to_bytes(width, "little")[::-1], "little")
        else:
            raise IRFormatError(op)
        out[off:off + width] = value.to_bytes(width, "little")
    return bytes(out)


def _rle_encode(src: bytes) -> bytes:
    if not src:
        return b""
    out = bytearray()
    i = 0
    while i < len(src):
        b = src[i]
        j = i + 1
        while j < len(src) and src[j] == b and j - i < 0xFFFFFFFF:
            j += 1
        out.append(b)
        out += struct.pack("<I", j - i)
        i = j
    return bytes(out)


def _rle_decode(src: bytes) -> bytes:
    if len(src) % 5:
        raise IRFormatError("invalid RLE IR")
    out = bytearray()
    for i in range(0, len(src), 5):
        b = src[i]
        count = struct.unpack_from("<I", src, i + 1)[0]
        if count == 0:
            raise IRFormatError("zero RLE run")
        out.extend(bytes((b,)) * count)
    return bytes(out)


def _lanes_encode(src: bytes, width: int) -> bytes:
    return b"".join(src[i::width] for i in range(width))


def _lanes_decode(src: bytes, width: int, original_size: int) -> bytes:
    n = original_size
    lengths = [(n + width - 1 - i) // width for i in range(width)]
    groups: list[bytes] = []
    pos = 0
    for length in lengths:
        groups.append(src[pos:pos + length])
        pos += length
    if pos != len(src):
        raise IRFormatError("lane payload size mismatch")
    out = bytearray(n)
    offsets = [0] * width
    for i in range(n):
        lane = i % width
        out[i] = groups[lane][offsets[lane]]
        offsets[lane] += 1
    return bytes(out)


def _apply_one(src: bytes, op: Op, decode: bool = False) -> bytes:
    if op == Op.RAW:
        return bytes(src)
    if op in (Op.DELTA8, Op.XOR8, Op.NIBBLE, Op.BITPLANE, Op.TRANSPOSE4,
              Op.TRANSPOSE8, Op.STRIDE2, Op.STRIDE4, Op.STRIDE8):
        kind = Kind(op.value)
        return inverse(src, kind) if decode else transform(src, kind)
    if op in (Op.DELTA16, Op.DELTA32, Op.DELTA64, Op.XOR16, Op.XOR32, Op.XOR64,
              Op.SWAP16, Op.SWAP32, Op.SWAP64):
        name = op.name
        width = int(name[-2:]) // 8
        action = "delta" if name.startswith("DELTA") else "xor" if name.startswith("XOR") else "swap"
        return _word_transform(src, width, action, decode)
    if op == Op.RLE:
        return _rle_decode(src) if decode else _rle_encode(src)
    if op in (Op.BYTE_LANES2, Op.BYTE_LANES4, Op.BYTE_LANES8):
        width = {Op.BYTE_LANES2: 2, Op.BYTE_LANES4: 4, Op.BYTE_LANES8: 8}[op]
        return _lanes_decode(src, width, len(src)) if decode else _lanes_encode(src, width)
    raise IRFormatError(f"unknown IR op {op}")


def encode_pipeline(src: bytes, pipeline: Pipeline) -> bytes:
    data = bytes(src)
    for instruction in pipeline.instructions:
        data = _apply_one(data, instruction.op)
    return data


def decode_pipeline(payload: bytes, pipeline: Pipeline, original_size: int) -> bytes:
    data = bytes(payload)
    for instruction in reversed(pipeline.instructions):
        data = _apply_one(data, instruction.op, decode=True)
    if len(data) != original_size:
        raise IRFormatError("decoded IR size mismatch")
    return data


def serialize(compiled: CompiledIR) -> bytes:
    if len(compiled.pipeline.instructions) > 255:
        raise IRFormatError("pipeline too long")
    header = struct.pack("<4sBBQ", IR_MAGIC, IR_VERSION,
                         len(compiled.pipeline.instructions), compiled.original_size)
    return header + bytes(int(i.op) for i in compiled.pipeline.instructions) + compiled.payload


def deserialize(blob: bytes) -> CompiledIR:
    if len(blob) < 14:
        raise IRFormatError("truncated universal IR")
    magic, version, count, original_size = struct.unpack_from("<4sBBQ", blob)
    if magic != IR_MAGIC or version != IR_VERSION:
        raise IRFormatError("not universal IR v2")
    pos = 14
    if len(blob) < pos + count:
        raise IRFormatError("truncated universal IR instructions")
    try:
        instructions = tuple(Instruction(Op(v)) for v in blob[pos:pos + count])
    except ValueError as exc:
        raise IRFormatError("unknown universal IR opcode") from exc
    return CompiledIR(bytes(blob[pos + count:]), Pipeline(instructions), original_size)


def verify_pipeline(src: bytes, pipeline: Pipeline) -> None:
    restored = decode_pipeline(encode_pipeline(src, pipeline), pipeline, len(src))
    if restored != bytes(src):
        raise AssertionError(f"universal IR roundtrip failed: {pipeline.name}")


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts if c)


def _zero_ratio(data: bytes) -> float:
    return data.count(0) / len(data) if data else 0.0


def _repeat_ratio(data: bytes) -> float:
    if len(data) < 2:
        return 0.0
    return sum(a == b for a, b in zip(data, data[1:])) / (len(data) - 1)


def _candidate_pipelines(data: bytes) -> list[Pipeline]:
    sample = bytes(data[: min(len(data), 256 * 1024)])
    if not sample:
        return [Pipeline(())]
    candidates: list[Pipeline] = [Pipeline(())]
    for op in Op:
        if op != Op.RAW:
            candidates.append(Pipeline((Instruction(op),)))
    preferred = [Op.DELTA8, Op.XOR8, Op.DELTA16, Op.DELTA32, Op.XOR16,
                 Op.XOR32, Op.BYTE_LANES2, Op.BYTE_LANES4, Op.BYTE_LANES8,
                 Op.STRIDE2, Op.STRIDE4, Op.STRIDE8]
    candidates.extend(Pipeline((Instruction(a), Instruction(b)))
                      for a in preferred for b in preferred if a != b)
    for width in (16, 32, 64):
        delta = Op[f"DELTA{width}"]
        xor = Op[f"XOR{width}"]
        for lane in (Op.BYTE_LANES2, Op.BYTE_LANES4, Op.BYTE_LANES8):
            candidates.append(Pipeline((Instruction(delta), Instruction(lane))))
            candidates.append(Pipeline((Instruction(xor), Instruction(lane))))
    if _repeat_ratio(sample) >= 0.04 or _zero_ratio(sample) >= 0.08:
        candidates.append(Pipeline((Instruction(Op.RLE),)))
        candidates.append(Pipeline((Instruction(Op.RLE), Instruction(Op.BYTE_LANES4))))
    return candidates


def plan(data: bytes, *, max_candidates: int = 32) -> list[Pipeline]:
    """Return complete IR programs for DE2 evaluation.

    The heuristic only limits search. It never declares a compression winner;
    the caller must measure final DE2 output for every selected program.
    """
    src = bytes(data)
    candidates = _candidate_pipelines(src)
    sample = src[: min(len(src), 64 * 1024)]
    scored: list[tuple[float, Pipeline]] = []
    for pipeline in candidates:
        try:
            transformed = encode_pipeline(sample, pipeline)
        except (ValueError, IRFormatError):
            continue
        score = _entropy(transformed) + 0.5 * (1.0 - _zero_ratio(transformed))
        score += 0.15 * len(transformed) / max(1, len(sample))
        scored.append((score, pipeline))
    scored.sort(key=lambda item: (item[0], item[1].name))
    result: list[Pipeline] = []
    seen: set[str] = set()
    for _score, pipeline in scored:
        if pipeline.name in seen:
            continue
        seen.add(pipeline.name)
        result.append(pipeline)
        if len(result) >= max_candidates:
            break
    return result or [Pipeline(())]


def compile_ir(data: bytes, pipeline: Pipeline) -> CompiledIR:
    src = bytes(data)
    payload = encode_pipeline(src, pipeline)
    verify_pipeline(src, pipeline)
    return CompiledIR(payload, pipeline, len(src))
