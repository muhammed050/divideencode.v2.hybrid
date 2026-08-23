"""Adaptive Binary Representation (ABR) preconditioner.

ABR is a deterministic, lossless preconditioner for structured JSON/CSV/text.
It does not claim to compress by itself: the caller should keep the ABR form
only when the complete downstream compressed result is smaller than direct
compression.
"""
from __future__ import annotations

import csv
import io
import json
import re
import struct
from collections import Counter

MAGIC = b"ABR1"
K_TEXT, K_CSV, K_JSON = 1, 2, 3


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


# Semantic text runs: words, whitespace runs, or punctuation runs.
_TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
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


def _csv_encode(text: str) -> bytes:
    rows = list(csv.reader(io.StringIO(text, newline="")))
    cells = [c for row in rows for c in row]
    entries, ids = _dictionary(cells)
    out = bytearray(_u(len(rows)))
    out += _u(len(entries))
    for x in entries:
        _put(out, x.encode("utf-8"))
    for row in rows:
        out += _u(len(row))
        for x in row:
            i = ids.get(x)
            if i is None:
                out.append(0)
                _put(out, x.encode("utf-8"))
            else:
                out.append(1)
                out += _u(i)
    return bytes(out)


def _csv_decode(buf: bytes, p: int) -> tuple[str, int]:
    nr, p = _r(buf, p)
    nd, p = _r(buf, p)
    entries = []
    for _ in range(nd):
        b, p = _get(buf, p)
        entries.append(b.decode("utf-8"))
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    for _ in range(nr):
        nc, p = _r(buf, p)
        row = []
        for _ in range(nc):
            tag = buf[p]
            p += 1
            if tag == 0:
                b, p = _get(buf, p)
                row.append(b.decode("utf-8"))
            elif tag == 1:
                i, p = _r(buf, p)
                if i >= len(entries):
                    raise ValueError("invalid CSV dictionary reference")
                row.append(entries[i])
            else:
                raise ValueError("invalid CSV tag")
        writer.writerow(row)
    return out.getvalue(), p


def _json_collect(v, counts: Counter[str]) -> None:
    if isinstance(v, str):
        counts[v] += 1
    elif isinstance(v, list):
        for x in v:
            _json_collect(x, counts)
    elif isinstance(v, dict):
        for k, x in v.items():
            counts[k] += 1
            _json_collect(x, counts)


def _json_put(v, ids, out: bytearray) -> None:
    if v is None:
        out.append(0)
    elif v is False:
        out.append(1)
    elif v is True:
        out.append(2)
    elif isinstance(v, int) and not isinstance(v, bool):
        out.append(3)
        z = (v << 1) if v >= 0 else ((-v << 1) - 1)
        out += _u(z)
    elif isinstance(v, float):
        out.append(4)
        out += struct.pack("<d", v)
    elif isinstance(v, str):
        out.append(5)
        out += _u(ids[v])
    elif isinstance(v, list):
        out.append(6)
        out += _u(len(v))
        for x in v:
            _json_put(x, ids, out)
    elif isinstance(v, dict):
        out.append(7)
        out += _u(len(v))
        for k, x in v.items():
            out += _u(ids[k])
            _json_put(x, ids, out)
    else:
        raise TypeError(f"unsupported JSON type: {type(v).__name__}")


def _json_get(buf: bytes, p: int, entries):
    if p >= len(buf):
        raise ValueError("truncated JSON value")
    tag = buf[p]
    p += 1
    if tag == 0: return None, p
    if tag == 1: return False, p
    if tag == 2: return True, p
    if tag == 3:
        z, p = _r(buf, p)
        return (z >> 1) if not z & 1 else -((z >> 1) + 1), p
    if tag == 4:
        if p + 8 > len(buf): raise ValueError("truncated float")
        return struct.unpack("<d", buf[p:p + 8])[0], p + 8
    if tag == 5:
        i, p = _r(buf, p)
        if i >= len(entries): raise ValueError("invalid JSON string reference")
        return entries[i], p
    if tag == 6:
        n, p = _r(buf, p)
        arr = []
        for _ in range(n):
            x, p = _json_get(buf, p, entries)
            arr.append(x)
        return arr, p
    if tag == 7:
        n, p = _r(buf, p)
        obj = {}
        for _ in range(n):
            i, p = _r(buf, p)
            if i >= len(entries): raise ValueError("invalid JSON key reference")
            x, p = _json_get(buf, p, entries)
            obj[entries[i]] = x
        return obj, p
    raise ValueError("invalid JSON tag")


def encode(data: bytes, kind: str) -> bytes:
    text = data.decode("utf-8")
    if kind == "text":
        payload = _encode_tokens(_tokens(text))
        code = K_TEXT
    elif kind == "csv":
        payload = _csv_encode(text)
        code = K_CSV
    elif kind == "json":
        value = json.loads(text)
        counts = Counter()
        _json_collect(value, counts)
        entries = [x for x, n in counts.items() if n >= 2]
        entries.sort(key=lambda x: (-counts[x] * len(x), x))
        ids = {x: i for i, x in enumerate(entries)}
        out = bytearray(_u(len(entries)))
        for x in entries:
            _put(out, x.encode("utf-8"))
        _json_put(value, ids, out)
        payload = bytes(out)
        code = K_JSON
    else:
        raise ValueError("kind must be text, csv, or json")
    return MAGIC + bytes([code]) + _u(len(data)) + payload


def decode(blob: bytes) -> bytes:
    if len(blob) < 5 or blob[:4] != MAGIC:
        raise ValueError("invalid ABR header")
    code = blob[4]
    raw_len, p = _r(blob, 5)
    if code == K_TEXT:
        text, p = _decode_tokens(blob, p)
    elif code == K_CSV:
        text, p = _csv_decode(blob, p)
    elif code == K_JSON:
        nd, p = _r(blob, p)
        entries = []
        for _ in range(nd):
            b, p = _get(blob, p)
            entries.append(b.decode("utf-8"))
        value, p = _json_get(blob, p, entries)
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        raise ValueError("unknown ABR kind")
    if p != len(blob):
        raise ValueError("trailing ABR data")
    out = text.encode("utf-8")
    if len(out) != raw_len:
        raise ValueError("ABR length mismatch")
    return out


def candidates(data: bytes, suffix: str) -> list[tuple[str, bytes]]:
    s = suffix.lower()
    kinds = []
    if s == ".csv":
        kinds.append("csv")
    elif s in {".json", ".jsonl"}:
        kinds.append("json")
    elif s in {".txt", ".log", ".html", ".css", ".c", ".h", ".cpp", ".py", ".js", ".ts"}:
        kinds.append("text")
    out = []
    for kind in kinds:
        try:
            b = encode(data, kind)
            if decode(b) == data:
                out.append((kind, b))
        except Exception:
            pass
    return out
