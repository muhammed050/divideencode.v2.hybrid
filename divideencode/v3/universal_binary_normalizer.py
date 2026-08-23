"""Universal Binary Normalizer for DE2 experiments.

Goal: turn arbitrary bytes into reversible byte layouts that expose structure
DE2 can exploit. The original bytes are never lost. Each transform is pure,
deterministic, and exactly invertible.

This module deliberately does NOT replace DE2. It supplies candidate IRs and
lets the caller choose the smallest final DE2 container.
"""
from __future__ import annotations

import struct
from typing import Callable

MAGIC = b"UBN1"
HEADER = struct.Struct(">4sBQ")  # magic, transform id, original length


def _identity(data: bytes) -> bytes:
    return data


def _delta(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    prev = 0
    for i, x in enumerate(data):
        out[i] = (x - prev) & 0xFF
        prev = x
    return bytes(out)


def _delta_inv(data: bytes) -> bytes:
    out = bytearray(len(data))
    acc = 0
    for i, x in enumerate(data):
        acc = (acc + x) & 0xFF
        out[i] = acc
    return bytes(out)


def _xor_prev(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    prev = 0
    for i, x in enumerate(data):
        out[i] = x ^ prev
        prev = x
    return bytes(out)


def _xor_prev_inv(data: bytes) -> bytes:
    out = bytearray(len(data))
    acc = 0
    for i, x in enumerate(data):
        acc ^= x
        out[i] = acc
    return bytes(out)


def _nibble(data: bytes) -> bytes:
    n = len(data)
    out = bytearray(n)
    half = (n + 1) // 2
    for i, x in enumerate(data):
        out[i] = x >> 4 if i < half else 0
    # For odd lengths the last low nibble occupies the final byte.
    for i, x in enumerate(data):
        pos = half + i
        if pos < n:
            out[pos] = x & 0x0F
    return bytes(out)


def _nibble_inv(data: bytes) -> bytes:
    n = len(data)
    half = (n + 1) // 2
    out = bytearray(n)
    for i in range(n):
        hi = data[i] if i < half else 0
        lo_pos = half + i
        lo = data[lo_pos] if lo_pos < n else 0
        out[i] = ((hi & 0x0F) << 4) | (lo & 0x0F)
    return bytes(out)


def _bitplane(data: bytes) -> bytes:
    """Transpose each 8-byte group into eight bit planes."""
    out = bytearray()
    for off in range(0, len(data), 8):
        block = data[off:off + 8]
        if len(block) < 8:
            block = block + b"\0" * (8 - len(block))
        for bit in range(8):
            v = 0
            for j, x in enumerate(block):
                v |= ((x >> bit) & 1) << j
            out.append(v)
    return bytes(out)


def _bitplane_inv(data: bytes, original_len: int) -> bytes:
    out = bytearray()
    for off in range(0, len(data), 8):
        planes = data[off:off + 8]
        if len(planes) < 8:
            planes = planes + b"\0" * (8 - len(planes))
        for j in range(8):
            x = 0
            for bit in range(8):
                x |= ((planes[bit] >> j) & 1) << bit
            out.append(x)
    return bytes(out[:original_len])


def _transpose16(data: bytes) -> bytes:
    """16x16 byte-matrix transpose, zero-padding only the last block."""
    out = bytearray()
    for off in range(0, len(data), 256):
        block = data[off:off + 256]
        size = len(block)
        if size < 256:
            block += b"\0" * (256 - size)
        for c in range(16):
            for r in range(16):
                out.append(block[r * 16 + c])
    return bytes(out)


def _transpose16_inv(data: bytes, original_len: int) -> bytes:
    out = bytearray()
    for off in range(0, len(data), 256):
        block = data[off:off + 256]
        if len(block) < 256:
            block += b"\0" * (256 - len(block))
        dst = bytearray(256)
        k = 0
        for c in range(16):
            for r in range(16):
                dst[r * 16 + c] = block[k]
                k += 1
        out.extend(dst)
    return bytes(out[:original_len])


def _rle8(data: bytes) -> bytes:
    """Simple count/value RLE; always reversible, useful for long runs."""
    if not data:
        return b""
    out = bytearray()
    i = 0
    while i < len(data):
        x = data[i]
        j = i + 1
        while j < len(data) and data[j] == x and j - i < 256:
            j += 1
        out.append(j - i - 1)
        out.append(x)
        i = j
    return bytes(out)


def _rle8_inv(data: bytes, original_len: int) -> bytes:
    if len(data) & 1:
        raise ValueError("invalid UBN RLE payload")
    out = bytearray()
    for i in range(0, len(data), 2):
        out.extend(bytes((data[i + 1],)) * (data[i] + 1))
    if len(out) != original_len:
        raise ValueError("UBN RLE length mismatch")
    return bytes(out)


TRANSFORMS: dict[str, tuple[int, Callable[[bytes], bytes], Callable[[bytes, int], bytes]]] = {
    "raw": (0, _identity, lambda b, n: b),
    "delta8": (1, _delta, lambda b, n: _delta_inv(b)),
    "xor8": (2, _xor_prev, lambda b, n: _xor_prev_inv(b)),
    "nibble": (3, _nibble, lambda b, n: _nibble_inv(b)),
    "bitplane8": (4, _bitplane, _bitplane_inv),
    "transpose16": (5, _transpose16, _transpose16_inv),
    "rle8": (6, _rle8, _rle8_inv),
}
BY_ID = {v[0]: (name, v[1], v[2]) for name, v in TRANSFORMS.items()}


def candidates(data: bytes) -> list[tuple[str, bytes]]:
    data = bytes(data)
    return [(name, fn(data)) for name, (_id, fn, _inv) in TRANSFORMS.items()]


def pack(transform: str, transformed: bytes, original_len: int) -> bytes:
    tid = TRANSFORMS[transform][0]
    return HEADER.pack(MAGIC, tid, original_len) + transformed


def unpack(blob: bytes) -> tuple[str, bytes, int]:
    if len(blob) < HEADER.size:
        raise ValueError("UBN blob too short")
    magic, tid, original_len = HEADER.unpack(blob[:HEADER.size])
    if magic != MAGIC or tid not in BY_ID:
        raise ValueError("invalid UBN header")
    name, _fn, inv = BY_ID[tid]
    return name, blob[HEADER.size:], original_len


def restore(blob: bytes) -> bytes:
    name, transformed, original_len = unpack(blob)
    _id, _fn, inv = TRANSFORMS[name]
    out = inv(transformed, original_len)
    if len(out) != original_len:
        raise ValueError(f"{name} produced {len(out)} bytes, expected {original_len}")
    return out
