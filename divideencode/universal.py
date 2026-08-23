"""Content-agnostic adaptive preprocessing for DE2.

The selector is intentionally extension-free. It scores generic reversible
byte transforms by the *final DE2 size*, not by intermediate IR size.
"""
from __future__ import annotations

from dataclasses import dataclass

from .de2 import compress as de2_compress, decompress as de2_decompress

MAGIC = b"DU1"
VERSION = 1


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


def _bitplane(data: bytes) -> bytes:
    n = len(data)
    out = bytearray(n)
    p = 0
    for bit in range(8):
        for x in data:
            out[p] = (x >> bit) & 1
            p += 1
    return bytes(out)


def _unbitplane(data: bytes) -> bytes:
    n = len(data)
    if n == 0:
        return b""
    if n % 8:
        raise ValueError("invalid bitplane payload")
    width = n // 8
    out = bytearray(width)
    p = 0
    for bit in range(8):
        for i in range(width):
            out[i] |= (data[p] & 1) << bit
            p += 1
    return bytes(out)


def _transpose16(data: bytes) -> bytes:
    # Byte-matrix transpose for 16-byte rows. Tail is copied unchanged.
    full = len(data) // 16 * 16
    out = bytearray(full)
    p = 0
    for off in range(0, full, 16):
        row = data[off:off + 16]
        for col in range(16):
            out[p] = row[col]
            p += 1
    return bytes(out) + data[full:]


def _untranspose16(data: bytes) -> bytes:
    full = len(data) // 16 * 16
    out = bytearray(full)
    p = 0
    for off in range(0, full, 16):
        for col in range(16):
            out[off + col] = data[p]
            p += 1
    return bytes(out) + data[full:]


def candidates(data: bytes) -> list[Candidate]:
    """Return generic candidates; no filename/extension classification."""
    data = bytes(data)
    raw = [
        Candidate("identity", 0, data, len(data)),
        Candidate("delta8", 1, _delta(data), len(data)),
        Candidate("xor8", 2, _xor(data), len(data)),
        Candidate("bitplane8", 3, _bitplane(data), len(data)),
        Candidate("transpose16", 4, _transpose16(data), len(data)),
    ]
    return raw


def _inverse(ident: int, data: bytes) -> bytes:
    if ident == 0:
        return data
    if ident == 1:
        return _undelta(data)
    if ident == 2:
        return _unxor(data)
    if ident == 3:
        return _unbitplane(data)
    if ident == 4:
        return _untranspose16(data)
    raise ValueError(f"unknown universal transform {ident}")


def _pack(ident: int, original_size: int, transformed: bytes) -> bytes:
    return MAGIC + bytes((VERSION, ident)) + original_size.to_bytes(8, "little") + transformed


def _unpack(payload: bytes) -> tuple[int, int, bytes]:
    if len(payload) < 13 or payload[:3] != MAGIC or payload[3] != VERSION:
        raise ValueError("invalid universal DE2 payload")
    return payload[4], int.from_bytes(payload[5:13], "little"), payload[13:]


def compress(data: bytes, *, max_candidates: int = 5) -> tuple[bytes, dict]:
    """Select the smallest final DE2 stream among generic reversible transforms."""
    data = bytes(data)
    best_blob = None
    best = None
    for cand in candidates(data)[:max_candidates]:
        packed = _pack(cand.ident, len(data), cand.data)
        blob = de2_compress(packed)
        # Verify every candidate before it can win.
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
