"""UBIR2 -- guided universal binary representation search for DE2.

The IR is intentionally allowed to grow. The only objective is the final
DE2 container size. A cheap proxy narrows the search, then a bounded sample
is actually compressed by DE2 to choose the most promising representation.
Only the selected full-size representation is sent through DE2, alongside
DIRECT as the mandatory baseline.

This module is deliberately separate from the existing phrase frontend so
benchmarks can compare the approaches without changing DE2 internals.
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
    entropy = 0.0
    import math
    for c in counts:
        if c:
            p = c / n
            entropy -= p * math.log2(p)
    return entropy


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
        len(sample),
        _entropy(sample),
        _zero_ratio(sample),
        _ratio_equal(sample),
        _zero_ratio(delta),
        _zero_ratio(xor),
        _ratio_equal(bitplane),
    )


def _proxy(data: bytes) -> float:
    """Cheap lower-is-better proxy used only for initial candidate pruning."""
    if not data:
        return 0.0
    sample = data[: min(len(data), 64 * 1024)]
    counts = [0] * 256
    for b in sample:
        counts[b] += 1
    concentration = sum(c * c for c in counts) / len(sample)
    zeros = sample.count(0) / len(sample)
    runs = _ratio_equal(sample)
    return 1.0 / (1.0 + concentration * 0.015 + zeros * 2.5 + runs * 4.0)


def _candidate_pool(data: bytes, mode: SearchMode) -> list[Kind]:
    """Use cheap statistics to make a small pool for the DE2 sample oracle."""
    sample = bytes(data[:256 * 1024])
    if not sample:
        return []
    candidates = [Kind.DELTA8, Kind.XOR8, Kind.BITPLANE, Kind.TRANSPOSE4, Kind.TRANSPOSE8]
    low_nibble = sum((b & 0x0F) == 0 for b in sample) / len(sample)
    high_nibble = sum((b >> 4) == 0 for b in sample) / len(sample)
    if max(low_nibble, high_nibble) >= 0.20:
        candidates.append(Kind.NIBBLE)

    base = _proxy(sample)
    scored: list[tuple[float, Kind]] = []
    for kind in candidates:
        transformed = transform(sample, kind)
        score = _proxy(transformed) * (len(transformed) / len(sample))
        if score < base * 0.99:
            scored.append((score, kind))
    scored.sort(key=lambda x: (x[0], int(x[1])))

    # The proxy only selects a bounded pool. The final decision is made by
    # actual DE2 on the sample, never by this heuristic alone.
    pool_limit = {SearchMode.FAST: 1, SearchMode.BALANCED: 2, SearchMode.MAX: 3}[mode]
    return [kind for _score, kind in scored[:pool_limit]]


def _guided_candidates(data: bytes, mode: SearchMode, *, sample_size: int = 64 * 1024) -> list[Kind]:
    """Pick transforms using real DE2 sizes on a bounded sample."""
    from .de2 import compress as de2_compress

    pool = _candidate_pool(data, mode)
    if not pool:
        return []
    sample = bytes(data[:sample_size])
    direct_size = len(de2_compress(sample, level="BALANCED"))
    scored: list[tuple[int, Kind]] = []
    for kind in pool:
        transformed = transform(sample, kind)
        size = len(de2_compress(transformed, level="BALANCED"))
        # Only candidates that beat DIRECT on the actual sample survive.
        if size < direct_size:
            scored.append((size, kind))
    scored.sort(key=lambda x: (x[0], int(x[1])))
    if not scored:
        return []

    # Balanced/Max may retain a second candidate only when it is genuinely
    # close to the best sample result. This prevents expensive full trials on
    # weak alternatives while preserving diversity.
    best_size = scored[0][0]
    if mode == SearchMode.FAST:
        return [scored[0][1]]
    close = [kind for size, kind in scored if size <= best_size * 1.02]
    return close[:2 if mode == SearchMode.BALANCED else 3]


def rank_candidates(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED) -> list[Kind]:
    """Return DIRECT plus transforms selected by a bounded DE2 sample oracle."""
    mode = _normalize_mode(mode)
    return [Kind.DIRECT] + _guided_candidates(bytes(data), mode)


def _pack(kind: Kind, original_size: int, crc: int, payload: bytes) -> bytes:
    header = _HEADER.pack(MAGIC, VERSION, int(kind), 0, original_size, len(payload), crc, zlib.crc32(payload) & 0xFFFFFFFF)
    return header + payload


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
    """Compress with DIRECT plus only transforms proven by sample DE2."""
    from .de2 import compress as de2_compress

    src = bytes(data)
    kinds = rank_candidates(src, mode=mode)
    best_blob = de2_compress(src, block_size=block_size, level=level)
    best_kind = Kind.DIRECT
    for kind in kinds[1:]:
        ir = transform(src, kind)
        candidate = de2_compress(ir, block_size=block_size, level=level)
        if len(candidate) < len(best_blob):
            best_blob = candidate
            best_kind = kind
    return _pack(best_kind, len(src), zlib.crc32(src) & 0xFFFFFFFF, best_blob)


def compress_with_stats(data: bytes, *, mode: SearchMode | str = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> Result:
    from .de2 import compress as de2_compress
    src = bytes(data)
    kinds = rank_candidates(src, mode=mode)
    best_blob = de2_compress(src, block_size=block_size, level=level)
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
