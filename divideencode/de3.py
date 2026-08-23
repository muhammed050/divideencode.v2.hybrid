"""DE3 representation search.

Goal: minimize final encoded size, not encode speed.  DE3 treats DivideEncode
as a representation search problem: generate reversible transforms, recursively
compose useful transforms, then let a final entropy/LZ coder encode the winning
representation.  Every candidate carries its exact metadata cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .divide_transform import DIVISORS, WORD_SIZES, divide_reconstruct, divide_transform


@dataclass(frozen=True)
class Representation:
    """A reversible representation with an exact-ish cost model."""
    name: str
    data: bytes
    metadata: bytes = b""
    parent: Optional["Representation"] = None

    @property
    def total_size(self) -> int:
        return len(self.data) + len(self.metadata)


@dataclass(frozen=True)
class TransformSpec:
    name: str
    encode: Callable[[bytes], Optional[Representation]]


def identity(data: bytes) -> Representation:
    return Representation("raw", bytes(data))


def _divide_candidate(data: bytes, w: int, d: int) -> Optional[Representation]:
    try:
        t = divide_transform(data, w, d)
    except (ValueError, OverflowError):
        return None
    q = t["quotient_stream"]
    r = t["remainder_stream"]
    # Header is deliberately explicit in DE3.  The production bitstream can
    # replace this fixed accounting with varints, but search must never pretend
    # metadata is free.
    header = (
        b"DV3"
        + bytes((w,))
        + d.to_bytes(4, "little")
        + t["n_words"].to_bytes(8, "little")
        + bytes((t["wq"], t["rbits"]))
        + len(t["tail"]).to_bytes(4, "little")
    )
    body = q + r + t["tail"]
    return Representation(f"divide(w={w},d={d})", body, header)


def generate_divide_candidates(data: bytes, limit: int = 12) -> list[Representation]:
    """Generate reversible Divide representations and rank by total bytes."""
    out: list[Representation] = []
    for w in WORD_SIZES:
        if len(data) < 4 * w:
            continue
        for d in DIVISORS:
            if d > 65536:
                continue
            cand = _divide_candidate(data, w, d)
            if cand is not None and cand.total_size < len(data) + 64:
                out.append(cand)
    out.sort(key=lambda x: x.total_size)
    return out[:limit]


def search_representations(data: bytes, *, beam: int = 16, max_depth: int = 2) -> Representation:
    """Beam-search reversible representations.

    This is intentionally independent of the final compressor.  A future stage
    can plug in entropy/LZ cost estimation; for now we select on exact raw
    transformed bytes + representation metadata, giving us a safe foundation
    for discovering transformations that genuinely reduce the representation.
    """
    root = identity(data)
    beam_items = [root]
    best = root
    seen = {root.data}

    for _depth in range(max_depth):
        expanded: list[Representation] = []
        for parent in beam_items:
            for cand in generate_divide_candidates(parent.data, limit=beam):
                if cand.data in seen:
                    continue
                seen.add(cand.data)
                expanded.append(
                    Representation(
                        name=f"{parent.name} -> {cand.name}",
                        data=cand.data,
                        metadata=parent.metadata + cand.metadata,
                        parent=parent,
                    )
                )
        if not expanded:
            break
        expanded.sort(key=lambda x: x.total_size)
        beam_items = expanded[:beam]
        if beam_items[0].total_size < best.total_size:
            best = beam_items[0]

    return best


def reconstruct_divide(data: bytes, metadata: bytes) -> bytes:
    """Decode one DV3 Divide representation header/body."""
    if len(metadata) < 21 or metadata[:3] != b"DV3":
        raise ValueError("invalid DE3 Divide metadata")
    w = metadata[3]
    d = int.from_bytes(metadata[4:8], "little")
    n_words = int.from_bytes(metadata[8:16], "little")
    wq, rbits = metadata[16], metadata[17]
    tail_len = int.from_bytes(metadata[17:21], "little")
    q_len = n_words * wq
    r_len = (n_words * rbits + 7) // 8
    q = data[:q_len]
    r = data[q_len:q_len + r_len]
    tail = data[q_len + r_len:q_len + r_len + tail_len]
    return divide_reconstruct(q, r, w, d, wq, rbits, n_words, tail)
