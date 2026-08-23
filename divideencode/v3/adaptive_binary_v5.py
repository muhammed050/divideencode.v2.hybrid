"""ABR5 experimental canonical stream representation.

ABR5 is a new reversible preconditioner: instead of encoding text as one
mixed token stream, it separates token classes into dedicated streams while
keeping a compact shape stream that records how to interleave them again.
Each stream is dictionary-coded independently; integer streams are delta-coded.
The final DE2 size remains the only selection criterion.
"""
from __future__ import annotations
from collections import Counter
import re

MAGIC = b"ABR5"
VERSION = 1
# 0 whitespace, 1 integer, 2 word, 3 punctuation/other
_TOKEN_RE = re.compile(r"\r\n|\n|\r|\s+|\d+|[\w]+|[^\w\s]+", re.UNICODE)


def _u(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative varint")
    out = bytearray()
    while n >= 128:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def _r(b: bytes, p: int) -> tuple[int, int]:
    n = 0; s = 0
    while p < len(b):
        x = b[p]; p += 1
        n |= (x & 127) << s
        if not x & 128:
            return n, p
        s += 7
        if s > 63:
            break
    raise ValueError("invalid varint")


def _zig(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def _unzig(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def _s(x: bytes) -> bytes:
    return _u(len(x)) + x


def _g(b: bytes, p: int) -> tuple[bytes, int]:
    n, p = _r(b, p); e = p + n
    if e > len(b):
        raise ValueError("truncated field")
    return b[p:e], e


def _classify(token: str) -> int:
    if token.isspace():
        return 0
    if token.isascii() and token.isdigit():
        return 1
    if token and all(ch.isalnum() or ch == "_" for ch in token):
        return 2
    return 3


def _pack_shape(classes: list[int]) -> bytes:
    out = bytearray(_u(len(classes)))
    acc = bits = 0
    for c in classes:
        acc |= (c & 3) << bits
        bits += 2
        if bits == 8:
            out.append(acc); acc = bits = 0
    if bits:
        out.append(acc)
    return bytes(out)


def _unpack_shape(b: bytes, p: int, count: int) -> tuple[list[int], int]:
    nbytes = (count + 3) // 4
    raw = b[p:p+nbytes]
    if len(raw) != nbytes:
        raise ValueError("truncated shape")
    p += nbytes; out = []
    for x in raw:
        for shift in (0, 2, 4, 6):
            if len(out) == count:
                break
            out.append((x >> shift) & 3)
    return out, p


def _encode_stream(values: list[str], cls: int) -> bytes:
    counts = Counter(values)
    dictionary = sorted((v for v, n in counts.items() if n >= 2), key=lambda v: (-counts[v], v))
    ids = {v: i for i, v in enumerate(dictionary)}
    out = bytearray(_u(len(values)))
    out += _u(len(dictionary))
    for v in dictionary:
        out += _s(v.encode("utf-8"))
    out += _u(len(values))
    if cls == 1:
        prev = 0
        for v in values:
            n = int(v); out += _u(_zig(n - prev)); prev = n
        return bytes(out)
    for v in values:
        i = ids.get(v)
        if i is None:
            out.append(0); out += _s(v.encode("utf-8"))
        else:
            out.append(1); out += _u(i)
    return bytes(out)


def _decode_stream(b: bytes, p: int, cls: int) -> tuple[list[str], int]:
    count, p = _r(b, p)
    dcount, p = _r(b, p); dictionary = []
    for _ in range(dcount):
        x, p = _g(b, p); dictionary.append(x.decode("utf-8"))
    n, p = _r(b, p)
    if n != count:
        raise ValueError("stream count mismatch")
    out = []
    if cls == 1:
        prev = 0
        for _ in range(n):
            z, p = _r(b, p); prev += _unzig(z); out.append(str(prev))
        return out, p
    for _ in range(n):
        if p >= len(b):
            raise ValueError("truncated stream")
        tag = b[p]; p += 1
        if tag == 0:
            x, p = _g(b, p); out.append(x.decode("utf-8"))
        elif tag == 1:
            i, p = _r(b, p)
            if i >= len(dictionary):
                raise ValueError("bad dictionary reference")
            out.append(dictionary[i])
        else:
            raise ValueError("bad stream tag")
    return out, p


def encode(data: bytes, kind: str = "text") -> bytes:
    if kind not in {"text", "json", "csv"}:
        raise ValueError("ABR5 currently accepts text/json/csv")
    text = data.decode("utf-8")
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return MAGIC + bytes([VERSION]) + _u(len(data)) + _u(0) + b"\0" * 4
    classes = [_classify(t) for t in tokens]
    streams = [[] for _ in range(4)]
    for c, t in zip(classes, tokens):
        streams[c].append(t)
    out = bytearray(MAGIC + bytes([VERSION]) + _u(len(data)))
    out += _u(len(tokens)) + _pack_shape(classes)[1:]
    for c in range(4):
        payload = _encode_stream(streams[c], c)
        out += _u(len(payload)) + payload
    # Kind is metadata only; reconstruction is byte-exact from tokens.
    out.append({"text": 1, "json": 2, "csv": 3}[kind])
    return bytes(out)


def decode(blob: bytes) -> bytes:
    if len(blob) < 5 or blob[:4] != MAGIC or blob[4] != VERSION:
        raise ValueError("bad ABR5 header")
    raw_len, p = _r(blob, 5)
    token_count, p = _r(blob, p)
    classes, p = _unpack_shape(b"\0" + blob[p:], 0, token_count)
    # _unpack_shape above consumed from a synthetic buffer; advance real p.
    shape_bytes = (token_count + 3) // 4
    p += shape_bytes
    streams = []
    for c in range(4):
        size, p = _r(blob, p); end = p + size
        if end > len(blob): raise ValueError("truncated stream payload")
        vals, _ = _decode_stream(blob, p, c); streams.append(vals); p = end
    if p >= len(blob): raise ValueError("missing kind")
    p += 1
    pos = [0, 0, 0, 0]; out = []
    for c in classes:
        if pos[c] >= len(streams[c]): raise ValueError("shape/stream mismatch")
        out.append(streams[c][pos[c]]); pos[c] += 1
    data = "".join(out).encode("utf-8")
    if len(data) != raw_len:
        raise ValueError("ABR5 length mismatch")
    return data


def candidates(data: bytes, suffix: str):
    s = suffix.lower()
    if s in {".json", ".jsonl"}:
        kinds = ["json"]
    elif s == ".csv":
        kinds = ["csv"]
    elif s in {".txt", ".log", ".html", ".css", ".c", ".h", ".cpp", ".py", ".js", ".ts"}:
        kinds = ["text"]
    else:
        return []
    out = []
    for kind in kinds:
        try:
            payload = encode(data, kind)
            if decode(payload) == data:
                out.append((f"abr5:{kind}", payload))
        except (UnicodeDecodeError, ValueError):
            pass
    return out
