"""Experimental symbol-ID transform for DE2."""
from __future__ import annotations
import struct
from .codec import compress as de2_compress, decompress as de2_decompress

MAGIC = b"DE2I"
VERSION = 1


def _encode_ids(data: bytes):
    ids = {}
    dictionary = bytearray()
    stream = bytearray(len(data))
    for i, b in enumerate(data):
        sid = ids.get(b)
        if sid is None:
            sid = len(dictionary)
            ids[b] = sid
            dictionary.append(b)
        stream[i] = sid
    return bytes(stream), bytes(dictionary)


def transform(data: bytes):
    """Return (ordered symbol-ID stream, symbol dictionary)."""
    return _encode_ids(bytes(data))


def inverse(stream: bytes, dictionary: bytes, original_len: int) -> bytes:
    if len(stream) != original_len:
        raise ValueError("invalid DE2I stream length")
    if any(x >= len(dictionary) for x in stream):
        raise ValueError("invalid DE2I symbol id")
    return bytes(dictionary[x] for x in stream)


def compress(data: bytes) -> bytes:
    raw = bytes(data)
    ids, dictionary = _encode_ids(raw)
    transformed = de2_compress(ids)
    candidate = (MAGIC + bytes((VERSION,)) +
                 struct.pack("<HI", len(dictionary), len(raw)) +
                 dictionary + transformed)
    direct = de2_compress(raw)
    fallback = MAGIC + b"\x00" + struct.pack("<I", len(raw)) + direct
    return candidate if len(candidate) < len(fallback) else fallback


def decompress(blob: bytes) -> bytes:
    if len(blob) < 9 or blob[:4] != MAGIC:
        raise ValueError("invalid DE2I blob")
    mode = blob[4]
    if mode == 0:
        original_len = struct.unpack_from("<I", blob, 5)[0]
        out = de2_decompress(blob[9:])
        if len(out) != original_len:
            raise ValueError("invalid DE2I direct length")
        return out
    if mode != VERSION or len(blob) < 11:
        raise ValueError("unsupported DE2I version")
    dict_len, original_len = struct.unpack_from("<HI", blob, 5)
    start = 11
    end = start + dict_len
    if end > len(blob):
        raise ValueError("truncated DE2I dictionary")
    dictionary = blob[start:end]
    ids = de2_decompress(blob[end:])
    return inverse(ids, dictionary, original_len)


__all__ = ["compress", "decompress", "transform", "inverse"]
