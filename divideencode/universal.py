"""Content-agnostic adaptive preprocessing for DE2.

The selector is intentionally extension-free. It scores generic reversible
byte transforms by the *final DE2 size*, not by intermediate IR size.
"""
from __future__ import annotations

from dataclasses import dataclass

from .de2 import compress as de2_compress, decompress as de2_decompress

MAGIC = b"DU1"
VERSION = 2


@dataclass(frozen=True)
class Candidate:
    name: str
    ident: int
    data: bytes
    transform_size: int


def _delta(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    prev = 0
    for i, x in enumerate(data):
        out[i] = (x - prev) & 255
        prev = x
    return bytes(out)


def _undelta(data: bytes) -> bytes:
    out = bytearray(len(data))
    prev = 0
    for i, x in enumerate(data):
        prev = (prev + x) & 255
        out[i] = prev
    return bytes(out)


def _xor(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    prev = 0
    for i, x in enumerate(data):
        out[i] = x ^ prev
        prev = x
    return bytes(out)


def _unxor(data: bytes) -> bytes:
    out = bytearray(len(data))
    prev = 0
    for i, x in enumerate(data):
        prev ^= x
        out[i] = prev
    return bytes(out)


def _bittranspose8(data: bytes) -> bytes:
    """Transpose bits inside every 8-byte block without changing size."""
    full = len(data) // 8 * 8
    out = bytearray(len(data))
    for off in range(0, full, 8):
        block = data[off:off + 8]
        for bit in range(8):
            value = 0
            for row in range(8):
                value |= ((block[row] >> bit) & 1) << row
            out[off + bit] = value
    if full != len(data):
        out[full:] = data[full:]
    return bytes(out)


def _unbittranspose8(data: bytes) -> bytes:
    return _bittranspose8(data)


def _transpose16(data: bytes) -> bytes:
    """Transpose each 16x16 byte matrix (256-byte block), preserving size."""
    full = len(data) // 256 * 256
    out = bytearray(len(data))
    for off in range(0, full, 256):
        block = data[off:off + 256]
        for row in range(16):
            base = row * 16
            for col in range(16):
                out[off + col * 16 + row] = block[base + col]
    if full != len(data):
        out[full:] = data[full:]
    return bytes(out)


def _untranspose16(data: bytes) -> bytes:
    return _transpose16(data)


def _rle(data: bytes) -> bytes:
    """Generic byte RLE: each run is encoded as count(1..255), value."""
    if not data:
        return b""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        value = data[i]
        j = i + 1
        limit = min(n, i + 255)
        while j < limit and data[j] == value:
            j += 1
        out.append(j - i)
        out.append(value)
        i = j
    return bytes(out)


def _unrle(data: bytes) -> bytes:
    if len(data) & 1:
        raise ValueError("invalid RLE payload")
    out = bytearray()
    for i in range(0, len(data), 2):
        count = data[i]
        if count == 0:
            raise ValueError("invalid zero-length RLE run")
        out.extend(bytes((data[i + 1],)) * count)
    return bytes(out)


def _shuffle_even_odd(data: bytes) -> bytes:
    """Group even and odd source positions while preserving byte count."""
    return data[::2] + data[1::2]


def _unshuffle_even_odd(data: bytes) -> bytes:
    n = len(data)
    even_n = (n + 1) // 2
    evens = data[:even_n]
    odds = data[even_n:]
    out = bytearray(n)
    out[::2] = evens
    out[1::2] = odds
    return bytes(out)


def candidates(data: bytes) -> list[Candidate]:
    """Return generic candidates; no filename/extension classification."""
    data = bytes(data)
    return [
        Candidate("identity", 0, data, len(data)),
        Candidate("delta8", 1, _delta(data), len(data)),
        Candidate("xor8", 2, _xor(data), len(data)),
        Candidate("bittranspose8", 3, _bittranspose8(data), len(data)),
        Candidate("transpose16", 4, _transpose16(data), len(data)),
        Candidate("rle", 5, _rle(data), len(_rle(data))),
        Candidate("even_odd", 6, _shuffle_even_odd(data), len(data)),
    ]


def _inverse(ident: int, data: bytes) -> bytes:
    if ident == 0:
        return data
    if ident == 1:
        return _undelta(data)
    if ident == 2:
        return _unxor(data)
    if ident == 3:
        return _unbittranspose8(data)
    if ident == 4:
        return _untranspose16(data)
    if ident == 5:
        return _unrle(data)
    if ident == 6:
        return _unshuffle_even_odd(data)
    raise ValueError(f"unknown universal transform {ident}")


def _pack(ident: int, original_size: int, transformed: bytes) -> bytes:
    return MAGIC + bytes((VERSION, ident)) + original_size.to_bytes(8, "little") + transformed


def _unpack(payload: bytes) -> tuple[int, int, bytes]:
    if len(payload) < 13 or payload[:3] != MAGIC or payload[3] != VERSION:
        raise ValueError("invalid universal DE2 payload")
    return payload[4], int.from_bytes(payload[5:13], "little"), payload[13:]


def compress(data: bytes, *, max_candidates: int = 7) -> tuple[bytes, dict]:
    """Select the smallest final DE2 stream among generic reversible transforms."""
    data = bytes(data)
    best_blob = None
    best = None
    for cand in candidates(data)[:max_candidates]:
        packed = _pack(cand.ident, len(data), cand.data)
        blob = de2_compress(packed)
        decoded = de2_decompress(blob)
        ident, original_size, transformed = _unpack(decoded)
        if original_size != len(data) or _inverse(ident, transformed) != data:
            continue
        if best_blob is None or len(blob) < len(best_blob):
            best_blob = blob
            best = cand
    if best_blob is None:
        raise ValueError("no valid universal candidate")
    return best_blob, {
        "transform": best.name,
        "transform_id": best.ident,
        "original_size": len(data),
        "final_size": len(best_blob),
        "ir_size": best.transform_size,
    }


def decompress(blob: bytes, *, verify: bool = True) -> bytes:
    decoded = de2_decompress(blob, verify=verify)
    ident, original_size, transformed = _unpack(decoded)
    data = _inverse(ident, transformed)
    if len(data) != original_size:
        raise ValueError("universal decoded size mismatch")
    return data
