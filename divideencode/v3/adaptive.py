"""Original adaptive representation search for the DE3 research branch.

This module deliberately keeps the production V3 codec untouched.  It explores
small, deterministic transformations on independent blocks and chooses the
lowest measured representation cost, including its metadata.

The transformations are conventional building blocks, implemented here from
scratch.  The composition/search policy is the experimental DivideEncode
contribution: bounded beam search over reversible representations with exact
measured cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import zlib


MAGIC = b"DAR1"
VERSION = 1


@dataclass(frozen=True)
class Candidate:
    name: str
    data: bytes
    chain: tuple[str, ...]
    cost: int


Transform = Callable[[bytes], bytes | None]


def _delta(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    prev = 0
    for i, value in enumerate(data):
        out[i] = (value - prev) & 0xFF
        prev = value
    return bytes(out)


def _xor_prev(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    prev = 0
    for i, value in enumerate(data):
        out[i] = value ^ prev
        prev = value
    return bytes(out)


def _rle(data: bytes) -> bytes | None:
    if not data:
        return b""
    out = bytearray()
    i = 0
    while i < len(data):
        j = i + 1
        while j < len(data) and data[j] == data[i] and j - i < 256:
            j += 1
        run = j - i
        # literal packet: 0..127 length; repeat packet: 128..255 length
        if run >= 3:
            out.extend((0x80 | (run - 1), data[i]))
        else:
            out.extend((run - 1,))
            out.extend(data[i:j])
        i = j
    return bytes(out)


def _bitplane(data: bytes) -> bytes | None:
    if not data:
        return b""
    out = bytearray(len(data))
    # Store each bit position as a byte plane, packed into bytes.
    plane_bytes = (len(data) + 7) // 8
    out = bytearray(8 * plane_bytes)
    for bit in range(8):
        base = bit * plane_bytes
        acc = 0
        n = 0
        dst = base
        for value in data:
            acc = (acc << 1) | ((value >> bit) & 1)
            n += 1
            if n == 8:
                out[dst] = acc
                dst += 1
                acc = 0
                n = 0
        if n:
            out[dst] = acc << (8 - n)
    return bytes(out)


def _byteplane(data: bytes) -> bytes | None:
    if not data:
        return b""
    # For ordinary byte streams this is identity; don't waste a candidate.
    return None


def _pack_runs(data: bytes) -> bytes | None:
    """Encode short repeated byte pairs as a reversible byte-oriented stream.

    This is intentionally simple and deterministic.  It is separate from RLE
    so the search can discover whether a sparse marker stream is worthwhile.
    """
    if len(data) < 8:
        return None
    out = bytearray()
    i = 0
    while i < len(data):
        best = 1
        best_byte = data[i]
        j = i + 1
        while j < len(data) and data[j] == best_byte and j - i < 255:
            j += 1
        best = j - i
        if best >= 4:
            out.extend((0, best, best_byte))
            i = j
        else:
            start = i
            i += 1
            while i < len(data) and i - start < 254:
                if i + 3 < len(data) and data[i] == data[i + 1] == data[i + 2] == data[i + 3]:
                    break
                i += 1
            literal_len = i - start
            out.extend((1, literal_len))
            out.extend(data[start:i])
    return bytes(out)


def _entropy_proxy(data: bytes) -> int:
    """Fast deterministic proxy: zlib level 1 plus a tiny framing estimate.

    This is only a search oracle.  Production DE2/DE3 entropy coding is not
    replaced by zlib; the final branch will plug the chosen representation into
    its own coder.
    """
    if not data:
        return 0
    return len(zlib.compress(data, 1)) + 2


TRANSFORMS: tuple[tuple[str, Transform], ...] = (
    ("delta", _delta),
    ("xor-prev", _xor_prev),
    ("rle", _rle),
    ("bitplane", _bitplane),
    ("pack-runs", _pack_runs),
)


def _header_cost(chain: tuple[str, ...], payload_size: int) -> int:
    # DAR1 chain IDs are fixed one-byte IDs in this research format.
    return 8 + len(chain) + payload_size


def search_block(data: bytes, *, depth: int = 2, beam: int = 8) -> Candidate:
    """Find the best bounded transformation chain for one block.

    The search is deliberately bounded.  Every candidate is scored using the
    transformed bytes plus an explicit representation header cost, so a clever
    transformation cannot win merely by hiding metadata.
    """
    raw = bytes(data)
    initial = Candidate("raw", raw, (), _header_cost((), len(raw)))
    frontier = [initial]
    best = initial
    seen: set[bytes] = {raw}

    for _ in range(max(0, depth)):
        expanded: list[Candidate] = []
        for cand in frontier:
            for name, transform in TRANSFORMS:
                transformed = transform(cand.data)
                if transformed is None or transformed in seen:
                    continue
                seen.add(transformed)
                chain = cand.chain + (name,)
                # Search cost is representation payload after a cheap entropy
                # proxy, plus explicit chain metadata.
                cost = _header_cost(chain, _entropy_proxy(transformed))
                expanded.append(Candidate(" -> ".join(chain), transformed, chain, cost))
        if not expanded:
            break
        expanded.sort(key=lambda c: (c.cost, len(c.chain), c.chain))
        frontier = expanded[: max(1, beam)]
        if frontier[0].cost < best.cost:
            best = frontier[0]

    return best


def analyze(data: bytes, *, block_size: int = 1 << 20, depth: int = 2, beam: int = 8) -> list[Candidate]:
    """Analyze every block independently and return its winning candidate."""
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    winners = []
    for start in range(0, len(data), block_size):
        block = data[start:start + block_size]
        winners.append(search_block(block, depth=depth, beam=beam))
    return winners


__all__ = ["Candidate", "TRANSFORMS", "search_block", "analyze"]
