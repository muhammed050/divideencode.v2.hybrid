"""Experimental DE2 Patternization layer.

It deliberately sits outside the stable DE2 container while the idea is
validated.  It tries only transforms that a cheap prefix sample predicts may
create repetition, then uses DE2's exact compressed size as the arbiter.
"""
from .codec import compress as de2_compress, decompress as de2_decompress
from .patterns import PATTERN_DELTA2, PATTERN_XOR, apply, inverse, should_try

MAGIC = b"DE2P"


def compress(data):
    """Return a self-contained DE2-P blob. Never larger than raw DE2 by more
    than its tiny 5-byte dispatch header, and only transforms when measured
    DE2 output is strictly smaller."""
    raw = de2_compress(data)
    best = raw
    best_kind = 0
    for kind in (PATTERN_DELTA2, PATTERN_XOR):
        if not should_try(data, kind):
            continue
        transformed = apply(data, kind)
        candidate = de2_compress(transformed)
        # 5 bytes: magic + transform id. The margin makes the transform pay
        # for its own dispatch cost instead of creating a fake win.
        if len(candidate) + 5 < len(best):
            best = candidate
            best_kind = kind
    return MAGIC + bytes((best_kind,)) + best


def decompress(blob):
    if not blob.startswith(MAGIC) or len(blob) < 6:
        raise ValueError("invalid DE2-P blob")
    kind = blob[4]
    payload = blob[5:]
    out = de2_decompress(payload)
    if kind == 0:
        return out
    return inverse(out, kind)

__all__ = ["compress", "decompress"]
