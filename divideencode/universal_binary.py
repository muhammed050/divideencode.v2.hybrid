"""UBIR2 -- fast universal binary representation search for DE2.

The IR is intentionally allowed to grow.  The only objective is the final
DE2 container size.  A cheap sample pass ranks reversible transforms, then
only the most promising transforms are materialized and sent through DE2.
DIRECT is always encoded as the baseline and is always eligible to win.

This module is deliberately separate from the existing phrase frontend so
benchmarks can compare the approaches without changing DE2 internals.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable

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
    """Cheap lower-is-better proxy used only on the bounded sample."""
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


def _sample_transform(data: bytes, kind: Kind) -> bytes:
    return transform(data, kind)


def rank_candidates(data: bytes, *, mode: SearchMode = SearchMode.BALANCED) -> list[Kind]:
    """Return only likely DE2-friendly transforms, without running DE2."""
    sample = bytes(data[: 256 * 1024])
    if not sample:
        return [Kind.DIRECT]
    candidates = [Kind.DELTA8, Kind.XOR8, Kind.BITPLANE, Kind.TRANSPOSE4, Kind.TRANSPOSE8]
    # Nibble planes always double the IR and are therefore only explored when
    # the sample strongly concentrates in low/high nibbles.
    low_nibble = sum((b & 0x0F) == 0 for b in sample) / len(sample)
    high_nibble = sum((b >> 4) == 0 for b in sample) / len(sample)
    if max(low_nibble, high_nibble) >= 0.20:
        candidates.append(Kind.NIBBLE)

    base_proxy = _proxy(sample)
    scored: list[tuple[float, Kind]] = []
    for kind in candidates:
        transformed = _sample_transform(sample, kind)
        growth = len(transformed) / len(sample)
        score = _proxy(transformed) * growth
        # Require a meaningful predicted improvement. This keeps random and
        # already-compressed data on DIRECT without expensive full trials.
        if score < base_proxy * 0.94:
            scored.append((score, kind))
    scored.sort(key=lambda x: (x[0], int(x[1])))
    limit = {SearchMode.FAST: 1, SearchMode.BALANCED: 2, SearchMode.MAX: 3}[mode]
    return [Kind.DIRECT] + [kind for _score, kind in scored[:limit]]


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


def compress(data: bytes, *, mode: SearchMode = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> bytes:
    """Compress using DIRECT plus at most 1/2/3 promising UBIR transforms.

    The final winner is always selected by the actual DE2 byte length.  The
    representation itself is never required to be smaller than the source.
    """
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


def compress_with_stats(data: bytes, *, mode: SearchMode = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> Result:
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
