"""UBIR2 -- universal representation compiler for DE2.

UBIR2 is intentionally not a compressor. It searches reversible
representations whose resulting bytes are easier for DE2 to encode. The
intermediate representation may grow; only final DE2 size is authoritative.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum

from .errors import CorruptedError, NotDivideEncodedError
from .universal_ir import Kind, transform, inverse

MAGIC = b"UB2D"
VERSION = 1
_HEADER = struct.Struct("<4sBBHQQII")
_DIRECT_SEARCH_CUTOFF = 0.10


class SearchMode(IntEnum):
    FAST = 1
    BALANCED = 2
    MAX = 3


# Extra binary representations live here so the older UBIR1 Kind enum stays
# wire-compatible. Values 10..18 are reserved by UBIR2 for this family.
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
    kind: IntEnum
    de2_size: int
    ir_size: int
    candidates_tested: int


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


def _bitplane_sample(data: bytes) -> bytes:
    return transform(data, Kind.BITPLANE)


def analyze(data: bytes, *, sample_size: int = 256 * 1024) -> Analysis:
    sample = bytes(data[:sample_size])
    delta = _delta_sample(sample)
    xor = _xor_sample(sample)
    bitplane = _bitplane_sample(sample)
    return Analysis(
        len(sample), _entropy(sample), _zero_ratio(sample), _ratio_equal(sample),
        _zero_ratio(delta), _zero_ratio(xor), _ratio_equal(bitplane),
    )


def _column_similarity(data: bytes, width: int) -> float:
    if width <= 1 or len(data) < width * 8:
        return 0.0
    columns: list[list[int]] = [[0] * 256 for _ in range(width)]
    counts = [0] * width
    for i, b in enumerate(data):
        c = i % width
        columns[c][b] += 1
        counts[c] += 1
    total = pairs = 0.0
    for a in range(width - 1):
        for b in range(a + 1, width):
            if not counts[a] or not counts[b]:
                continue
            total += sum(min(columns[a][v] / counts[a], columns[b][v] / counts[b]) for v in range(256))
            pairs += 1
    return total / pairs if pairs else 0.0


def _textlike(data: bytes) -> float:
    if not data:
        return 0.0
    return sum(1 for b in data if b in (9, 10, 13) or 32 <= b <= 126) / len(data)


def _word_transform(src: bytes, width: int, op: str, decode: bool = False) -> bytes:
    """Reversible little-endian word transform; incomplete tail is unchanged."""
    src = bytes(src)
    out = bytearray(src)
    mask = (1 << (8 * width)) - 1
    full = len(src) - (len(src) % width)
    prev = 0
    for off in range(0, full, width):
        value = int.from_bytes(src[off:off + width], "little")
        if op == "swap":
            result = value.to_bytes(width, "little")[::-1]
        elif op == "delta":
            if decode:
                value = (prev + value) & mask
                result = value.to_bytes(width, "little")
            else:
                result_value = (value - prev) & mask
                result = result_value.to_bytes(width, "little")
            prev = value
        elif op == "xor":
            if decode:
                value ^= prev
                result = value.to_bytes(width, "little")
            else:
                result = (value ^ prev).to_bytes(width, "little")
            prev = value
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


def _candidate_pool(data: bytes, mode: SearchMode) -> list[IntEnum]:
    """Rank representations; never reject one using a compression proxy."""
    sample = bytes(data[:256 * 1024])
    if not sample:
        return []

    old_kinds: list[IntEnum] = [
        Kind.DELTA8, Kind.XOR8, Kind.NIBBLE, Kind.BITPLANE,
        Kind.TRANSPOSE4, Kind.TRANSPOSE8,
        Kind.STRIDE2, Kind.STRIDE4, Kind.STRIDE8,
    ]
    word_kinds: list[IntEnum] = [
        BinaryKind.DELTA16, BinaryKind.DELTA32, BinaryKind.DELTA64,
        BinaryKind.XOR16, BinaryKind.XOR32, BinaryKind.XOR64,
        BinaryKind.SWAP16, BinaryKind.SWAP32, BinaryKind.SWAP64,
    ]
    all_kinds = old_kinds + word_kinds
    text = _textlike(sample) >= 0.70
    entropy = _entropy(sample)
    zero_delta = _zero_ratio(_delta_sample(sample))
    zero_xor = _zero_ratio(_xor_sample(sample))
    column = max(_column_similarity(sample, 2), _column_similarity(sample, 4), _column_similarity(sample, 8))

    priority: dict[IntEnum, float] = {k: 100.0 for k in all_kinds}
    priority[Kind.DELTA8] -= zero_delta * 40.0
    priority[Kind.XOR8] -= zero_xor * 40.0
    priority[Kind.NIBBLE] -= max(
        sum((b & 0x0F) == 0 for b in sample) / len(sample),
        sum((b >> 4) == 0 for b in sample) / len(sample),
    ) * 20.0
    for k in (Kind.STRIDE2, Kind.STRIDE4, Kind.STRIDE8):
        priority[k] -= column * 15.0
    if text:
        priority[Kind.XOR8] -= 10.0
        priority[Kind.DELTA8] -= 8.0
    if entropy > 7.5:
        priority[Kind.BITPLANE] += 5.0

    # Word transforms are deliberately always eligible for binary-ish data.
    # Their sample DE2 result decides whether they are useful.
    if not text:
        for k in word_kinds:
            priority[k] -= 4.0
    if column > 0.55:
        for k in word_kinds:
            priority[k] -= 8.0
    if zero_delta > 0.10:
        for k in (BinaryKind.DELTA16, BinaryKind.DELTA32, BinaryKind.DELTA64):
            priority[k] -= 10.0
    if zero_xor > 0.10:
        for k in (BinaryKind.XOR16, BinaryKind.XOR32, BinaryKind.XOR64):
            priority[k] -= 10.0

    ordered = sorted(all_kinds, key=lambda k: (priority[k], int(k)))
    limits = {SearchMode.FAST: 5, SearchMode.BALANCED: 10, SearchMode.MAX: len(all_kinds)}
    return ordered[:limits[mode]]


def _apply_transform(data: bytes, kind: IntEnum, *, decode: bool = False, original_size: int | None = None) -> bytes:
    if isinstance(kind, BinaryKind):
        return _binary_transform(data, kind, decode=decode)
    return inverse(data, kind, original_size=original_size) if decode else transform(data, kind)


def _guided_candidates(data: bytes, mode: SearchMode, *, direct_size: int | None = None, sample_size: int = 64 * 1024) -> list[IntEnum]:
    from .de2 import compress as de2_compress
    src = bytes(data)
    if not src:
        return []
    if mode != SearchMode.MAX and direct_size is not None and direct_size / len(src) <= _DIRECT_SEARCH_CUTOFF:
        return []
    pool = _candidate_pool(src, mode)
    sample = src[:sample_size]
    measured: list[tuple[int, IntEnum]] = []
    for kind in pool:
        transformed = _apply_transform(sample, kind)
        size = len(de2_compress(transformed, level="BALANCED"))
        measured.append((size, kind))
    measured.sort(key=lambda x: (x[0], int(x[1])))
    if mode == SearchMode.FAST:
        return [measured[0][1]]
    if mode == SearchMode.BALANCED:
        best = measured[0][0]
        return [kind for size, kind in measured if size <= best * 1.08][:5]
    return [kind for _size, kind in measured]


def rank_candidates(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED, direct_size: int | None = None) -> list[IntEnum]:
    mode = _normalize_mode(mode)
    return [Kind.DIRECT] + _guided_candidates(bytes(data), mode, direct_size=direct_size)


def _pack(kind: IntEnum, original_size: int, crc: int, payload: bytes) -> bytes:
    return _HEADER.pack(MAGIC, VERSION, int(kind), 0, original_size, len(payload), crc, zlib.crc32(payload) & 0xFFFFFFFF) + payload


def _unpack(blob: bytes) -> tuple[IntEnum, int, int, bytes]:
    if len(blob) < _HEADER.size:
        raise NotDivideEncodedError("truncated UBIR2 container")
    magic, version, kind_value, _flags, original_size, payload_size, crc, payload_crc = _HEADER.unpack_from(blob)
    if magic != MAGIC or version != VERSION:
        raise NotDivideEncodedError("not a UBIR2 container")
    try:
        kind: IntEnum = BinaryKind(kind_value) if kind_value >= 10 else Kind(kind_value)
    except ValueError as exc:
        raise CorruptedError("unknown UBIR2 transform") from exc
    end = _HEADER.size + payload_size
    if end != len(blob):
        raise CorruptedError("UBIR2 payload size mismatch")
    payload = bytes(blob[_HEADER.size:end])
    if zlib.crc32(payload) & 0xFFFFFFFF != payload_crc:
        raise CorruptedError("UBIR2 payload checksum mismatch")
    return kind, original_size, crc, payload


def compress(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> bytes:
    from .de2 import compress as de2_compress
    src = bytes(data)
    direct_blob = de2_compress(src, block_size=block_size, level=level)
    kinds = rank_candidates(src, mode=mode, direct_size=len(direct_blob))
    best_blob = direct_blob
    best_kind: IntEnum = Kind.DIRECT
    for kind in kinds[1:]:
        ir = _apply_transform(src, kind)
        candidate = de2_compress(ir, block_size=block_size, level=level)
        if len(candidate) < len(best_blob):
            best_blob, best_kind = candidate, kind
    return _pack(best_kind, len(src), zlib.crc32(src) & 0xFFFFFFFF, best_blob)


def compress_with_stats(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> Result:
    from .de2 import compress as de2_compress
    src = bytes(data)
    direct_blob = de2_compress(src, block_size=block_size, level=level)
    kinds = rank_candidates(src, mode=mode, direct_size=len(direct_blob))
    best_blob = direct_blob
    best_kind: IntEnum = Kind.DIRECT
    best_ir_size = len(src)
    tested = 1
    for kind in kinds[1:]:
        ir = _apply_transform(src, kind)
        candidate = de2_compress(ir, block_size=block_size, level=level)
        tested += 1
        if len(candidate) < len(best_blob):
            best_blob, best_kind, best_ir_size = candidate, kind, len(ir)
    return Result(_pack(best_kind, len(src), zlib.crc32(src) & 0xFFFFFFFF, best_blob), best_kind, len(best_blob), best_ir_size, tested)


def decompress(blob: bytes, *, verify: bool = True) -> bytes:
    from .de2 import decompress as de2_decompress
    kind, original_size, crc, payload = _unpack(bytes(blob))
    ir = de2_decompress(payload, verify=verify)
    data = _apply_transform(ir, kind, decode=True, original_size=original_size)
    if len(data) != original_size:
        raise CorruptedError("UBIR2 original size mismatch")
    if verify and zlib.crc32(data) & 0xFFFFFFFF != crc:
        raise CorruptedError("UBIR2 source checksum mismatch")
    return data
