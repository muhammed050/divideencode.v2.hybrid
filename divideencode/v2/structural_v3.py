"""Compositional Structural Engine v3.

The v2 structural engine chooses one transform.  v3 searches short reversible
pipelines, because a useful representation is often a composition such as
integer-delta -> RLE or dictionary -> RLE.  The engine is conservative: every
candidate is lossless, has explicit metadata, and adaptive mode compares the
complete representation with RAW using the supplied downstream scorer.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

MAGIC = b"SV3"
_VERSION = 1

# step ids are deliberately stable; never recycle an id.
STEP_DELTA = 1
STEP_RLE = 2
STEP_DICT = 3
STEP_PLANE = 4


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


def _varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative varint")
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _read_varint(buf: bytes, p: int = 0) -> tuple[int, int]:
    n = 0
    shift = 0
    while True:
        if p >= len(buf) or shift > 63:
            raise ValueError("invalid varint")
        b = buf[p]
        p += 1
        n |= (b & 0x7F) << shift
        if not (b & 0x80):
            return n, p
        shift += 7


def _svarint(x: int) -> bytes:
    # Python integers are arbitrary precision; this is the canonical ZigZag form.
    u = (x << 1) if x >= 0 else ((-x << 1) - 1)
    return _varint(u)


def _read_svarints(buf: bytes, count: int) -> list[int]:
    out: list[int] = []
    p = 0
    for _ in range(count):
        u, p = _read_varint(buf, p)
        out.append((u >> 1) ^ -(u & 1))
    if p != len(buf):
        raise ValueError("trailing signed varints")
    return out


def _delta_step(data: bytes):
    best = None
    for width, fmts in (
        (1, ("B",)),
        (2, ("<H", ">H")),
        (4, ("<I", ">I")),
        (8, ("<Q", ">Q")),
    ):
        if len(data) < width * 8 or len(data) % width:
            continue
        for fmt in fmts:
            vals = [x[0] for x in struct.iter_unpack(fmt, data)]
            prev = 0
            packed = bytearray()
            for v in vals:
                packed.extend(_svarint(v - prev))
                prev = v
            # Store original format and count so reconstruction is exact.
            fb = fmt.encode("ascii")
            meta = bytes((width, len(fb))) + fb + _varint(len(vals))
            overhead = len(_varint(len(meta))) + len(meta) + 4
            size = overhead + len(packed)
            if size >= len(data):
                continue
            item = (size, Step(STEP_DELTA, meta, bytes(packed)), ("delta",))
            if best is None or size < best[0]:
                best = item
    return best


def _rle_step(data: bytes):
    if not data:
        return None
    packed = bytearray()
    runs = 0
    i = 0
    while i < len(data):
        j = i + 1
        while j < len(data) and data[j] == data[i]:
            j += 1
        packed.append(data[i])
        packed.extend(_varint(j - i))
        runs += 1
        i = j
    if len(packed) + 4 >= len(data):
        return None
    meta = _varint(runs)
    return len(meta) + len(packed) + 4, Step(STEP_RLE, meta, bytes(packed)), ("rle",)


def _dict_step(data: bytes):
    best = None
    for width in (2, 3, 4, 5, 6, 8, 12, 16, 24, 32):
        if len(data) < width * 16 or len(data) % width:
            continue
        table: dict[bytes, int] = {}
        dictionary: list[bytes] = []
        ids = bytearray()
        for p in range(0, len(data), width):
            chunk = data[p:p + width]
            idx = table.get(chunk)
            if idx is None:
                idx = len(dictionary)
                if idx >= 256:
                    break
                table[chunk] = idx
                dictionary.append(chunk)
            ids.append(idx)
        else:
            meta = bytearray(_varint(width))
            meta.extend(_varint(len(dictionary)))
            for chunk in dictionary:
                meta.extend(chunk)
            size = len(meta) + len(ids) + 4
            if size < len(data) and (best is None or size < best[0]):
                best = size, Step(STEP_DICT, bytes(meta), bytes(ids)), ("dict",)
    return best


def _plane_step(data: bytes):
    # Transposition alone is neutral in byte count; v3 only emits it when a
    # following transform makes it useful.  The caller therefore treats it as
    # a candidate intermediate rather than a final representation.
    for width in (2, 4, 8, 16):
        if len(data) < width * 16 or len(data) % width:
            continue
        count = len(data) // width
        out = bytearray(len(data))
        q = 0
        for b in range(width):
            for r in range(count):
                out[q] = data[r * width + b]
                q += 1
        meta = bytes((width,)) + _varint(count)
        return Step(STEP_PLANE, meta, bytes(out)), ("plane",), bytes(out)
    return None


def _apply_raw_step(data: bytes, kind: int):
    if kind == STEP_DELTA:
        x = _delta_step(data)
        return None if x is None else (x[1], x[2], x[0])
    if kind == STEP_RLE:
        x = _rle_step(data)
        return None if x is None else (x[1], x[2], x[0])
    if kind == STEP_DICT:
        x = _dict_step(data)
        return None if x is None else (x[1], x[2], x[0])
    return None


def _step_blob(step: Step) -> bytes:
    return bytes((step.kind,)) + _varint(len(step.meta)) + step.meta + step.payload


def _make_blob(steps: list[Step]) -> bytes:
    body = bytearray()
    body.extend(bytes((_VERSION, len(steps))))
    for step in steps:
        body.extend(_step_blob(step))
    # The final bytes are the payload of the last step.  Earlier steps contain
    # their own payload, making the stream a self-contained transformation log.
    return MAGIC + bytes(body)


def _decode_step(step: Step) -> bytes:
    data = step.payload
    if step.kind == STEP_DELTA:
        if len(step.meta) < 2:
            raise ValueError("invalid delta metadata")
        width, flen = step.meta[0], step.meta[1]
        fs, fe = 2, 2 + flen
        if fe > len(step.meta):
            raise ValueError("truncated delta metadata")
        fmt = step.meta[fs:fe].decode("ascii")
        count, q = _read_varint(step.meta, fe)
        if q != len(step.meta):
            raise ValueError("trailing delta metadata")
        deltas = _read_svarints(data, count)
        vals = []
        total = 0
        for d in deltas:
            total += d
            vals.append(total)
        if width == 1:
            if any(v < 0 or v > 255 for v in vals):
                raise ValueError("delta byte out of range")
            return bytes(vals)
        try:
            return b"".join(struct.pack(fmt, v) for v in vals)
        except struct.error as exc:
            raise ValueError("delta value out of range") from exc

    if step.kind == STEP_RLE:
        runs, q = _read_varint(step.meta)
        if q != len(step.meta):
            raise ValueError("invalid rle metadata")
        out = bytearray()
        p = 0
        for _ in range(runs):
            if p >= len(data):
                raise ValueError("truncated rle payload")
            b = data[p]
            p += 1
            n, p = _read_varint(data, p)
            out.extend(bytes((b,)) * n)
        if p != len(data):
            raise ValueError("trailing rle payload")
        return bytes(out)

    if step.kind == STEP_DICT:
        width, q = _read_varint(step.meta)
        count, q = _read_varint(step.meta, q)
        dictionary = []
        for _ in range(count):
            end = q + width
            if end > len(step.meta):
                raise ValueError("truncated dictionary")
            dictionary.append(step.meta[q:end])
            q = end
        if q != len(step.meta) or count > 256:
            raise ValueError("invalid dictionary")
        if any(i >= count for i in data):
            raise ValueError("invalid dictionary id")
        return b"".join(dictionary[i] for i in data)

    if step.kind == STEP_PLANE:
        if not step.meta:
            raise ValueError("invalid plane metadata")
        width = step.meta[0]
        count, q = _read_varint(step.meta, 1)
        if q != len(step.meta) or width not in (2, 4, 8, 16):
            raise ValueError("invalid plane metadata")
        if len(data) != width * count:
            raise ValueError("invalid plane payload")
        out = bytearray(len(data))
        p = 0
        for b in range(width):
            for r in range(count):
                out[r * width + b] = data[p]
                p += 1
        return bytes(out)

    raise ValueError("unknown structural v3 step")


def _encode_pipeline(original: bytes, steps: list[Step]) -> bytes:
    # A step stores the output of that step. Decode therefore walks backwards.
    # RAW is implicit: inverse reconstructs from the last payload and reverses
    # every operation in reverse order.
    body = bytearray((_VERSION, len(steps)))
    for s in steps:
        body.extend(_step_blob(s))
    return MAGIC + bytes(body)


def inverse(blob: bytes) -> bytes:
    if len(blob) < 5 or blob[:3] != MAGIC:
        raise ValueError("invalid structural v3 stream")
    version = blob[3]
    if version != _VERSION:
        raise ValueError("unsupported structural v3 version")
    count = blob[4]
    p = 5
    steps: list[Step] = []
    for _ in range(count):
        if p >= len(blob):
            raise ValueError("truncated structural v3 stream")
        kind = blob[p]
        p += 1
        mlen, p = _read_varint(blob, p)
        end = p + mlen
        if end > len(blob):
            raise ValueError("truncated structural v3 metadata")
        meta = blob[p:end]
        payload_start = end
        # Payload boundaries are explicit for every step by storing payload
        # length before payload.  Old blobs are rejected rather than guessed.
        plen, p2 = _read_varint(blob, payload_start)
        pend = p2 + plen
        if pend > len(blob):
            raise ValueError("truncated structural v3 payload")
        steps.append(Step(kind, meta, blob[p2:pend]))
        p = pend
    if p != len(blob):
        raise ValueError("trailing structural v3 bytes")
    if not steps:
        return b""
    data = steps[-1].payload
    for step in reversed(steps):
        # The final step payload is already its output; inverse of a step
        # reconstructs its input. For intermediate steps this is exactly the
        # previous step's output.
        data = _decode_step(Step(step.kind, step.meta, data))
    return data


def _encode_pipeline(steps: list[Step]) -> bytes:
    body = bytearray((_VERSION, len(steps)))
    for s in steps:
        body.extend(bytes((s.kind,)))
        body.extend(_varint(len(s.meta)))
        body.extend(s.meta)
        body.extend(_varint(len(s.payload)))
        body.extend(s.payload)
    return MAGIC + bytes(body)


def _raw_blob(data: bytes) -> bytes:
    return MAGIC + bytes((_VERSION, 0)) + _varint(len(data)) + data


def _single_candidates(data: bytes):
    for kind in (STEP_DELTA, STEP_RLE, STEP_DICT):
        x = _apply_raw_step(data, kind)
        if x is not None:
            step, names, size = x
            yield names, _encode_pipeline([step])


def analyze(data: bytes, max_depth: int = 2) -> list[Candidate]:
    """Search a bounded transform graph and return candidates by byte size."""
    seen: set[bytes] = set()
    candidates: list[Candidate] = []
    queue: list[tuple[bytes, list[Step], tuple[str, ...], int]] = [(data, [], (), 0)]

    while queue:
        current, steps, names, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        for kind in (STEP_DELTA, STEP_RLE, STEP_DICT):
            x = _apply_raw_step(current, kind)
            if x is None:
                continue
            step, step_names, _ = x
            nxt = step.payload
            new_steps = steps + [step]
            new_names = names + step_names
            blob = _encode_pipeline(new_steps)
            if blob in seen:
                continue
            seen.add(blob)
            candidates.append(Candidate(new_names, blob, len(blob)))
            # Do not allow an unbounded graph; each intermediate must shrink.
            if len(nxt) < len(current) and len(new_steps) < max_depth:
                queue.append((nxt, new_steps, new_names, depth + 1))

    # Plane is an intermediate only. Apply it and then the normal transforms.
    plane = _plane_step(data)
    if plane is not None and max_depth >= 2:
        step, names, plane_data = plane
        for kind in (STEP_DELTA, STEP_RLE, STEP_DICT):
            x = _apply_raw_step(plane_data, kind)
            if x is None:
                continue
            second, second_names, _ = x
            blob = _encode_pipeline([step, second])
            candidates.append(Candidate(names + second_names, blob, len(blob)))

    candidates.sort(key=lambda c: c.size)
    return candidates


def transform(data: bytes, max_depth: int = 2) -> bytes:
    candidates = analyze(data, max_depth=max_depth)
    raw = _raw_blob(data)
    return candidates[0].blob if candidates and candidates[0].size < len(raw) else raw


def adaptive_transform(data: bytes, scorer, max_depth: int = 2) -> Decision:
    raw = _raw_blob(data)
    options = [((), raw)]
    options.extend((c.kinds, c.blob) for c in analyze(data, max_depth=max_depth))
    best_kinds, best_blob = options[0]
    best = scorer(best_blob)
    for kinds, blob in options[1:]:
        score = scorer(blob)
        if score < best:
            best_kinds, best_blob, best = kinds, blob, score
    return Decision(best_kinds, best_blob, len(best_blob), best)
