"""UBIR2 -- universal representation compiler for DE2.

UBIR2 is a compiler, not a compressor.  Any input is valid bytes.  It may be
expanded into a reversible Universal Binary IR program; only the final DE2
size decides whether that program is selected.  DIRECT remains a mandatory
fallback.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum

from .errors import CorruptedError, NotDivideEncodedError
from .universal_ir import Kind, transform, inverse
from .universal_compiler import Pipeline, compile_ir, decode_pipeline, deserialize, plan

MAGIC = b"UB2D"
VERSION = 2
_HEADER = struct.Struct("<4sBBHQQII")
_PIPELINE_KIND = 255


class SearchMode(IntEnum):
    FAST = 1
    BALANCED = 2
    MAX = 3


class BinaryKind(IntEnum):
    DELTA16 = 10
    DELTA32 = 11
    DELTA64 = 12
    XOR16 = 13
    XOR32 = 14
    XOR64 = 15
    SWAP16 = 16
    SWAP32 = 17
    SWAP64 = 18


@dataclass(frozen=True)
class Analysis:
    sample_size: int
    entropy: float
    zero_ratio: float
    run_ratio: float
    delta_zero_ratio: float
    xor_zero_ratio: float
    bitplane_run_ratio: float


@dataclass(frozen=True)
class Result:
    data: bytes
    kind: IntEnum | str
    de2_size: int
    ir_size: int
    candidates_tested: int


@dataclass(frozen=True)
class _Candidate:
    kind: IntEnum | str
    ir: bytes
    pipeline: Pipeline | None = None


def _normalize_mode(mode: SearchMode | str) -> SearchMode:
    if isinstance(mode, SearchMode):
        return mode
    if isinstance(mode, str):
        try:
            return SearchMode[mode.upper()]
        except KeyError as exc:
            raise ValueError(f"unknown UBIR2 search mode: {mode!r}; expected FAST, BALANCED, or MAX") from exc
    try:
        return SearchMode(mode)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid UBIR2 search mode: {mode!r}") from exc


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    import math
    return -sum((c / n) * math.log2(c / n) for c in counts if c)


def _ratio_equal(data: bytes) -> float:
    if len(data) < 2:
        return 0.0
    return sum(a == b for a, b in zip(data, data[1:])) / (len(data) - 1)


def _zero_ratio(data: bytes) -> float:
    return data.count(0) / len(data) if data else 0.0


def _delta_sample(data: bytes) -> bytes:
    out = bytearray(len(data))
    prev = 0
    for i, b in enumerate(data):
        out[i] = (b - prev) & 0xFF
        prev = b
    return bytes(out)


def _xor_sample(data: bytes) -> bytes:
    out = bytearray(len(data))
    prev = 0
    for i, b in enumerate(data):
        out[i] = b ^ prev
        prev = b
    return bytes(out)


def analyze(data: bytes, *, sample_size: int = 256 * 1024) -> Analysis:
    sample = bytes(data[:sample_size])
    delta = _delta_sample(sample)
    xor = _xor_sample(sample)
    return Analysis(
        len(sample), _entropy(sample), _zero_ratio(sample), _ratio_equal(sample),
        _zero_ratio(delta), _zero_ratio(xor), _ratio_equal(transform(sample, Kind.BITPLANE)),
    )


def _word_transform(src: bytes, width: int, op: str, decode: bool = False) -> bytes:
    src = bytes(src)
    out = bytearray(src)
    mask = (1 << (8 * width)) - 1
    full = len(src) - len(src) % width
    prev = 0
    for off in range(0, full, width):
        value = int.from_bytes(src[off:off + width], "little")
        original = value
        if op == "swap":
            result = value.to_bytes(width, "little")[::-1]
        elif op == "delta":
            if decode:
                value = (prev + value) & mask
                result = value.to_bytes(width, "little")
                prev = value
            else:
                result = ((value - prev) & mask).to_bytes(width, "little")
                prev = original
        elif op == "xor":
            if decode:
                value ^= prev
                result = value.to_bytes(width, "little")
                prev = value
            else:
                result = (value ^ prev).to_bytes(width, "little")
                prev = original
        else:
            raise ValueError(op)
        out[off:off + width] = result
    return bytes(out)


def _binary_transform(src: bytes, kind: BinaryKind, decode: bool = False) -> bytes:
    name = kind.name
    if name.startswith("DELTA"):
        return _word_transform(src, int(name[5:]) // 8, "delta", decode)
    if name.startswith("XOR"):
        return _word_transform(src, int(name[3:]) // 8, "xor", decode)
    if name.startswith("SWAP"):
        return _word_transform(src, int(name[4:]) // 8, "swap", False)
    raise ValueError(f"unknown UBIR2 binary transform: {kind}")


def _apply_transform(src: bytes, kind: IntEnum, *, decode: bool = False, original_size: int | None = None) -> bytes:
    if isinstance(kind, BinaryKind):
        return _binary_transform(src, kind, decode=decode)
    return inverse(src, kind, original_size=original_size) if decode else transform(src, kind)


def _pack(kind: int, original_size: int, crc: int, payload: bytes) -> bytes:
    return _HEADER.pack(MAGIC, VERSION, kind, 0, original_size, len(payload), crc, zlib.crc32(payload) & 0xFFFFFFFF) + payload


def _unpack(blob: bytes) -> tuple[int, int, int, bytes]:
    if len(blob) < _HEADER.size:
        raise NotDivideEncodedError("truncated UBIR2 container")
    magic, version, kind, _flags, original_size, payload_size, crc, payload_crc = _HEADER.unpack_from(blob)
    if magic != MAGIC or version not in (1, VERSION):
        raise NotDivideEncodedError("not a UBIR2 container")
    end = _HEADER.size + payload_size
    if end != len(blob):
        raise CorruptedError("UBIR2 payload size mismatch")
    payload = bytes(blob[_HEADER.size:end])
    if zlib.crc32(payload) & 0xFFFFFFFF != payload_crc:
        raise CorruptedError("UBIR2 payload checksum mismatch")
    return kind, original_size, crc, payload


def rank_candidates(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED, direct_size: int | None = None) -> list[IntEnum]:
    """Compatibility ranking for the original single-transform API.

    The actual compiler now uses :func:`plan` and evaluates complete IR
    pipelines.  This function remains available to existing callers.
    """
    mode = _normalize_mode(mode)
    candidates: list[IntEnum] = [Kind.DIRECT, Kind.DELTA8, Kind.XOR8, Kind.NIBBLE, Kind.BITPLANE,
                                 Kind.TRANSPOSE4, Kind.TRANSPOSE8, Kind.STRIDE2, Kind.STRIDE4, Kind.STRIDE8,
                                 BinaryKind.DELTA16, BinaryKind.DELTA32, BinaryKind.DELTA64,
                                 BinaryKind.XOR16, BinaryKind.XOR32, BinaryKind.XOR64,
                                 BinaryKind.SWAP16, BinaryKind.SWAP32, BinaryKind.SWAP64]
    if mode == SearchMode.FAST:
        return [Kind.DIRECT, Kind.XOR8]
    if mode == SearchMode.BALANCED:
        return candidates[:11]
    return candidates


def _legacy_candidates(src: bytes, mode: SearchMode) -> list[_Candidate]:
    kinds = rank_candidates(src, mode=mode)
    result: list[_Candidate] = []
    for kind in kinds[1:]:
        result.append(_Candidate(kind, _apply_transform(src, kind)))
    return result


def _pipeline_limit(mode: SearchMode) -> int:
    return {SearchMode.FAST: 8, SearchMode.BALANCED: 24, SearchMode.MAX: 64}[mode]


def _build_candidates(src: bytes, mode: SearchMode) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    # Complete programs are the primary representation.  The plan is only a
    # search bound; final DE2 size is still measured for every program here.
    for pipeline in plan(src, max_candidates=_pipeline_limit(mode)):
        compiled = compile_ir(src, pipeline)
        candidates.append(_Candidate("IR:" + pipeline.name, compiled.payload, pipeline))
    # Keep the original transforms as compatibility fallbacks for paths that
    # predate the v2 compiler.
    candidates.extend(_legacy_candidates(src, mode))
    return candidates


def _choose(src: bytes, mode: SearchMode, level: str, block_size: int) -> tuple[bytes, _Candidate, int]:
    from .de2 import compress as de2_compress
    direct = de2_compress(src, block_size=block_size, level=level)
    best_blob = direct
    best = _Candidate(Kind.DIRECT, src)
    tested = 1
    for candidate in _build_candidates(src, mode):
        packed = de2_compress(candidate.ir, block_size=block_size, level=level)
        tested += 1
        if len(packed) < len(best_blob):
            best_blob = packed
            best = candidate
    return best_blob, best, tested


def compress(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> bytes:
    src = bytes(data)
    mode = _normalize_mode(mode)
    best_blob, best, _tested = _choose(src, mode, level, block_size)
    if isinstance(best.kind, Kind):
        kind_value = int(best.kind)
        payload = best_blob
    else:
        # Pipeline payload is the DE2 stream followed by a compact pipeline
        # descriptor.  The descriptor is outside DE2 so DE2 still sees only
        # the compiled binary IR bytes.
        descriptor = struct.pack("<4sBBQ", b"IRP2", 1, len(best.pipeline.instructions), len(src))
        descriptor += bytes(int(i.op) for i in best.pipeline.instructions)
        payload = descriptor + best_blob
        kind_value = _PIPELINE_KIND
    return _pack(kind_value, len(src), zlib.crc32(src) & 0xFFFFFFFF, payload)


def compress_with_stats(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> Result:
    src = bytes(data)
    mode = _normalize_mode(mode)
    best_blob, best, tested = _choose(src, mode, level, block_size)
    if isinstance(best.kind, Kind):
        kind = best.kind
        payload = best_blob
        ir_size = len(best.ir)
    else:
        descriptor = struct.pack("<4sBBQ", b"IRP2", 1, len(best.pipeline.instructions), len(src))
        descriptor += bytes(int(i.op) for i in best.pipeline.instructions)
        payload = descriptor + best_blob
        kind = best.kind
        ir_size = len(best.ir)
    return Result(_pack(_PIPELINE_KIND if isinstance(kind, str) else int(kind), len(src), zlib.crc32(src) & 0xFFFFFFFF, payload), kind, len(best_blob), ir_size, tested)


def _decode_pipeline_payload(payload: bytes, original_size: int, *, verify: bool) -> bytes:
    from .de2 import decompress as de2_decompress
    if len(payload) < 14 or payload[:4] != b"IRP2":
        raise CorruptedError("missing UBIR2 pipeline descriptor")
    _magic, version, count, declared_size = struct.unpack_from("<4sBBQ", payload)
    if version != 1 or declared_size != original_size:
        raise CorruptedError("invalid UBIR2 pipeline descriptor")
    pos = 14
    if len(payload) < pos + count:
        raise CorruptedError("truncated UBIR2 pipeline descriptor")
    try:
        from .universal_compiler import Instruction, Op
        instructions = tuple(Instruction(Op(v)) for v in payload[pos:pos + count])
    except (ValueError, TypeError) as exc:
        raise CorruptedError("unknown UBIR2 pipeline opcode") from exc
    pipeline = Pipeline(instructions)
    ir = de2_decompress(payload[pos + count:], verify=verify)
    try:
        return decode_pipeline(ir, pipeline, original_size)
    except Exception as exc:
        raise CorruptedError("UBIR2 pipeline decode failed") from exc


def decompress(blob: bytes, *, verify: bool = True) -> bytes:
    kind, original_size, crc, payload = _unpack(bytes(blob))
    if kind == _PIPELINE_KIND:
        data = _decode_pipeline_payload(payload, original_size, verify=verify)
    else:
        from .de2 import decompress as de2_decompress
        try:
            kind_enum: IntEnum = BinaryKind(kind) if kind >= 10 else Kind(kind)
        except ValueError as exc:
            raise CorruptedError("unknown UBIR2 transform") from exc
        ir = de2_decompress(payload, verify=verify)
        data = _apply_transform(ir, kind_enum, decode=True, original_size=original_size)
    if len(data) != original_size:
        raise CorruptedError("UBIR2 original size mismatch")
    if verify and zlib.crc32(data) & 0xFFFFFFFF != crc:
        raise CorruptedError("UBIR2 source checksum mismatch")
    return data
