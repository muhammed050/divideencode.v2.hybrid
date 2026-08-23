"""Structural Engine v4.

V4 extends the v3 compositional engine with reversible byte-oriented
transforms and a stricter candidate search.  It is deliberately independent
from v3 so experiments can be compared without changing the stable engine.
"""
from __future__ import annotations

from dataclasses import dataclass

from .structural_v3 import (
    MAGIC as V3_MAGIC,
    _VERSION as V3_VERSION,
    _varint,
    _read_varint,
    _apply_step,
    _encode_pipeline,
    _raw_blob,
    _decode_step,
    Step,
    Candidate as V3Candidate,
    inverse as v3_inverse,
    analyze as v3_analyze,
    STEP_DELTA,
    STEP_RLE,
    STEP_DICT,
    STEP_PLANE,
)

MAGIC = b"SV4"
VERSION = 1
STEP_XOR = 5
STEP_TRANSPOSE = 6

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


def _encode_v4(steps: list[Step]) -> bytes:
    body = bytearray((VERSION, len(steps)))
    for step in steps:
        body.append(step.kind)
        body.extend(_varint(len(step.meta)))
        body.extend(step.meta)
        body.extend(_varint(len(step.payload)))
        body.extend(step.payload)
    return MAGIC + bytes(body)


def _xor_step(data: bytes):
    if len(data) < 16:
        return None
    out = bytearray(len(data))
    prev = 0
    for i, b in enumerate(data):
        out[i] = b ^ prev
        prev = b
    # XOR itself is only useful if it actually exposes a cheaper downstream
    # representation; keep the candidate even when it is not byte-smaller.
    return Step(STEP_XOR, b"", bytes(out)), ("xor",), bytes(out)


def _transpose_step(data: bytes):
    best = None
    for width in (2, 4, 8, 16, 32):
        if len(data) < width * 32 or len(data) % width:
            continue
        count = len(data) // width
        out = bytearray(len(data))
        q = 0
        for b in range(width):
            for r in range(count):
                out[q] = data[r * width + b]
                q += 1
        meta = bytes((width,)) + _varint(count)
        step = Step(STEP_TRANSPOSE, meta, bytes(out))
        # Metadata is tiny; all widths are retained for downstream scoring.
        size = 5 + len(meta) + len(out)
        candidate = (step, ("transpose",), bytes(out), size)
        if best is None or size < best[3]:
            best = candidate
    return best[:3] if best else None


def _decode_v4_step(step: Step) -> bytes:
    if step.kind == STEP_XOR:
        out = bytearray(len(step.payload))
        prev = 0
        for i, b in enumerate(step.payload):
            value = b ^ prev
            out[i] = value
            prev = value
        return bytes(out)
    if step.kind == STEP_TRANSPOSE:
        if not step.meta:
            raise ValueError("invalid transpose metadata")
        width = step.meta[0]
        count, q = _read_varint(step.meta, 1)
        if q != len(step.meta) or width not in (2, 4, 8, 16, 32):
            raise ValueError("invalid transpose metadata")
        if len(step.payload) != width * count:
            raise ValueError("invalid transpose payload")
        out = bytearray(len(step.payload))
        p = 0
        for b in range(width):
            for r in range(count):
                out[r * width + b] = step.payload[p]
                p += 1
        return bytes(out)
    return _decode_step(step)


def inverse(blob: bytes) -> bytes:
    if len(blob) < 5 or blob[:3] != MAGIC:
        raise ValueError("invalid structural v4 stream")
    if blob[3] != VERSION:
        raise ValueError("unsupported structural v4 version")
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
            raise ValueError("truncated structural v4 stream")
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
        data = _decode_v4_step(Step(step.kind, step.meta, data))
    return data


def _legacy_candidates(data: bytes, max_depth: int) -> list[Candidate]:
    out = []
    for c in v3_analyze(data, max_depth=max_depth):
        out.append(Candidate(c.kinds, MAGIC + c.blob[3:], len(MAGIC + c.blob[3:])))
    return out


def analyze(data: bytes, max_depth: int = 3) -> list[Candidate]:
    if max_depth < 1:
        return []
    candidates = _legacy_candidates(data, max_depth=min(max_depth, 2))
    seen = {c.blob for c in candidates}
    queue = [(data, [], (), 0)]
    transforms = (
        ("xor", _xor_step),
        ("transpose", _transpose_step),
    )
    while queue:
        current, steps, names, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        for name, fn in transforms:
            x = fn(current)
            if x is None:
                continue
            step, step_names, payload = x
            new_steps = steps + [step]
            new_names = names + step_names
            blob = _encode_v4(new_steps)
            if blob not in seen:
                seen.add(blob)
                candidates.append(Candidate(new_names, blob, len(blob)))
            if depth + 1 < max_depth:
                for kind in (STEP_DELTA, STEP_RLE, STEP_DICT):
                    y = _apply_step(payload, kind)
                    if y is None:
                        continue
                    second, second_names, _ = y
                    composed = new_steps + [second]
                    cname = new_names + second_names
                    cblob = _encode_v4(composed)
                    if cblob not in seen:
                        seen.add(cblob)
                        candidates.append(Candidate(cname, cblob, len(cblob)))
                    if depth + 2 < max_depth and len(second.payload) < len(payload):
                        queue.append((second.payload, composed, cname, depth + 2))
    candidates.sort(key=lambda c: c.size)
    return candidates


def transform(data: bytes, max_depth: int = 3) -> bytes:
    raw = MAGIC + bytes((VERSION, 0)) + _varint(len(data)) + data
    candidates = analyze(data, max_depth=max_depth)
    return candidates[0].blob if candidates and candidates[0].size < len(raw) else raw


def adaptive_transform(data: bytes, scorer, max_depth: int = 3) -> Decision:
    raw = MAGIC + bytes((VERSION, 0)) + _varint(len(data)) + data
    options = [((), raw)]
    options.extend((c.kinds, c.blob) for c in analyze(data, max_depth=max_depth))
    best_kinds, best_blob = options[0]
    best = scorer(data)
    for kinds, blob in options[1:]:
        score = scorer(blob)
        if score < best:
            best_kinds, best_blob, best = kinds, blob, score
    return Decision(best_kinds, best_blob, len(best_blob), best)
