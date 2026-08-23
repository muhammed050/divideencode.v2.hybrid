"""Structural Engine v5 — structure discovery before DE2.

V5 keeps v4's lossless transforms and adds bounded record/column discovery:
- generalized byte-plane transpose for fixed-width records
- column-wise XOR/delta candidates
- bounded compositions
- downstream adaptive scoring with RAW as the safety floor

The engine is deliberately independent so v4 remains a stable baseline.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from .structural_v4 import (
    MAGIC as V4_MAGIC,
    VERSION as V4_VERSION,
    STEP_XOR,
    STEP_TRANSPOSE,
    _encode_v4,
    _raw_blob as _v4_raw,
    _varint,
    _read_varint,
    _decode_v4_step,
    _apply_step,
    STEP_DELTA,
    STEP_RLE,
    STEP_DICT,
    Candidate as V4Candidate,
)

MAGIC = b"SV5"
VERSION = 1
STEP_RECORD_TRANSPOSE = 7
STEP_COLUMN_DELTA = 8
STEP_COLUMN_XOR = 9

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


def _encode(steps: list[Step]) -> bytes:
    body = bytearray((VERSION, len(steps)))
    for step in steps:
        body.append(step.kind)
        body.extend(_varint(len(step.meta)))
        body.extend(step.meta)
        body.extend(_varint(len(step.payload)))
        body.extend(step.payload)
    return MAGIC + bytes(body)


def _raw(data: bytes) -> bytes:
    return MAGIC + bytes((VERSION, 0)) + _varint(len(data)) + data


def _record_transpose(data: bytes):
    best = None
    # 2..64 covers common fixed-record layouts while keeping search bounded.
    for width in range(2, 65):
        if len(data) < width * 32 or len(data) % width:
            continue
        count = len(data) // width
        out = bytearray(len(data))
        q = 0
        for field in range(width):
            for row in range(count):
                out[q] = data[row * width + field]
                q += 1
        meta = bytes((width,)) + _varint(count)
        step = Step(STEP_RECORD_TRANSPOSE, meta, bytes(out))
        score = len(_encode([step]))
        if best is None or score < best[0]:
            best = score, step, bytes(out), width
    return best[1:] if best else None


def _column_delta(data: bytes):
    best = None
    for width in range(2, 17):
        if len(data) < width * 32 or len(data) % width:
            continue
        count = len(data) // width
        # Delta each byte column independently. This is reversible and useful
        # for fixed-width records whose fields change gradually.
        out = bytearray(len(data))
        for col in range(width):
            prev = 0
            for row in range(count):
                p = row * width + col
                value = data[p]
                out[p] = (value - prev) & 0xFF
                prev = value
        meta = bytes((width,)) + _varint(count)
        step = Step(STEP_COLUMN_DELTA, meta, bytes(out))
        score = len(_encode([step]))
        if best is None or score < best[0]:
            best = score, step, bytes(out), width
    return best[1:] if best else None


def _column_xor(data: bytes):
    best = None
    for width in range(2, 17):
        if len(data) < width * 32 or len(data) % width:
            continue
        count = len(data) // width
        out = bytearray(len(data))
        for col in range(width):
            prev = 0
            for row in range(count):
                p = row * width + col
                value = data[p]
                out[p] = value ^ prev
                prev = value
        meta = bytes((width,)) + _varint(count)
        step = Step(STEP_COLUMN_XOR, meta, bytes(out))
        score = len(_encode([step]))
        if best is None or score < best[0]:
            best = score, step, bytes(out), width
    return best[1:] if best else None


def _decode_v5_step(step: Step) -> bytes:
    if step.kind in (STEP_COLUMN_DELTA, STEP_COLUMN_XOR):
        if not step.meta:
            raise ValueError("invalid column metadata")
        width = step.meta[0]
        count, q = _read_varint(step.meta, 1)
        if q != len(step.meta) or width < 2 or width > 64:
            raise ValueError("invalid column metadata")
        if len(step.payload) != width * count:
            raise ValueError("invalid column payload")
        out = bytearray(len(step.payload))
        for col in range(width):
            prev = 0
            for row in range(count):
                p = row * width + col
                x = step.payload[p]
                value = (x + prev) & 0xFF if step.kind == STEP_COLUMN_DELTA else x ^ prev
                out[p] = value
                prev = value
        return bytes(out)
    if step.kind == STEP_RECORD_TRANSPOSE:
        if not step.meta:
            raise ValueError("invalid record transpose metadata")
        width = step.meta[0]
        count, q = _read_varint(step.meta, 1)
        if q != len(step.meta) or width < 2 or width > 64:
            raise ValueError("invalid record transpose metadata")
        if len(step.payload) != width * count:
            raise ValueError("invalid record transpose payload")
        out = bytearray(len(step.payload))
        p = 0
        for field in range(width):
            for row in range(count):
                out[row * width + field] = step.payload[p]
                p += 1
        return bytes(out)
    if step.kind in (STEP_XOR, STEP_TRANSPOSE, STEP_DELTA, STEP_RLE, STEP_DICT):
        return _decode_v4_step(step)
    raise ValueError("unknown structural v5 step")


def inverse(blob: bytes) -> bytes:
    if len(blob) < 5 or blob[:3] != MAGIC:
        raise ValueError("invalid structural v5 stream")
    if blob[3] != VERSION:
        raise ValueError("unsupported structural v5 version")
    count = blob[4]
    p = 5
    if count == 0:
        size, p = _read_varint(blob, p)
        end = p + size
        if end != len(blob):
            raise ValueError("invalid raw structural stream")
        return blob[p:end]
    steps = []
    for _ in range(count):
        if p >= len(blob):
            raise ValueError("truncated structural v5 stream")
        kind = blob[p]; p += 1
        mlen, p = _read_varint(blob, p)
        end = p + mlen
        if end > len(blob):
            raise ValueError("truncated structural metadata")
        meta = blob[p:end]; p = end
        plen, p = _read_varint(blob, p)
        end = p + plen
        if end > len(blob):
            raise ValueError("truncated structural payload")
        steps.append(Step(kind, meta, blob[p:end]))
        p = end
    if p != len(blob):
        raise ValueError("trailing structural bytes")
    data = steps[-1].payload
    for step in reversed(steps):
        data = _decode_v5_step(step)
    return data


def _legacy_candidates(data: bytes, max_depth: int) -> list[Candidate]:
    # v4 candidates are valid structural representations; re-wrap their
    # payload pipeline by decoding and rebuilding only when useful is costly.
    # Instead, keep v5 focused on newly discovered structure and add the most
    # useful v4 transforms directly below.
    out: list[Candidate] = []
    from .structural_v4 import analyze as v4_analyze
    for c in v4_analyze(data, max_depth=min(max_depth, 2)):
        # Decode v4 then place the original bytes in a v5 raw candidate only if
        # v4's structural size is already below raw; the adaptive scorer can
        # still compare it through a v5 candidate wrapper.
        try:
            payload = __import__("divideencode.v2.structural_v4", fromlist=["inverse"]).inverse(c.blob)
        except Exception:
            continue
        if payload == data:
            out.append(Candidate(("v4:" + "+".join(c.kinds),), c.blob, c.size))
    return out


def analyze(data: bytes, max_depth: int = 3) -> list[Candidate]:
    if max_depth < 1:
        return []
    candidates: list[Candidate] = []
    seen: set[bytes] = set()
    raw = _raw(data)

    def add(steps: list[Step], names: tuple[str, ...]):
        blob = _encode(steps)
        if blob not in seen:
            seen.add(blob)
            candidates.append(Candidate(names, blob, len(blob)))

    # First-order structural discovery.
    transforms = (
        ("record-transpose", _record_transpose),
        ("column-delta", _column_delta),
        ("column-xor", _column_xor),
    )
    queue: list[tuple[bytes, list[Step], tuple[str, ...], int]] = []
    for name, fn in transforms:
        x = fn(data)
        if x is None:
            continue
        step, payload, _width = x
        names = (name,)
        add([step], names)
        queue.append((payload, [step], names, 1))

    # Compose discovered structure with v4's dictionary/delta/RLE and with
    # another discovered transform, but cap depth to keep the search bounded.
    while queue:
        current, steps, names, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        for kind, label in ((STEP_DELTA, "delta"), (STEP_RLE, "rle"), (STEP_DICT, "dict")):
            x = _apply_step(current, kind)
            if x is not None:
                step, step_names, _ = x
                ns = steps + [step]
                nn = names + (label,)
                add(ns, nn)
                if depth + 1 < max_depth and len(step.payload) < len(current):
                    queue.append((step.payload, ns, nn, depth + 1))
        if depth + 1 < max_depth:
            for name, fn in transforms:
                x = fn(current)
                if x is not None:
                    step, payload, _ = x
                    ns = steps + [step]
                    nn = names + (name,)
                    add(ns, nn)
                    if len(payload) < len(current):
                        queue.append((payload, ns, nn, depth + 1))

    # Keep v4 candidates as opaque alternatives only when they are valid.
    candidates.extend(c for c in _legacy_candidates(data, max_depth) if c.blob not in seen)
    candidates.sort(key=lambda c: c.size)
    return candidates


def transform(data: bytes, max_depth: int = 3) -> bytes:
    raw = _raw(data)
    candidates = analyze(data, max_depth=max_depth)
    return candidates[0].blob if candidates and candidates[0].size < len(raw) else raw


def adaptive_transform(data: bytes, scorer, max_depth: int = 3) -> Decision:
    raw = _raw(data)
    options = [((), raw)]
    options.extend((c.kinds, c.blob) for c in analyze(data, max_depth=max_depth))
    best_kinds, best_blob = options[0]
    best = scorer(best_blob)
    for kinds, blob in options[1:]:
        score = scorer(blob)
        if score < best:
            best_kinds, best_blob, best = kinds, blob, score
    return Decision(best_kinds, best_blob, len(best_blob), best)
