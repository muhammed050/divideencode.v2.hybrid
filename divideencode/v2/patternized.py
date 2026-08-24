"""Experimental DE2 patternization with symbol-address/rank encoding."""
import struct

from .codec import compress as de2_compress, decompress as de2_decompress
from .patterns import (PATTERN_DELTA2, PATTERN_RANK, PATTERN_XOR, apply,
                       inverse, should_try, symbol_rank, symbol_unrank)

MAGIC = b"DE2P"


def compress(data):
    raw = de2_compress(data)
    best = MAGIC + b"\x00" + raw
    best_len = len(best)
    best_kind = 0
    best_payload = raw
    best_meta = b""

    for kind in (PATTERN_RANK, PATTERN_DELTA2, PATTERN_XOR):
        if not should_try(data, kind):
            continue
        if kind == PATTERN_RANK:
            stream, dictionary, bits = symbol_rank(data)
            candidate = de2_compress(stream)
            # original length + dictionary length + rank width + dictionary
            meta = struct.pack("<IHB", len(data), len(dictionary), bits) + dictionary
            if 5 + len(meta) + len(candidate) < best_len:
                best_len = 5 + len(meta) + len(candidate)
                best_kind = kind
                best_payload = candidate
                best_meta = meta
        else:
            transformed = apply(data, kind)
            candidate = de2_compress(transformed)
            if len(candidate) + 5 < best_len:
                best_len = len(candidate) + 5
                best_kind = kind
                best_payload = candidate
                best_meta = b""

    return MAGIC + bytes((best_kind,)) + best_meta + best_payload


def decompress(blob):
    if not blob.startswith(MAGIC) or len(blob) < 5:
        raise ValueError("invalid DE2-P blob")
    kind = blob[4]
    if kind == PATTERN_RANK:
        if len(blob) < 12:
            raise ValueError("truncated rank header")
        original_len, dict_len, bits = struct.unpack_from("<IHB", blob, 5)
        start = 12
        end = start + dict_len
        if end > len(blob):
            raise ValueError("truncated rank dictionary")
        dictionary = blob[start:end]
        stream = de2_decompress(blob[end:])
        return symbol_unrank(stream, dictionary, original_len, bits)
    out = de2_decompress(blob[5:])
    if kind == 0:
        return out
    return inverse(out, kind)


__all__ = ["compress", "decompress"]
