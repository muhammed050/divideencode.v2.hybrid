"""ABR3 adaptive preconditioner selector.

Experimental only: evaluates multiple reversible representations and lets the
end-to-end DE2 size decide. No production DE2 behavior is changed.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from . import adaptive_binary as abr1
from . import adaptive_binary_v2 as abr2

@dataclass(frozen=True)
class Candidate:
    kind: str
    payload: bytes


def candidates(data: bytes, suffix: str) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[bytes] = set()
    for name, fn in (("abr1", abr1.candidates), ("abr2", abr2.candidates)):
        for kind, payload in fn(data, suffix):
            if payload not in seen:
                out.append(Candidate(f"{name}:{kind}", payload))
                seen.add(payload)
    return out


def decode(kind: str, payload: bytes) -> bytes:
    if kind.startswith("abr1:"):
        return abr1.decode(payload)
    if kind.startswith("abr2:"):
        return abr2.decode(payload)
    if kind == "direct":
        return payload
    raise ValueError(f"unknown ABR3 kind: {kind}")


def choose(data: bytes, suffix: str, packer):
    """Return (kind, packed, intermediate_size, elapsed) for the best path.

    packer(payload) must return the complete DE2 frame. The selector compares
    complete end-to-end sizes, never the intermediate representation alone.
    """
    import time
    t0 = time.perf_counter()
    direct = packer(data)
    best = ("direct", direct, len(data), time.perf_counter() - t0)
    for c in candidates(data, suffix):
        t = time.perf_counter()
        packed = packer(c.payload)
        elapsed = time.perf_counter() - t
        if len(packed) < len(best[1]):
            best = (c.kind, packed, len(c.payload), elapsed)
    return best
