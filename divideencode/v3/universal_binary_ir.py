"""Universal Binary IR (UBIR) experiment for V3.

A reversible, self-describing intermediate representation for structured
JSON and canonical CSV. DE2 remains the entropy backend; callers select UBIR
only when the final DE2 stream is smaller than direct DE2.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter

MAGIC = b"UBIR"
VERSION = 1
K_JSON = 1
K_CSV = 2

J_PUNCT = 1
J_STRING = 2
J_INT = 3
J_RAW = 4
J_DICT = 5

_JSON_TOKEN = re.compile(
    rb'(?:[ \t\r\n]+|[{}\[\],:]|"(?:\\.|[^"\\])*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)'
)
_JSON_INT = re.compile(r"^-?(?:0|[1-9][0-9]*)$")


def _u(n: int) -> bytes:
    if n < 0:
        raise ValueError("unsigned varint cannot encode negative values")
    out = bytearray()
    while n >= 128:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _r(data: bytes, p: int) -> tuple[int, int]:
    n = 0
    shift = 0
    while p < len(data):
        b = data[p]
        p += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, p
        shift += 7
        if shift > 4096:
            raise ValueError("varint too long")
    raise ValueError("truncated varint")


def _s(data: bytes) -> bytes:
    return _u(len(data)) + data


def _g(data: bytes, p: int) -> tuple[bytes, int]:
    n, p = _r(data, p)
    e = p + n
    if e > len(data):
        raise ValueError("truncated length-delimited value")
    return data[p:e], e


def _zz(n: int) -> int:
    # Generic zigzag mapping; unlike the common 64-bit formula this is safe
    # for JSON integers of arbitrary Python precision.
    return (n << 1) if n >= 0 else ((-n << 1) - 1)


def _uzz(n: int) -> int:
    return (n >> 1) if not (n & 1) else -((n >> 1) + 1)


def _json_tokens(data: bytes) -> list[bytes]:
    pos = 0
    out = []
    for m in _JSON_TOKEN.finditer(data):
        if m.start() != pos:
            raise ValueError("invalid JSON lexical stream")
        out.append(m.group(0))
        pos = m.end()
    if pos != len(data):
        raise ValueError("invalid JSON lexical stream")
    return out


def _json_encode(data: bytes) -> bytes:
    tokens = _json_tokens(data)
    strings = Counter(t for t in tokens if t[:1] == b'"')
    dictionary = sorted(
        (x for x, n in strings.items() if n >= 2),
        key=lambda x: (-strings[x] * len(x), x),
    )
    ids = {x: i for i, x in enumerate(dictionary)}

    out = bytearray(_u(len(dictionary)))
    for s in dictionary:
        out += _s(s)
    out += _u(len(tokens))

    prev_int = 0
    for t in tokens:
        if t[:1] in b"{}[],:":
            out.append(J_PUNCT)
            out += _s(t)
        elif t[:1] == b'"':
            i = ids.get(t)
            if i is None:
                out.append(J_STRING)
                out += _s(t)
            else:
                out.append(J_DICT)
                out += _u(i)
        elif _JSON_INT.fullmatch(t.decode("ascii")):
            out.append(J_INT)
            value = int(t)
            out += _u(_zz(value - prev_int))
            prev_int = value
        else:
            out.append(J_RAW)
            out += _s(t)
    return bytes(out)


def _json_decode(payload: bytes) -> bytes:
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
            raise ValueError("truncated JSON IR")
        tag = payload[p]
        p += 1
        if tag in (J_PUNCT, J_STRING, J_RAW):
            x, p = _g(payload, p)
            out += x
        elif tag == J_DICT:
            i, p = _r(payload, p)
            if i >= len(dictionary):
                raise ValueError("bad JSON dictionary reference")
            out += dictionary[i]
        elif tag == J_INT:
            z, p = _r(payload, p)
            prev_int += _uzz(z)
            out += str(prev_int).encode("ascii")
        else:
            raise ValueError("unknown JSON IR tag")
    if p != len(payload):
        raise ValueError("trailing JSON IR bytes")
    return bytes(out)


def _csv_parse_exact(data: bytes):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text or "," not in text:
        return None
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows or any(len(r) != len(rows[0]) for r in rows):
        return None
    # Gate the transform on byte-exact canonical reconstruction.
    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator="\n").writerows(rows)
    if buf.getvalue().encode("utf-8") != data:
        return None
    return rows


def _csv_encode(data: bytes) -> bytes:
    rows = _csv_parse_exact(data)
    if rows is None:
        raise ValueError("CSV is not canonical UTF-8 CSV")
    width = len(rows[0])
    out = bytearray(_u(width))
    for col in zip(*rows):
        vals = list(col)
        ints = []
        numeric = True
        for v in vals:
            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", v or ""):
                numeric = False
                break
            ints.append(int(v))
        if numeric:
            out.append(1)
            out += _u(len(vals))
            prev = 0
            for n in ints:
                out += _u(_zz(n - prev))
                prev = n
        else:
            out.append(2)
            counts = Counter(vals)
            dictionary = sorted(
                (v for v, c in counts.items() if c >= 2),
                key=lambda v: (-counts[v] * len(v), v),
            )
            ids = {v: i for i, v in enumerate(dictionary)}
            out += _u(len(dictionary))
            for v in dictionary:
                out += _s(v.encode("utf-8"))
            out += _u(len(vals))
            for v in vals:
                i = ids.get(v)
                if i is None:
                    out.append(0)
                    out += _s(v.encode("utf-8"))
                else:
                    out.append(1)
                    out += _u(i)
    return bytes(out)


def _csv_decode(payload: bytes) -> bytes:
    p = 0
    width, p = _r(payload, p)
    cols = []
    for _ in range(width):
        if p >= len(payload):
            raise ValueError("truncated CSV IR")
        tag = payload[p]
        p += 1
        if tag == 1:
            n, p = _r(payload, p)
            vals = []
            prev = 0
            for _ in range(n):
                z, p = _r(payload, p)
                prev += _uzz(z)
                vals.append(str(prev))
            cols.append(vals)
        elif tag == 2:
            nd, p = _r(payload, p)
            dictionary = []
            for _ in range(nd):
                x, p = _g(payload, p)
                dictionary.append(x.decode("utf-8"))
            n, p = _r(payload, p)
            vals = []
            for _ in range(n):
                t = payload[p]
                p += 1
                if t == 0:
                    x, p = _g(payload, p)
                    vals.append(x.decode("utf-8"))
                elif t == 1:
                    i, p = _r(payload, p)
                    if i >= len(dictionary):
                        raise ValueError("bad CSV dictionary reference")
                    vals.append(dictionary[i])
                else:
                    raise ValueError("bad CSV value tag")
            cols.append(vals)
        else:
            raise ValueError("unknown CSV column tag")
    if not cols:
        return b""
    if any(len(c) != len(cols[0]) for c in cols):
        raise ValueError("CSV column length mismatch")
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    for row in zip(*cols):
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


def encode(data: bytes, kind: str) -> bytes:
    if kind == "json":
        payload, code = _json_encode(data), K_JSON
    elif kind == "csv":
        payload, code = _csv_encode(data), K_CSV
    else:
        raise ValueError("UBIR supports json/csv candidates only")
    return MAGIC + bytes([VERSION, code]) + _u(len(data)) + payload


def decode(blob: bytes) -> bytes:
    if len(blob) < 6 or blob[:4] != MAGIC or blob[4] != VERSION:
        raise ValueError("invalid UBIR header")
    kind = blob[5]
    raw, p = _r(blob, 6)
    payload = blob[p:]
    if kind == K_JSON:
        out = _json_decode(payload)
    elif kind == K_CSV:
        out = _csv_decode(payload)
    else:
        raise ValueError("unknown UBIR kind")
    if len(out) != raw:
        raise ValueError("UBIR length mismatch")
    return out


def candidates(data: bytes, suffix: str):
    s = suffix.lower()
    kinds = ["json"] if s in {".json", ".jsonl"} else (["csv"] if s == ".csv" else [])
    out = []
    for kind in kinds:
        try:
            payload = encode(data, kind)
            if decode(payload) == data:
                out.append((kind, payload))
        except (ValueError, UnicodeDecodeError, csv.Error):
            pass
    return out


__all__ = ["encode", "decode", "candidates", "K_JSON", "K_CSV"]
