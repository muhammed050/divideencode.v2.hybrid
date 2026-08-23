"""UBIR1 — Universal Binary Intermediate Representation for DE2.

This layer is a reversible *representation compiler*, not a compressor.
Arbitrary bytes are rewritten into DE2-friendly layouts. The representation
is allowed to grow; the downstream DE2 stage decides whether the rewrite was
worthwhile.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


MAGIC = b"UBIR1"
VERSION = 1


class Kind(IntEnum):
    DIRECT = 0
    DELTA8 = 1
    XOR8 = 2
    NIBBLE = 3
    BITPLANE = 4
    TRANSPOSE4 = 5
    TRANSPOSE8 = 6
    STRIDE2 = 7
    STRIDE4 = 8
    STRIDE8 = 9


@dataclass(frozen=True)
class Candidate:
    kind: Kind
    payload: bytes
    score: float


def _delta_encode(src: bytes) -> bytes:
    out = bytearray(len(src))
    prev = 0
    for i, b in enumerate(src):
        out[i] = (b - prev) & 0xFF
        prev = b
    return bytes(out)


def _delta_decode(src: bytes) -> bytes:
    out = bytearray(len(src))
    prev = 0
    for i, b in enumerate(src):
        prev = (prev + b) & 0xFF
        out[i] = prev
    return bytes(out)


def _xor_encode(src: bytes) -> bytes:
    out = bytearray(len(src))
    prev = 0
    for i, b in enumerate(src):
        out[i] = b ^ prev
        prev = b
    return bytes(out)


def _xor_decode(src: bytes) -> bytes:
    out = bytearray(len(src))
    prev = 0
    for i, b in enumerate(src):
        prev ^= b
        out[i] = prev
    return bytes(out)


def _nibble_encode(src: bytes) -> bytes:
    n = len(src)
    out = bytearray(2 * n)
    for i, b in enumerate(src):
        out[i] = b & 0x0F
        out[n + i] = b >> 4
    return bytes(out)


def _nibble_decode(src: bytes, original_size: int | None = None) -> bytes:
    if len(src) % 2:
        raise ValueError("invalid nibble plane length")
    n = len(src) // 2
    if original_size is not None and original_size > n:
        raise ValueError("invalid nibble original size")
    out = bytearray(n)
    for i in range(n):
        out[i] = (src[i] & 0x0F) | ((src[n + i] & 0x0F) << 4)
    return bytes(out if original_size is None else out[:original_size])


def _bitplane_encode(src: bytes) -> bytes:
    n = len(src)
    if not src:
        return b""
    groups = (n + 7) // 8
    out = bytearray(groups * 8)
    for g in range(groups):
        base = g * 8
        block = src[base:base + 8]
        for bit in range(8):
            v = 0
            for j, b in enumerate(block):
                if b & (1 << bit):
                    v |= 1 << j
            out[base + bit] = v
    return bytes(out)


def _bitplane_decode(src: bytes, original_size: int | None = None) -> bytes:
    if len(src) % 8:
        raise ValueError("invalid bit-plane length")
    out = bytearray((len(src) // 8) * 8)
    for base in range(0, len(src), 8):
        for bit in range(8):
            packed = src[base + bit]
            for j in range(8):
                if packed & (1 << j):
                    out[base + j] |= 1 << bit
    if original_size is not None:
        if original_size > len(out):
            raise ValueError("invalid bit-plane original size")
        return bytes(out[:original_size])
    return bytes(out)


def _transpose(src: bytes, width: int) -> bytes:
    block_size = width * width
    out = bytearray(src)
    for base in range(0, len(src) - block_size + 1, block_size):
        for row in range(width):
            for col in range(width):
                out[base + row * width + col] = src[base + col * width + row]
    return bytes(out)


def _transpose_decode(src: bytes, width: int) -> bytes:
    return _transpose(src, width)


def _stride_encode(src: bytes, width: int) -> bytes:
    """Group bytes by position modulo *width*, preserving length exactly.

    This exposes repeated columns/fields that are separated by a fixed byte
    stride. It is particularly useful for regular text/source records and
    fixed-width binary structures. The tail is naturally handled by the
    modulo grouping, so no padding or sidecar is required.
    """
    if width <= 1 or len(src) < width:
        return bytes(src)
    return b"".join(src[offset::width] for offset in range(width))


def _stride_decode(src: bytes, width: int, original_size: int | None = None) -> bytes:
    if width <= 1 or len(src) < width:
        out = bytes(src)
    else:
        n = len(src)
        lengths = [(n + width - 1 - i) // width for i in range(width)]
        groups = []
        pos = 0
        for length in lengths:
            groups.append(src[pos:pos + length])
            pos += length
        out_buf = bytearray(n)
        positions = [0] * width
        for i in range(n):
            group = i % width
            out_buf[i] = groups[group][positions[group]]
            positions[group] += 1
        out = bytes(out_buf)
    return out if original_size is None else out[:original_size]


def transform(src: bytes, kind: Kind) -> bytes:
    src = bytes(src)
    if kind == Kind.DIRECT:
        return src
    if kind == Kind.DELTA8:
        return _delta_encode(src)
    if kind == Kind.XOR8:
        return _xor_encode(src)
    if kind == Kind.NIBBLE:
        return _nibble_encode(src)
    if kind == Kind.BITPLANE:
        return _bitplane_encode(src)
    if kind == Kind.TRANSPOSE4:
        return _transpose(src, 4)
    if kind == Kind.TRANSPOSE8:
        return _transpose(src, 8)
    if kind == Kind.STRIDE2:
        return _stride_encode(src, 2)
    if kind == Kind.STRIDE4:
        return _stride_encode(src, 4)
    if kind == Kind.STRIDE8:
        return _stride_encode(src, 8)
    raise ValueError(f"unknown UBIR kind: {kind}")


def inverse(src: bytes, kind: Kind, *, original_size: int | None = None) -> bytes:
    src = bytes(src)
    if kind == Kind.DIRECT:
        return src if original_size is None else src[:original_size]
    if kind == Kind.DELTA8:
        out = _delta_decode(src)
    elif kind == Kind.XOR8:
        out = _xor_decode(src)
    elif kind == Kind.NIBBLE:
        return _nibble_decode(src, original_size)
    elif kind == Kind.BITPLANE:
        return _bitplane_decode(src, original_size)
    elif kind == Kind.TRANSPOSE4:
        out = _transpose_decode(src, 4)
    elif kind == Kind.TRANSPOSE8:
        out = _transpose_decode(src, 8)
    elif kind == Kind.STRIDE2:
        return _stride_decode(src, 2, original_size)
    elif kind == Kind.STRIDE4:
        return _stride_decode(src, 4, original_size)
    elif kind == Kind.STRIDE8:
        return _stride_decode(src, 8, original_size)
    else:
        raise ValueError(f"unknown UBIR kind: {kind}")
    return out if original_size is None else out[:original_size]


def _score(data: bytes) -> float:
    if not data:
        return 0.0
    sample = data[: min(len(data), 256 * 1024)]
    counts = [0] * 256
    for b in sample:
        counts[b] += 1
    repeated = sum(c * c for c in counts) / len(sample)
    low = sum(1 for b in sample if b < 16) / len(sample)
    runs = sum(sample[i] == sample[i - 1] for i in range(1, len(sample))) / max(1, len(sample) - 1)
    size_penalty = len(data) / max(1, len(sample))
    return (len(sample) / (1.0 + repeated * 0.02 + low * 2.0 + runs * 4.0)) * size_penalty


def rank(src: bytes, *, include_direct: bool = True) -> list[Candidate]:
    src = bytes(src)
    kinds = list(Kind)
    if not include_direct:
        kinds.remove(Kind.DIRECT)
    result = [Candidate(kind, transform(src, kind), 0.0) for kind in kinds]
    result = [Candidate(c.kind, c.payload, _score(c.payload)) for c in result]
    result.sort(key=lambda c: (c.score, int(c.kind), len(c.payload)))
    return result


def best(src: bytes) -> Candidate:
    return rank(src)[0]


def verify(src: bytes, kind: Kind) -> bytes:
    transformed = transform(src, kind)
    restored = inverse(transformed, kind, original_size=len(src))
    if restored != bytes(src):
        raise AssertionError(f"UBIR roundtrip failed for {kind.name}")
    return transformed
