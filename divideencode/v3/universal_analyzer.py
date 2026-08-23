"""Universal analyzer for V3.

The analyzer is intentionally a front-end, not a replacement for DE2. It
classifies the input, builds only reversible representations, and lets the
caller compare those candidates against direct DE2. A representation is
accepted only after an exact round-trip.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from . import universal_binary_ir as ubir

MAGIC = b"UAR1"
VERSION = 1
K_RAW = 0
K_TEXT = 1
K_JSON = 2
K_CSV = 3

_WORD = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")


def _u(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative varint")
    out = bytearray()
    while n >= 128:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def _r(data: bytes, p: int) -> tuple[int, int]:
    n = 0
    shift = 0
    while p < len(data):
        b = data[p]
        p += 1
        n |= (b & 127) << shift
        if not b & 128:
            return n, p
        shift += 7
        if shift > 4096:
            raise ValueError("varint too long")
    raise ValueError("truncated varint")


def _s(x: bytes) -> bytes:
    return _u(len(x)) + x


def _g(data: bytes, p: int) -> tuple[bytes, int]:
    n, p = _r(data, p)
    e = p + n
    if e > len(data):
        raise ValueError("truncated value")
    return data[p:e], e


def _text_like(data: bytes) -> bool:
    if not data:
        return False
    sample = data[: min(len(data), 262144)]
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    bad = sum(1 for b in sample if b < 32 and b not in (9, 10, 13))
    return bad * 100 <= len(sample)


def detect(data: bytes, suffix: str = "") -> str:
    s = suffix.lower()
    if s in {".json", ".jsonl"}:
        try:
            if s == ".json":
                json.loads(data.decode("utf-8"))
            return "json"
        except (UnicodeDecodeError, ValueError):
            pass
    if s == ".csv" and b"," in data:
        return "csv"
    if _text_like(data):
        if s in {".c", ".h", ".cpp", ".hpp", ".py", ".js", ".ts", ".java", ".css", ".html", ".xml", ".sql", ".sh"}:
            return "source"
        return "text"
    return "binary"


def _text_encode(data: bytes) -> bytes:
    """Dictionary-code repeated ASCII identifiers while preserving all bytes."""
    matches = list(_WORD.finditer(data))
    counts = Counter(m.group(0) for m in matches)
    dictionary = sorted(
        (w for w, c in counts.items() if c >= 2 and len(w) >= 3),
        key=lambda w: (-counts[w] * len(w), w),
    )
    ids = {w: i for i, w in enumerate(dictionary)}
    out = bytearray(_u(len(dictionary)))
    for w in dictionary:
        out += _s(w)
    out += _u(len(matches))
    pos = 0
    for m in matches:
        start, end = m.span()
        out += _s(data[pos:start])
        w = m.group(0)
        i = ids.get(w)
        if i is None:
            out.append(0)
            out += _s(w)
        else:
            out.append(1)
            out += _u(i)
        pos = end
    out += _s(data[pos:])
    return bytes(out)


def _text_decode(payload: bytes) -> bytes:
    p = 0
    nd, p = _r(payload, p)
    dictionary = []
    for _ in range(nd):
        w, p = _g(payload, p)
        dictionary.append(w)
    count, p = _r(payload, p)
    out = bytearray()
    for _ in range(count):
        gap, p = _g(payload, p)
        out += gap
        if p >= len(payload):
            raise ValueError("truncated text token")
        tag = payload[p]
        p += 1
        if tag == 0:
            w, p = _g(payload, p)
            out += w
        elif tag == 1:
            i, p = _r(payload, p)
            if i >= len(dictionary):
                raise ValueError("bad text dictionary reference")
            out += dictionary[i]
        else:
            raise ValueError("bad text token tag")
    tail, p = _g(payload, p)
    out += tail
    if p != len(payload):
        raise ValueError("trailing text IR bytes")
    return bytes(out)


def encode(data: bytes, kind: str) -> bytes:
    if kind in {"text", "source"}:
        payload, code = _text_encode(data), K_TEXT
    elif kind == "json":
        payload, code = ubir.encode(data, "json"), K_JSON
    elif kind == "csv":
        payload, code = ubir.encode(data, "csv"), K_CSV
    elif kind == "binary":
        payload, code = data, K_RAW
    else:
        raise ValueError(f"unknown analyzer kind: {kind}")
    return MAGIC + bytes([VERSION, code]) + _u(len(data)) + payload


def decode(blob: bytes) -> bytes:
    if len(blob) < 6 or blob[:4] != MAGIC or blob[4] != VERSION:
        raise ValueError("invalid analyzer header")
    kind = blob[5]
    raw, p = _r(blob, 6)
    payload = blob[p:]
    if kind == K_RAW:
        out = payload
    elif kind == K_TEXT:
        out = _text_decode(payload)
    elif kind in (K_JSON, K_CSV):
        out = ubir.decode(payload)
    else:
        raise ValueError("unknown analyzer representation")
    if len(out) != raw:
        raise ValueError("analyzer length mismatch")
    return out


@dataclass(frozen=True)
class Candidate:
    kind: str
    blob: bytes
    transform_bytes: int


def candidates(data: bytes, suffix: str = "") -> list[Candidate]:
    kind = detect(data, suffix)
    kinds = ["binary"]
    if kind in {"text", "source"}:
        kinds.append(kind)
    elif kind in {"json", "csv"}:
        kinds.append(kind)
    out: list[Candidate] = []
    for k in kinds:
        try:
            blob = encode(data, k)
            if decode(blob) != data:
                continue
            out.append(Candidate(k, blob, len(blob) - len(data)))
        except (ValueError, UnicodeDecodeError):
            continue
    return out


__all__ = ["Candidate", "candidates", "decode", "detect", "encode"]
