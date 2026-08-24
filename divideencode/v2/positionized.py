"""DE2 positionized symbol transform.

Stores each distinct byte once, then records the positions where that byte
occurs as delta-coded integer positions. The repeated symbol identity is
represented by a dictionary while positions become a numeric stream.
"""
from __future__ import annotations
import struct
from .codec import compress as de2_compress, decompress as de2_decompress

MAGIC = b"DE2P"
VERSION = 2


def _uvarint(n: int) -> bytes:
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _read_uvarint(buf: bytes, off: int):
    value = 0
    shift = 0
    while off < len(buf):
        b = buf[off]
        off += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, off
        shift += 7
        if shift > 63:
            raise ValueError("invalid varint")
    raise ValueError("truncated varint")


def _build(data: bytes):
    positions = [[] for _ in range(256)]
    for pos, b in enumerate(data):
        positions[b].append(pos)

    dictionary = bytearray()
    stream = bytearray()
    for symbol, poslist in enumerate(positions):
        if not poslist:
            continue
        dictionary.append(symbol)
        stream += _uvarint(len(poslist))
        prev = -1
        for pos in poslist:
            stream += _uvarint(pos - prev - 1)
            prev = pos
    return bytes(dictionary), bytes(stream)


def _restore(dictionary: bytes, stream: bytes, original_len: int) -> bytes:
    out = bytearray(original_len)
    off = 0
    used = 0
    for symbol in dictionary:
        count, off = _read_uvarint(stream, off)
        pos = -1
        for _ in range(count):
            gap, off = _read_uvarint(stream, off)
            pos += gap + 1
            if pos >= original_len:
                raise ValueError("position outside original stream")
            out[pos] = symbol
            used += 1
    if used != original_len or off != len(stream):
        raise ValueError("invalid positionized stream")
    return bytes(out)


def transform(data: bytes):
    return _build(bytes(data))


def inverse(dictionary: bytes, stream: bytes, original_len: int) -> bytes:
    return _restore(dictionary, stream, original_len)


def compress(data: bytes) -> bytes:
    raw = bytes(data)
    dictionary, positions = _build(raw)
    packed_positions = de2_compress(positions)
    candidate = (MAGIC + bytes((VERSION,)) +
                 struct.pack("<BI", len(dictionary), len(raw)) +
                 dictionary + packed_positions)
    direct = de2_compress(raw)
    fallback = MAGIC + b"\x00" + struct.pack("<I", len(raw)) + direct
    return candidate if len(candidate) < len(fallback) else fallback


def decompress(blob: bytes) -> bytes:
    if len(blob) < 9 or blob[:4] != MAGIC:
        raise ValueError("invalid DE2P blob")
    mode = blob[4]
    if mode == 0:
        original_len = struct.unpack_from("<I", blob, 5)[0]
        out = de2_decompress(blob[9:])
        if len(out) != original_len:
            raise ValueError("invalid direct length")
        return out
    if mode != VERSION or len(blob) < 10:
        raise ValueError("unsupported DE2P version")
    dict_len, original_len = struct.unpack_from("<BI", blob, 5)
    start = 10
    end = start + dict_len
    if end > len(blob):
        raise ValueError("truncated dictionary")
    positions = de2_decompress(blob[end:])
    return _restore(blob[start:end], positions, original_len)


__all__ = ["compress", "decompress", "transform", "inverse"]
