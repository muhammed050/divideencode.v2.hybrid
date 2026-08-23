"""Content-agnostic adaptive preprocessing for DE2.

The selector is extension-free: it measures the final DE2 stream and keeps only
reversible transforms that actually improve the end-to-end result.
"""
from __future__ import annotations

from collections import Counter
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


def _u(n: int) -> bytes:
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _r(data: bytes, p: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if p >= len(data) or shift > 63:
            raise ValueError("invalid varint")
        b = data[p]
        p += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, p
        shift += 7


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
    out[full:] = data[full:]
    return bytes(out)


def _untranspose16(data: bytes) -> bytes:
    return _transpose16(data)


def _rle(data: bytes) -> bytes:
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
    return data[::2] + data[1::2]


def _unshuffle_even_odd(data: bytes) -> bytes:
    n = len(data)
    even_n = (n + 1) // 2
    out = bytearray(n)
    out[::2] = data[:even_n]
    out[1::2] = data[even_n:]
    return bytes(out)


def _char_class(x: int) -> int:
    # Generic lexical classes; deliberately no file-format knowledge.
    if x in (9, 10, 13, 32):
        return 0  # whitespace
    if 48 <= x <= 57 or 65 <= x <= 90 or 97 <= x <= 122 or x >= 128:
        return 1  # word/text byte
    if x < 32:
        return 3  # control/raw
    return 2  # punctuation/symbol


def _lex_tokens(data: bytes) -> list[bytes]:
    if not data:
        return []
    tokens: list[bytes] = []
    start = 0
    cls = _char_class(data[0])
    for i in range(1, len(data)):
        c = _char_class(data[i])
        # Punctuation is deliberately kept as single-byte tokens. This exposes
        # repeated structural delimiters to DE2 without assuming JSON/CSV/etc.
        boundary = c != cls or cls == 2 or cls == 3
        if boundary:
            tokens.append(data[start:i])
            start = i
            cls = c
    tokens.append(data[start:])
    return tokens


def _token_dict(data: bytes) -> bytes:
    """Universal lexical dictionary transform.

    Repeated word/text and whitespace runs become dictionary references while
    unique tokens remain literal. The transform is lossless and format agnostic.
    """
    tokens = _lex_tokens(data)
    counts = Counter(t for t in tokens if len(t) >= 3)
    dictionary = [t for t, n in counts.items() if n >= 2]
    # Prefer high total savings, then deterministic lexical order.
    dictionary.sort(key=lambda t: (-(counts[t] * (len(t) - 2)), -len(t), t))
    dictionary = dictionary[:1024]
    ids = {t: i for i, t in enumerate(dictionary)}

    out = bytearray(b"TD2")
    out += _u(len(dictionary))
    for token in dictionary:
        out += _u(len(token)) + token
    out += _u(len(tokens))
    for token in tokens:
        idx = ids.get(token)
        if idx is not None:
            out.append(1)
            out += _u(idx)
        else:
            out.append(0)
            out += _u(len(token)) + token
    return bytes(out)


def _untoken_dict(data: bytes) -> bytes:
    if len(data) < 3 or data[:3] != b"TD2":
        raise ValueError("invalid token dictionary payload")
    p = 3
    n, p = _r(data, p)
    dictionary = []
    for _ in range(n):
        size, p = _r(data, p)
        if p + size > len(data):
            raise ValueError("truncated token dictionary")
        dictionary.append(data[p:p + size])
        p += size
    count, p = _r(data, p)
    out = bytearray()
    for _ in range(count):
        if p >= len(data):
            raise ValueError("truncated token stream")
        tag = data[p]
        p += 1
        if tag == 1:
            idx, p = _r(data, p)
            if idx >= len(dictionary):
                raise ValueError("bad token dictionary reference")
            out += dictionary[idx]
        elif tag == 0:
            size, p = _r(data, p)
            if p + size > len(data):
                raise ValueError("truncated literal token")
            out += data[p:p + size]
            p += size
        else:
            raise ValueError("unknown token stream tag")
    if p != len(data):
        raise ValueError("trailing token dictionary bytes")
    return bytes(out)


def candidates(data: bytes) -> list[Candidate]:
    """Return generic candidates; no extension-based routing."""
    data = bytes(data)
    rle = _rle(data)
    td = _token_dict(data)
    return [
        Candidate("identity", 0, data, len(data)),
        Candidate("delta8", 1, _delta(data), len(data)),
        Candidate("xor8", 2, _xor(data), len(data)),
        Candidate("bittranspose8", 3, _bittranspose8(data), len(data)),
        Candidate("transpose16", 4, _transpose16(data), len(data)),
        Candidate("rle", 5, rle, len(rle)),
        Candidate("even_odd", 6, _shuffle_even_odd(data), len(data)),
        Candidate("token_dict", 7, td, len(td)),
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
    if ident == 7:
        return _untoken_dict(data)
    raise ValueError(f"unknown universal transform {ident}")


def _pack(ident: int, original_size: int, transformed: bytes) -> bytes:
    return MAGIC + bytes((VERSION, ident)) + original_size.to_bytes(8, "little") + transformed


def _unpack(payload: bytes) -> tuple[int, int, bytes]:
    if len(payload) < 13 or payload[:3] != MAGIC or payload[3] != VERSION:
        raise ValueError("invalid universal DE2 payload")
    return payload[4], int.from_bytes(payload[5:13], "little"), payload[13:]


def compress(data: bytes, *, max_candidates: int = 8) -> tuple[bytes, dict]:
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
