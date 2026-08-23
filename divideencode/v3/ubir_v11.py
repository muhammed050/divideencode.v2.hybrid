"""UBIR V1.1 research candidate.

Goal: preserve the successful UBIR V1 Dictionary+Delta design while reducing
its token/tag/length overhead. This is deliberately separate from V1 until
benchmarks prove a win.
"""
from __future__ import annotations

from . import universal_binary_ir as v1


def _u(n: int) -> bytes:
    return v1._u(n)


def _r(data: bytes, p: int):
    return v1._r(data, p)


def _s(data: bytes) -> bytes:
    return v1._s(data)


def _g(data: bytes, p: int):
    return v1._g(data, p)


def _zz(n: int) -> int:
    return v1._zz(n)


def _uzz(n: int) -> int:
    return v1._uzz(n)

# One compact tag per token. Lengths are implicit for dictionary refs and
# punctuation. Literal strings/raw values remain length-delimited.
PUNCT = 0
DICT = 1
STRING = 2
INT = 3
RAW = 4


def encode_json(data: bytes) -> bytes:
    tokens = v1._json_tokens(data)
    from collections import Counter

    strings = Counter(t for t in tokens if t[:1] == b'"')
    dictionary = sorted(
        (x for x, n in strings.items() if n >= 2),
        key=lambda x: (-strings[x] * len(x), x),
    )
    ids = {x: i for i, x in enumerate(dictionary)}

    # Header: dictionary count + dictionary entries + token count.
    out = bytearray(_u(len(dictionary)))
    for s in dictionary:
        out += _s(s)
    out += _u(len(tokens))

    prev_int = 0
    for t in tokens:
        if t[:1] in b"{}[],:":
            # Encode punctuation directly as one byte. No length prefix.
            out.append(PUNCT)
            out.append(t[0])
        elif t[:1] == b'"':
            i = ids.get(t)
            if i is None:
                out.append(STRING)
                out += _s(t)
            else:
                out.append(DICT)
                out += _u(i)
        elif v1._JSON_INT.fullmatch(t.decode("ascii")):
            out.append(INT)
            value = int(t)
            out += _u(_zz(value - prev_int))
            prev_int = value
        else:
            out.append(RAW)
            out += _s(t)
    return bytes(out)


def decode_json(payload: bytes) -> bytes:
    p = 0
    n, p = _r(payload, p)
    dictionary = []
    for _ in range(n):
        x, p = _g(payload, p)
        dictionary.append(x)
    count, p = _r(payload, p)
    out = bytearray()
    prev_int = 0
    for _ in range(count):
        if p >= len(payload):
            raise ValueError("truncated UBIR V1.1")
        tag = payload[p]
        p += 1
        if tag == PUNCT:
            if p >= len(payload):
                raise ValueError("truncated punctuation")
            out.append(payload[p])
            p += 1
        elif tag == DICT:
            i, p = _r(payload, p)
            if i >= len(dictionary):
                raise ValueError("bad dictionary reference")
            out += dictionary[i]
        elif tag in (STRING, RAW):
            x, p = _g(payload, p)
            out += x
        elif tag == INT:
            z, p = _r(payload, p)
            prev_int += _uzz(z)
            out += str(prev_int).encode("ascii")
        else:
            raise ValueError("unknown UBIR V1.1 tag")
    if p != len(payload):
        raise ValueError("trailing UBIR V1.1 bytes")
    return bytes(out)


def encode(data: bytes, kind: str) -> bytes:
    if kind != "json":
        raise ValueError("UBIR V1.1 currently supports JSON only")
    payload = encode_json(data)
    return v1.MAGIC + bytes([v1.VERSION, v1.K_JSON]) + _u(len(data)) + payload


def decode(blob: bytes) -> bytes:
    if len(blob) < 6 or blob[:4] != v1.MAGIC or blob[4] != v1.VERSION or blob[5] != v1.K_JSON:
        raise ValueError("invalid UBIR V1.1 blob")
    raw, p = _r(blob, 6)
    out = decode_json(blob[p:])
    if len(out) != raw:
        raise ValueError("UBIR V1.1 length mismatch")
    return out
