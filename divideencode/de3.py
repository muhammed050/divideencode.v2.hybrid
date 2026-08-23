"""DE3 representation search.

DE3 is deliberately different from the old hybrid parser: the objective is
*final serialized size*.  A transform is useful only when it makes the final
coder produce fewer bytes after all representation metadata is paid.

The current search uses zlib level 9 as a deterministic stand-in for the
future native DE3 entropy/LZ backend.  This is a ranking oracle, not the
production bitstream coder.  Keeping the oracle separate lets us evolve the
representation search without confusing transform size with compression.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Callable, Optional

from .divide_transform import DIVISORS, WORD_SIZES, divide_reconstruct, divide_transform

HEADER_SIZE = 22


@dataclass(frozen=True)
class Representation:
    name: str
    data: bytes
    metadata: bytes = b""
    parent: Optional["Representation"] = None

    @property
    def coder_size(self) -> int:
        """Exact size of the current research ranking oracle."""
        return len(zlib.compress(self.data, level=9))

    @property
    def total_size(self) -> int:
        """Final size = transform metadata + bytes emitted by final coder."""
        return len(self.metadata) + self.coder_size

    @property
    def transform_size(self) -> int:
        """Raw transformed size, useful for diagnostics only."""
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
    header = (
        b"DV3"
        + bytes((w,))
        + d.to_bytes(4, "little")
        + t["n_words"].to_bytes(8, "little")
        + bytes((t["wq"], t["rbits"]))
        + len(t["tail"]).to_bytes(4, "little")
    )
    return Representation(f"divide(w={w},d={d})", q + r + t["tail"], header)


def generate_divide_candidates(data: bytes, limit: int = 12) -> list[Representation]:
    """Generate reversible Divide views without filtering on raw size.

    A transform that grows as bytes can still win after the final coder sees
    its structure, so the old ``len(transformed) < len(input)`` gate is
    intentionally gone.
    """
    out: list[Representation] = []
    for w in WORD_SIZES:
        if len(data) < 4 * w:
            continue
        for d in DIVISORS:
            cand = _divide_candidate(data, w, d)
            if cand is not None:
                out.append(cand)
    out.sort(key=lambda x: x.total_size)
    return out[:limit]


def search_representations(data: bytes, *, beam: int = 16, max_depth: int = 2) -> Representation:
    """Beam-search representations using final serialized size as objective."""
    root = identity(data)
    beam_items = [root]
    best = root
    # Include representation bytes AND transform history in the key. Two
    # identical payloads can have different decoding metadata.
    seen = {(root.data, root.metadata)}

    for _depth in range(max_depth):
        expanded: list[Representation] = []
        for parent in beam_items:
            for cand in generate_divide_candidates(parent.data, limit=beam):
                key = (cand.data, parent.metadata + cand.metadata)
                if key in seen:
                    continue
                seen.add(key)
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
    if len(metadata) < HEADER_SIZE or metadata[:3] != b"DV3":
        raise ValueError("invalid DE3 Divide metadata")
    w = metadata[3]
    d = int.from_bytes(metadata[4:8], "little")
    n_words = int.from_bytes(metadata[8:16], "little")
    wq = metadata[16]
    rbits = metadata[17]
    tail_len = int.from_bytes(metadata[18:22], "little")
    q_len = n_words * wq
    r_len = (n_words * rbits + 7) // 8
    body_len = q_len + r_len + tail_len
    if len(data) != body_len:
        raise ValueError("invalid DV3 body size")
    q = data[:q_len]
    r = data[q_len:q_len + r_len]
    tail = data[q_len + r_len:]
    return divide_reconstruct(q, r, w, d, wq, rbits, n_words, tail)
