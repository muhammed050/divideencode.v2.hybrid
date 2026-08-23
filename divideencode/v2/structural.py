"""Structural transformation engine for Universal Divide.

Lossless, conservative transforms that turn structured byte streams into
simpler representations before compression. Every transform is reversible
and includes enough metadata for exact reconstruction.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class Candidate:
    kind: str
    payload: bytes
    meta: bytes
    score: int


MAGIC = b"SD1"


def _varint(n: int) -> bytes:
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7f) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _read_varint(buf: bytes, p: int):
    n = 0
    shift = 0
    while True:
        if p >= len(buf) or shift > 63:
            raise ValueError("invalid structural varint")
        b = buf[p]; p += 1
        n |= (b & 0x7f) << shift
        if not (b & 0x80):
            return n, p
        shift += 7


def _signed_delta(values):
    if not values:
        return []
    return [values[0]] + [values[i] - values[i - 1] for i in range(1, len(values))]


def _undelta(values):
    out = []
    total = 0
    for x in values:
        total += x
        out.append(total)
    return out


def _encode_svarint(x: int) -> bytes:
    # Zigzag + varint
    return _varint((x << 1) ^ (x >> 63))


def _decode_svarints(buf: bytes, count: int):
    out = []
    p = 0
    for _ in range(count):
        u, p = _read_varint(buf, p)
        out.append((u >> 1) ^ -(u & 1))
    if p != len(buf):
        raise ValueError("trailing structural data")
    return out


def _numeric_sequence(data: bytes):
    """Detect fixed-width little/big endian integer arrays and return values."""
    for width, fmt in ((1, "B"), (2, "<H"), (4, "<I"), (8, "<Q"),
                       (2, ">H"), (4, ">I"), (8, ">Q")):
        if len(data) < width * 4 or len(data) % width:
            continue
        f = fmt if width == 1 else fmt
        try:
            vals = list(struct.iter_unpack(f if width == 1 else f, data))
        except struct.error:
            continue
        vals = [x[0] for x in vals]
        if len(vals) >= 4:
            yield width, f, vals


def _delta_candidate(data: bytes):
    best = None
    for width, fmt, vals in _numeric_sequence(data):
        ds = _signed_delta(vals)
        packed = b"".join(_encode_svarint(x) for x in ds)
        meta = bytes((width,)) + fmt.encode("ascii") + _varint(len(vals))
        total = len(MAGIC) + 1 + len(meta) + len(packed)
        if total < len(data):
            c = Candidate("delta", packed, meta, total)
            if best is None or c.score < best.score:
                best = c
    return best


def _rle_candidate(data: bytes):
    if not data:
        return None
    runs = []
    i = 0
    while i < len(data):
        j = i + 1
        while j < len(data) and data[j] == data[i] and j - i < (1 << 32):
            j += 1
        runs.append((data[i], j - i))
        i = j
    if len(runs) >= len(data):
        return None
    packed = bytearray()
    for b, n in runs:
        packed.append(b)
        packed.extend(_varint(n))
    total = len(MAGIC) + 1 + len(packed)
    if total >= len(data):
        return None
    return Candidate("rle", bytes(packed), b"", total)


def _dictionary_candidate(data: bytes):
    # Repeated fixed-size chunks. This intentionally stays conservative.
    best = None
    for size in (2, 3, 4, 5, 6, 8, 12, 16, 24, 32):
        if len(data) < size * 8 or len(data) % size:
            continue
        chunks = [data[i:i + size] for i in range(0, len(data), size)]
        uniq = {}
        dictionary = []
        ids = bytearray()
        for c in chunks:
            idx = uniq.get(c)
            if idx is None:
                idx = len(dictionary)
                if idx >= 256:
                    break
                uniq[c] = idx
                dictionary.append(c)
            ids.append(idx)
        else:
            packed = bytearray(_varint(size))
            packed.extend(_varint(len(dictionary)))
            for c in dictionary:
                packed.extend(c)
            packed.extend(ids)
            total = len(MAGIC) + 1 + len(packed)
            if total < len(data):
                c = Candidate("dict", bytes(packed), b"", total)
                if best is None or c.score < best.score:
                    best = c
    return best


def analyze(data: bytes):
    """Return conservative structural candidates ordered by final size."""
    candidates = []
    for fn in (_delta_candidate, _rle_candidate, _dictionary_candidate):
        c = fn(data)
        if c is not None:
            candidates.append(c)
    return sorted(candidates, key=lambda x: x.score)


def transform(data: bytes) -> bytes:
    """Choose the smallest structural representation, or store raw."""
    candidates = analyze(data)
    if not candidates:
        return MAGIC + b"\x00" + data
    c = candidates[0]
    kind = {"delta": 1, "rle": 2, "dict": 3}[c.kind]
    return MAGIC + bytes((kind,)) + _varint(len(c.meta)) + c.meta + c.payload


def inverse(blob: bytes) -> bytes:
    if len(blob) < 4 or blob[:3] != MAGIC:
        raise ValueError("invalid structural stream")
    kind = blob[3]
    if kind == 0:
        return blob[4:]
    mlen, p = _read_varint(blob, 4)
    meta = blob[p:p + mlen]
    payload = blob[p + mlen:]
    if kind == 1:
        width = meta[0]
        fmt = meta[1:].split(b"\x00", 1)[0].decode("ascii")
        count, _ = _read_varint(meta, 1 + len(fmt))
        vals = _undelta(_decode_svarints(payload, count))
        if width == 1:
            return bytes(vals)
        return b"".join(struct.pack(fmt, v) for v in vals)
    if kind == 2:
        out = bytearray(); q = 0
        while q < len(payload):
            b = payload[q]; q += 1
            n, q = _read_varint(payload, q)
            out.extend(bytes((b,)) * n)
        return bytes(out)
    if kind == 3:
        size, q = _read_varint(payload, 0)
        n, q = _read_varint(payload, q)
        dictionary = []
        for _ in range(n):
            dictionary.append(payload[q:q + size]); q += size
        return b"".join(dictionary[i] for i in payload[q:])
    raise ValueError("unknown structural transform")
