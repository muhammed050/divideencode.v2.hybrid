"""UBIR1 — Universal Binary Intermediate Representation for DE2.

The goal is not to compress by itself.  It rewrites arbitrary bytes into a
small set of reversible, DE2-friendly representations and lets a cheap
proxy choose the representation before DE2 sees the data.

Every input is representable.  The IR may grow; that is intentional.  The
important property is that structured files can be rearranged into a form
where DE2 can see locality, repeated bytes, low-valued symbols, or repeated
bit planes instead of the original byte layout.

Transforms:
  DIRECT   : original bytes
  DELTA8   : byte residuals
  XOR8     : adjacent-byte XOR residuals
  NIBBLE   : low/high nibbles separated into two planes
  BITPLANE : eight bit planes, byte-aligned
  TRANSPOSE: fixed-width byte transpose (4/8-byte lanes)

The transform layer is deliberately deterministic and has no filename or
content-type assumptions.  A future version can add dictionaries/token IR
without changing the container contract.
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
    out = bytearray(n)
    half = (n + 1) // 2
    # Low nibbles first, then high nibbles.  Padding is explicit through n.
    for i, b in enumerate(src):
        out[i] = b & 0x0F
        if i + half < n:
            out[i + half] = b >> 4
    return bytes(out)


def _nibble_decode(src: bytes) -> bytes:
    n = len(src)
    out = bytearray(n)
    half = (n + 1) // 2
    for i in range(n):
        lo = src[i] & 0x0F
        hi = src[i + half] & 0x0F if i + half < n else 0
        out[i] = lo | (hi << 4)
    return bytes(out)


def _bitplane_encode(src: bytes) -> bytes:
    n = len(src)
    out = bytearray(n)
    if not src:
        return b""
    # Eight planes, each packed as bytes.  Keeping the same total size makes
    # this transform cheap to frame and avoids bit-level container complexity.
    # For every group of eight source bytes, emit one byte per bit position.
    # This is a true transpose of the 8x8 bit matrix.
    pos = 0
    while pos < n:
        block = src[pos:pos + 8]
        width = len(block)
        for bit in range(8):
            v = 0
            for j, b in enumerate(block):
                if b & (1 << bit):
                    v |= 1 << j
            out[pos + bit] = v
        # For short final blocks, the remaining output bytes are unused by
        # construction; overwrite them deterministically below.
        if width < 8:
            for bit in range(width, 8):
                if pos + bit < n:
                    out[pos + bit] = 0
        pos += 8
    return bytes(out)


def _bitplane_decode(src: bytes) -> bytes:
    n = len(src)
    out = bytearray(n)
    pos = 0
    while pos < n:
        width = min(8, n - pos)
        for bit in range(8):
            packed = src[pos + bit] if pos + bit < n else 0
            for j in range(width):
                if packed & (1 << j):
                    out[pos + j] |= 1 << bit
        pos += 8
    return bytes(out)


def _transpose(src: bytes, width: int) -> bytes:
    n = len(src)
    out = bytearray(n)
    pos = 0
    while pos < n:
        block = src[pos:pos + width]
        for col, b in enumerate(block):
            # Column-major within the block.
            out[pos + col] = b
        # For a scalar byte sequence, transpose only has an effect when we
        # have multiple adjacent records.  The record size is therefore
        # intentionally fixed at width and implemented as a byte matrix.
        if len(block) == width:
            for row in range(width):
                for col in range(width):
                    out[pos + row * width + col] = src[pos + col * width + row] if pos + col * width + row < n else 0
        pos += width * width
    return bytes(out)


def _transpose_decode(src: bytes, width: int) -> bytes:
    n = len(src)
    out = bytearray(src)
    pos = 0
    while pos + width * width <= n:
        for row in range(width):
            for col in range(width):
                out[pos + col * width + row] = src[pos + row * width + col]
        pos += width * width
    return bytes(out)


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
    raise ValueError(f"unknown UBIR kind: {kind}")


def inverse(src: bytes, kind: Kind) -> bytes:
    src = bytes(src)
    if kind == Kind.DIRECT:
        return src
    if kind == Kind.DELTA8:
        return _delta_decode(src)
    if kind == Kind.XOR8:
        return _xor_decode(src)
    if kind == Kind.NIBBLE:
        return _nibble_decode(src)
    if kind == Kind.BITPLANE:
        return _bitplane_decode(src)
    if kind == Kind.TRANSPOSE4:
        return _transpose_decode(src, 4)
    if kind == Kind.TRANSPOSE8:
        return _transpose_decode(src, 8)
    raise ValueError(f"unknown UBIR kind: {kind}")


def _score(data: bytes) -> float:
    """Cheap DE2-friendliness proxy; lower is better.

    It rewards repeated bytes and low-valued bytes without running DE2.
    Sampling is bounded so candidate generation remains fast on huge files.
    """
    if not data:
        return 0.0
    sample = data[: min(len(data), 256 * 1024)]
    counts = [0] * 256
    for b in sample:
        counts[b] += 1
    repeated = sum(c * c for c in counts) / len(sample)
    low = sum(1 for b in sample if b < 16) / len(sample)
    # Consecutive equality is especially useful for DE2's run/repetition paths.
    runs = sum(sample[i] == sample[i - 1] for i in range(1, len(sample))) / max(1, len(sample) - 1)
    return len(sample) / (1.0 + repeated * 0.02 + low * 2.0 + runs * 4.0)


def rank(src: bytes, *, include_direct: bool = True) -> list[Candidate]:
    """Build and rank all universal representations without DE2 trials."""
    src = bytes(src)
    kinds = list(Kind)
    if not include_direct:
        kinds.remove(Kind.DIRECT)
    result = []
    for kind in kinds:
        payload = transform(src, kind)
        result.append(Candidate(kind, payload, _score(payload)))
    result.sort(key=lambda c: (c.score, int(c.kind), len(c.payload)))
    return result


def best(src: bytes) -> Candidate:
    """Return the cheapest-proxy universal representation."""
    return rank(src)[0]


def verify(src: bytes, kind: Kind) -> bytes:
    """Transform and inverse-transform, raising if byte-exactness is lost."""
    transformed = transform(src, kind)
    restored = inverse(transformed, kind)
    if restored != bytes(src):
        raise AssertionError(f"UBIR roundtrip failed for {kind.name}")
    return transformed
