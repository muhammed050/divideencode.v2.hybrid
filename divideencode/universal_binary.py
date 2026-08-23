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
    kind: Kind
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


def _candidate_pool(data: bytes, mode: SearchMode) -> list[Kind]:
    """Build a search plan, never a compression verdict.

    The old proxy rejected transforms before DE2 measured them. That defeats
    the purpose of a representation compiler: two streams with similar byte
    statistics can select completely different DE2 modes. In particular it
    could reject XOR8 even when XOR8 produced a much smaller DE2 stream.

    Structural statistics are now used only to ORDER candidates. The actual
    DE2 size is the only quality signal used by the search.
    """
    sample = bytes(data[:256 * 1024])
    if not sample:
        return []

    all_kinds = [
        Kind.DELTA8, Kind.XOR8, Kind.NIBBLE, Kind.BITPLANE,
        Kind.TRANSPOSE4, Kind.TRANSPOSE8,
        Kind.STRIDE2, Kind.STRIDE4, Kind.STRIDE8,
    ]
    text = _textlike(sample) >= 0.70
    entropy = _entropy(sample)
    zero_delta = _zero_ratio(_delta_sample(sample))
    zero_xor = _zero_ratio(_xor_sample(sample))
    column = max(_column_similarity(sample, 2), _column_similarity(sample, 4), _column_similarity(sample, 8))

    priority: dict[Kind, float] = {k: 100.0 for k in all_kinds}
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

    ordered = sorted(all_kinds, key=lambda k: (priority[k], int(k)))
    limits = {SearchMode.FAST: 3, SearchMode.BALANCED: 6, SearchMode.MAX: len(all_kinds)}
    return ordered[:limits[mode]]


def _guided_candidates(
    data: bytes,
    mode: SearchMode,
    *,
    direct_size: int | None = None,
    sample_size: int = 64 * 1024,
) -> list[Kind]:
    from .de2 import compress as de2_compress

    src = bytes(data)
    if not src:
        return []
    if mode != SearchMode.MAX and direct_size is not None and direct_size / len(src) <= _DIRECT_SEARCH_CUTOFF:
        return []

    pool = _candidate_pool(src, mode)
    if not pool:
        return []

    sample = src[:sample_size]
    measured: list[tuple[int, Kind]] = []
    for kind in pool:
        transformed = transform(sample, kind)
        size = len(de2_compress(transformed, level="BALANCED"))
        measured.append((size, kind))

    measured.sort(key=lambda x: (x[0], int(x[1])))
    if mode == SearchMode.FAST:
        return [measured[0][1]]
    if mode == SearchMode.BALANCED:
        best = measured[0][0]
        return [kind for size, kind in measured if size <= best * 1.05][:3]
    return [kind for _size, kind in measured]


def rank_candidates(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED, direct_size: int | None = None) -> list[Kind]:
    mode = _normalize_mode(mode)
    return [Kind.DIRECT] + _guided_candidates(bytes(data), mode, direct_size=direct_size)


def _pack(kind: Kind, original_size: int, crc: int, payload: bytes) -> bytes:
    return _HEADER.pack(MAGIC, VERSION, int(kind), 0, original_size, len(payload), crc, zlib.crc32(payload) & 0xFFFFFFFF) + payload


def _unpack(blob: bytes) -> tuple[Kind, int, int, bytes]:
    if len(blob) < _HEADER.size:
        raise NotDivideEncodedError("truncated UBIR2 container")
    magic, version, kind, _flags, original_size, payload_size, crc, payload_crc = _HEADER.unpack_from(blob)
    if magic != MAGIC or version != VERSION:
        raise NotDivideEncodedError("not a UBIR2 container")
    if kind not in {int(k) for k in Kind}:
        raise CorruptedError("unknown UBIR2 transform")
    end = _HEADER.size + payload_size
    if end != len(blob):
        raise CorruptedError("UBIR2 payload size mismatch")
    payload = bytes(blob[_HEADER.size:end])
    if zlib.crc32(payload) & 0xFFFFFFFF != payload_crc:
        raise CorruptedError("UBIR2 payload checksum mismatch")
    return Kind(kind), original_size, crc, payload


def compress(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> bytes:
    from .de2 import compress as de2_compress
    src = bytes(data)
    direct_blob = de2_compress(src, block_size=block_size, level=level)
    kinds = rank_candidates(src, mode=mode, direct_size=len(direct_blob))
    best_blob = direct_blob
    best_kind = Kind.DIRECT
    for kind in kinds[1:]:
        ir = transform(src, kind)
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
    best_kind = Kind.DIRECT
    best_ir_size = len(src)
    tested = 1
    for kind in kinds[1:]:
        ir = transform(src, kind)
        candidate = de2_compress(ir, block_size=block_size, level=level)
        tested += 1
        if len(candidate) < len(best_blob):
            best_blob, best_kind, best_ir_size = candidate, kind, len(ir)
    return Result(_pack(best_kind, len(src), zlib.crc32(src) & 0xFFFFFFFF, best_blob), best_kind, len(best_blob), best_ir_size, tested)


def decompress(blob: bytes, *, verify: bool = True) -> bytes:
    from .de2 import decompress as de2_decompress
    kind, original_size, crc, payload = _unpack(bytes(blob))
    ir = de2_decompress(payload, verify=verify)
    data = inverse(ir, kind, original_size=original_size)
    if len(data) != original_size:
        raise CorruptedError("UBIR2 original size mismatch")
    if verify and zlib.crc32(data) & 0xFFFFFFFF != crc:
        raise CorruptedError("UBIR2 source checksum mismatch")
    return data
