"""Structural Engine v5: record/column discovery with v4 compatibility."""
from __future__ import annotations
from dataclasses import dataclass

from . import structural_v4 as v4

MAGIC = b"SV5"
VERSION = 1
STEP_RECORD_TRANSPOSE = 7
STEP_COLUMN_DELTA = 8
STEP_COLUMN_XOR = 9
STEP_V4 = 10

@dataclass(frozen=True)
class Step:
    kind: int
    meta: bytes
    payload: bytes

@dataclass(frozen=True)
class Candidate:
    kinds: tuple[str, ...]
    blob: bytes
    size: int

@dataclass(frozen=True)
class Decision:
    kinds: tuple[str, ...]
    blob: bytes
    structural_size: int
    downstream_size: int | None

_varint = v4._varint
_read_varint = v4._read_varint


def _encode(steps):
    body = bytearray((VERSION, len(steps)))
    for s in steps:
        body.append(s.kind)
        body.extend(_varint(len(s.meta))); body.extend(s.meta)
        body.extend(_varint(len(s.payload))); body.extend(s.payload)
    return MAGIC + bytes(body)


def _raw(data):
    return MAGIC + bytes((VERSION, 0)) + _varint(len(data)) + data


def _record_transpose(data):
    best = None
    for width in range(2, 65):
        if len(data) < width * 32 or len(data) % width: continue
        count = len(data) // width
        out = bytearray(len(data)); q = 0
        for col in range(width):
            for row in range(count):
                out[q] = data[row * width + col]; q += 1
        step = Step(STEP_RECORD_TRANSPOSE, bytes((width,)) + _varint(count), bytes(out))
        size = len(_encode([step]))
        if best is None or size < best[0]: best = size, step, bytes(out)
    return best[1:] if best else None


def _column_transform(data, xor=False):
    best = None
    for width in range(2, 65):
        if len(data) < width * 32 or len(data) % width: continue
        count = len(data) // width
        out = bytearray(len(data))
        for col in range(width):
            prev = 0
            for row in range(count):
                p = row * width + col; x = data[p]
                out[p] = (x ^ prev) if xor else ((x - prev) & 255)
                prev = x
        kind = STEP_COLUMN_XOR if xor else STEP_COLUMN_DELTA
        name = "column-xor" if xor else "column-delta"
        step = Step(kind, bytes((width,)) + _varint(count), bytes(out))
        size = len(_encode([step]))
        if best is None or size < best[0]: best = size, step, bytes(out)
    return (best[1], best[2], name) if best else None


def _decode_step(s):
    if s.kind == STEP_RECORD_TRANSPOSE:
        if not s.meta: raise ValueError("invalid record transpose metadata")
        width = s.meta[0]; count, q = _read_varint(s.meta, 1)
        if q != len(s.meta) or width < 2 or width > 64 or len(s.payload) != width * count:
            raise ValueError("invalid record transpose")
        out = bytearray(len(s.payload)); p = 0
        for col in range(width):
            for row in range(count): out[row * width + col] = s.payload[p]; p += 1
        return bytes(out)
    if s.kind in (STEP_COLUMN_DELTA, STEP_COLUMN_XOR):
        if not s.meta: raise ValueError("invalid column metadata")
        width = s.meta[0]; count, q = _read_varint(s.meta, 1)
        if q != len(s.meta) or width < 2 or width > 64 or len(s.payload) != width * count:
            raise ValueError("invalid column transform")
        out = bytearray(len(s.payload))
        for col in range(width):
            prev = 0
            for row in range(count):
                p = row * width + col; x = s.payload[p]
                out[p] = ((x + prev) & 255) if s.kind == STEP_COLUMN_DELTA else (x ^ prev)
                prev = out[p] if s.kind == STEP_COLUMN_DELTA else x
        return bytes(out)
    if s.kind == STEP_V4:
        return v4.inverse(s.payload)
    return v4._decode_v4_step(s)


def inverse(blob):
    if len(blob) < 5 or blob[:3] != MAGIC or blob[3] != VERSION:
        raise ValueError("invalid structural v5 stream")
    count = blob[4]; p = 5
    if count == 0:
        size, p = _read_varint(blob, p); end = p + size
        if end != len(blob): raise ValueError("invalid raw structural stream")
        return blob[p:end]
    steps = []
    for _ in range(count):
        if p >= len(blob): raise ValueError("truncated structural stream")
        kind = blob[p]; p += 1
        mlen, p = _read_varint(blob, p); end = p + mlen
        if end > len(blob): raise ValueError("truncated metadata")
        meta = blob[p:end]; p = end
        plen, p = _read_varint(blob, p); end = p + plen
        if end > len(blob): raise ValueError("truncated payload")
        steps.append(Step(kind, meta, blob[p:end])); p = end
    if p != len(blob): raise ValueError("trailing structural bytes")
    data = steps[-1].payload
    for s in reversed(steps): data = _decode_step(Step(s.kind, s.meta, data))
    return data


def _v4_candidates(data, max_depth):
    out = []
    for c in v4.analyze(data, max_depth=min(max_depth, 2)):
        wrapped = _encode([Step(STEP_V4, b"", c.blob)])
        out.append(Candidate(("v4:" + "+".join(c.kinds),), wrapped, len(wrapped)))
    return out


def analyze(data, max_depth=3):
    if max_depth < 1: return []
    candidates = []; seen = set(); queue = []
    def add(steps, names):
        blob = _encode(steps)
        if blob not in seen:
            seen.add(blob); candidates.append(Candidate(tuple(names), blob, len(blob)))
    for name, fn in (("record-transpose", _record_transpose), ("column-delta", lambda x: _column_transform(x, False)), ("column-xor", lambda x: _column_transform(x, True))):
        x = fn(data)
        if x is None: continue
        if name == "record-transpose": step, payload = x[0], x[1]
        else: step, payload = x[0], x[1]
        names = (name,); add([step], names); queue.append((payload, [step], names, 1))
    while queue:
        current, steps, names, depth = queue.pop(0)
        if depth >= max_depth: continue
        for kind, label in ((v4.STEP_DELTA,"delta"),(v4.STEP_RLE,"rle"),(v4.STEP_DICT,"dict")):
            x = v4._apply_step(current, kind)
            if x is None: continue
            step = x[0]; ns = steps + [step]; nn = names + (label,); add(ns, nn)
            if depth + 1 < max_depth and len(step.payload) < len(current): queue.append((step.payload, ns, nn, depth + 1))
    for c in _v4_candidates(data, max_depth):
        if c.blob not in seen: seen.add(c.blob); candidates.append(c)
    candidates.sort(key=lambda c: c.size)
    return candidates


def transform(data, max_depth=3):
    raw = _raw(data); cs = analyze(data, max_depth)
    return cs[0].blob if cs and cs[0].size < len(raw) else raw


def adaptive_transform(data, scorer, max_depth=3):
    raw = _raw(data); best_blob = raw; best_kinds = (); best = scorer(raw)
    for c in analyze(data, max_depth):
        score = scorer(c.blob)
        if score < best: best, best_blob, best_kinds = score, c.blob, c.kinds
    return Decision(best_kinds, best_blob, len(best_blob), best)
