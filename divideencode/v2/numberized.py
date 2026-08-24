"""DE2 Numberized experiment: symbols -> one integer -> DE2.

This implements the requested arithmetic representation literally:
1. Every byte is its global symbol ID (0..255).
2. The complete symbol stream is interpreted as ONE base-256 integer.
3. The integer is represented in a compact unsigned form (no leading zeroes).
4. The original byte length is stored so the inverse operation is exact.
5. DE2 compresses that integer representation.

The global dictionary is implicit: symbol ID N == byte value N, so no per-file
symbol dictionary is stored.

Important: this is a reversible representation experiment, not a claim that
arithmetic conversion creates information-theoretic compression. It lets the
benchmark test the exact idea without silently changing the data.
"""
from __future__ import annotations

import struct
from .codec import compress as de2_compress, decompress as de2_decompress

MAGIC = b"DE2N"
VERSION = 1


def symbols_to_integer(data: bytes) -> int:
    """Interpret the entire symbol stream as one base-256 integer."""
    return int.from_bytes(data, "big", signed=False)


def integer_to_symbols(value: int, length: int) -> bytes:
    """Inverse of symbols_to_integer, restoring exactly `length` symbols."""
    if value < 0:
        raise ValueError("integer must be non-negative")
    if length < 0:
        raise ValueError("length must be non-negative")
    if value >= (1 << (8 * length)):
        raise ValueError("integer does not fit requested symbol length")
    return value.to_bytes(length, "big")


def integer_bytes(value: int) -> bytes:
    """Minimal unsigned representation of an integer, with zero as one byte."""
    if value < 0:
        raise ValueError("integer must be non-negative")
    n = max(1, (value.bit_length() + 7) // 8)
    return value.to_bytes(n, "big")


def pack_number(data: bytes) -> bytes:
    """Store the single integer in minimal big-endian bytes."""
    return integer_bytes(symbols_to_integer(bytes(data)))


def unpack_number(payload: bytes, original_len: int) -> bytes:
    return integer_to_symbols(int.from_bytes(payload, "big"), original_len)


def compress(data: bytes) -> bytes:
    raw = bytes(data)
    number = pack_number(raw)
    payload = de2_compress(number)
    # Header: magic + version + original length + number-byte length.
    return MAGIC + bytes((VERSION,)) + struct.pack("<II", len(raw), len(number)) + payload


def decompress(blob: bytes) -> bytes:
    if len(blob) < 13 or blob[:4] != MAGIC or blob[4] != VERSION:
        raise ValueError("invalid DE2N blob")
    original_len, number_len = struct.unpack_from("<II", blob, 5)
    number = de2_decompress(blob[13:])
    if len(number) != number_len:
        raise ValueError("invalid number payload length")
    return unpack_number(number, original_len)


__all__ = [
    "symbols_to_integer", "integer_to_symbols", "integer_bytes",
    "pack_number", "unpack_number", "compress", "decompress",
]
