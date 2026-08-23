"""Adaptive Binary Representation (ABR) preconditioner.

ABR is a deterministic, lossless preconditioner for structured JSON/CSV/text.
It does not claim to compress by itself: the caller should keep the ABR form
only when the complete downstream compressed result is smaller than direct
compression.
"""
from __future__ import annotations

import re
from collections import Counter

MAGIC = b"ABR1"
K_TEXT, K_CSV, K_JSON = 1, 2, 3
_TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]+", re.UNICODE)


def _u(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative varint")
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _r(buf: bytes, p: int) -> tuple[int, int]:
    n = 0
    shift = 0
    while p < len(buf):
        b = buf[p]
        p += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, p
        shift += 7
        if shift > 63:
            break
    raise ValueError("truncated/invalid varint")


def _put(out: bytearray, b: bytes) -> None:
    out += _u(len(b))
    out += b


def _get(buf: bytes, p: int) -> tuple[bytes, int]:
    n, p = _r(buf, p)
    end = p + n
    if end > len(buf):
        raise ValueError("truncated byte string")
    return buf[p:end], end


def _tokens(text: str) -> list[str]:
    """Split Unicode text into semantic runs without losing any byte."""
    return _TOKEN_RE.findall(text)


def _dictionary(tokens: list[str]) -> tuple[list[str], dict[str, int]]:
    counts = Counter(tokens)
    entries = [x for x, n in counts.items() if n >= 2]
    entries.sort(key=lambda x: (-counts[x] * len(x), x))
    return entries, {x: i for i, x in enumerate(entries)}


def _encode_tokens(tokens: list[str]) -> bytes:
    entries, ids = _dictionary(tokens)
    out = bytearray(_u(len(entries)))
    for x in entries:
        _put(out, x.encode("utf-8"))
    for x in tokens:
        i = ids.get(x)
        if i is None:
            out.append(0)
            _put(out, x.encode("utf-8"))
        else:
            out.append(1)
            out += _u(i)
    return bytes(out)


def _decode_tokens(buf: bytes, p: int) -> tuple[str, int]:
    n, p = _r(buf, p)
    entries = []
    for _ in range(n):
        b, p = _get(buf, p)
        entries.append(b.decode("utf-8"))
    out = []
    while p < len(buf):
        tag = buf[p]
        p += 1
        if tag == 0:
            b, p = _get(buf, p)
            out.append(b.decode("utf-8"))
        elif tag == 1:
            i, p = _r(buf, p)
            if i >= len(entries):
                raise ValueError("invalid dictionary reference")
            out.append(entries[i])
        else:
            raise ValueError("invalid token tag")
    return "".join(out), p


def encode(data: bytes, kind: str) -> bytes:
    """Encode exact source bytes as a reversible dictionary-indexed stream.

    JSON and CSV deliberately use the same lexical core here.  That keeps
    whitespace, quoting, line endings, number spelling, and every other byte
    exactly intact while still exposing repeated words/runs to DE2.
    """
    if kind not in {"text", "csv", "json"}:
        raise ValueError("kind must be text, csv, or json")
    text = data.decode("utf-8")
    code = {"text": K_TEXT, "csv": K_CSV, "json": K_JSON}[kind]
    payload = _encode_tokens(_tokens(text))
    return MAGIC + bytes([code]) + _u(len(data)) + payload


def decode(blob: bytes) -> bytes:
    if len(blob) < 5 or blob[:4] != MAGIC:
        raise ValueError("invalid ABR header")
    code = blob[4]
    if code not in {K_TEXT, K_CSV, K_JSON}:
        raise ValueError("unknown ABR kind")
    raw_len, p = _r(blob, 5)
    text, p = _decode_tokens(blob, p)
    if p != len(blob):
        raise ValueError("trailing ABR data")
    out = text.encode("utf-8")
    if len(out) != raw_len:
        raise ValueError("ABR length mismatch")
    return out


def candidates(data: bytes, suffix: str) -> list[tuple[str, bytes]]:
    s = suffix.lower()
    if s == ".csv":
        kinds = ["csv"]
    elif s in {".json", ".jsonl"}:
        kinds = ["json"]
    elif s in {".txt", ".log", ".html", ".css", ".c", ".h", ".cpp", ".py", ".js", ".ts"}:
        kinds = ["text"]
    else:
        kinds = []
    out = []
    for kind in kinds:
        try:
            b = encode(data, kind)
            if decode(b) == data:
                out.append((kind, b))
        except (UnicodeDecodeError, ValueError):
            pass
    return out
