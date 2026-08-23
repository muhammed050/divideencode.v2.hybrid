"""Lossless Adaptive Binary Representation + DE2 experiment codec."""
from __future__ import annotations

from .adaptive_binary import encode as abr_encode, decode as abr_decode, choose_mode
from .de2 import compress as de2_compress, decompress as de2_decompress

MAGIC = b"ABD2"
VERSION = 1
_MODE = {"json": 1, "csv": 2, "text": 3}
_RMODE = {v: k for k, v in _MODE.items()}


def _v(n: int) -> bytes:
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7f) | 0x80); n >>= 7
    out.append(n)
    return bytes(out)


def _rv(b: bytes, p: int):
    n = 0; s = 0
    while True:
        if p >= len(b): raise ValueError("truncated ABD2 header")
        x = b[p]; p += 1; n |= (x & 0x7f) << s
        if not x & 0x80: return n, p
        s += 7
        if s > 63: raise ValueError("ABD2 varint overflow")


def compress(data: bytes, block_size: int = 1 << 20, level: str = "BALANCED") -> bytes:
    data = bytes(data)
    mode = choose_mode(data)
    abr = abr_encode(data, mode)
    payload = de2_compress(abr, block_size=block_size, level=level)
    return MAGIC + bytes((VERSION, _MODE[mode])) + _v(len(data)) + _v(len(abr)) + payload


def decompress(blob: bytes, verify: bool = True) -> bytes:
    if len(blob) < 6 or blob[:4] != MAGIC or blob[4] != VERSION:
        raise ValueError("invalid ABD2 stream")
    mode = _RMODE.get(blob[5])
    if mode is None: raise ValueError("unknown ABD2 mode")
    original, p = _rv(blob, 6)
    abr_len, p = _rv(blob, p)
    abr = de2_decompress(blob[p:], verify=verify)
    if len(abr) != abr_len: raise ValueError("ABD2 representation size mismatch")
    out = abr_decode(abr)
    if len(out) != original: raise ValueError("ABD2 original size mismatch")
    return out
