"""DE2 external-symbol numeric transform.

The codebook is fixed globally: byte value N always has symbol ID N.
Therefore the compressed stream does not need to store a per-file dictionary.

Two representations are provided:
- IDs: the canonical 0..255 symbol IDs (same information as the input bytes).
- decimal digits: each symbol ID is rendered as a fixed 3-digit decimal number.

The decimal form intentionally expands the data before DE2.  The purpose is
experimental: it tests whether exposing repeated decimal digits gives DE2 a
better stream.  Compression always falls back to direct DE2 when the numeric
representation loses.
"""
from __future__ import annotations

import struct
from .codec import compress as de2_compress, decompress as de2_decompress

MAGIC = b"DE2X"
VERSION = 1

# External/global codebook.  No table is serialized: byte N <-> symbol ID N.
SYMBOL_COUNT = 256


def to_ids(data: bytes) -> bytes:
    return bytes(data)


def from_ids(ids: bytes) -> bytes:
    return bytes(ids)


def to_decimal_digits(data: bytes) -> bytes:
    """Map every byte to exactly three ASCII decimal digits (000..255)."""
    out = bytearray(len(data) * 3)
    j = 0
    for value in data:
        out[j] = 48 + value // 100
        out[j + 1] = 48 + (value // 10) % 10
        out[j + 2] = 48 + value % 10
        j += 3
    return bytes(out)


def from_decimal_digits(digits: bytes, original_len: int) -> bytes:
    if len(digits) != original_len * 3:
        raise ValueError("invalid decimal digit stream length")
    out = bytearray(original_len)
    j = 0
    for i in range(original_len):
        a, b, c = digits[j], digits[j + 1], digits[j + 2]
        if not (48 <= a <= 50 and 48 <= b <= 57 and 48 <= c <= 57):
            raise ValueError("invalid decimal symbol digits")
        value = (a - 48) * 100 + (b - 48) * 10 + (c - 48)
        if value > 255:
            raise ValueError("decimal symbol outside byte range")
        out[i] = value
        j += 3
    return bytes(out)


def transform(data: bytes) -> tuple[str, bytes]:
    """Return the cheaper-to-encode exposed representation."""
    raw = bytes(data)
    ids = to_ids(raw)
    digits = to_decimal_digits(raw)
    direct = de2_compress(ids)
    numeric = de2_compress(digits)
    if len(numeric) < len(direct):
        return "digits", digits
    return "ids", ids


def compress(data: bytes) -> bytes:
    raw = bytes(data)
    direct = de2_compress(raw)
    digits = to_decimal_digits(raw)
    numeric = de2_compress(digits)

    # Header contains only representation + original length.  The global
    # symbol dictionary is implicit and never occupies bytes in the stream.
    if len(numeric) + 9 < len(direct) + 9:
        return MAGIC + bytes((VERSION, 1)) + struct.pack("<I", len(raw)) + numeric
    return MAGIC + bytes((VERSION, 0)) + struct.pack("<I", len(raw)) + direct


def decompress(blob: bytes) -> bytes:
    if len(blob) < 10 or blob[:4] != MAGIC or blob[4] != VERSION:
        raise ValueError("invalid DE2X blob")
    mode = blob[5]
    original_len = struct.unpack_from("<I", blob, 6)[0]
    payload = de2_decompress(blob[10:])
    if mode == 0:
        if len(payload) != original_len:
            raise ValueError("invalid ID payload length")
        return from_ids(payload)
    if mode == 1:
        return from_decimal_digits(payload, original_len)
    raise ValueError("unsupported DE2X mode")


__all__ = [
    "SYMBOL_COUNT", "to_ids", "from_ids", "to_decimal_digits",
    "from_decimal_digits", "transform", "compress", "decompress",
]
