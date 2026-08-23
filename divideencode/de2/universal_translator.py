"""Fast single-pass universal front-end for DE2.

The front-end makes one representation decision per block. A bounded sample
chooses whether phrase IR is worthwhile and, if so, its phrase length. The
full block is then translated once and DE2 encodes that one representation.
Normal LZ, RLE and numeric transforms remain native DE2 modes.
"""
from . import phrase

SAMPLE_SIZE = 65536
PHRASE_LENGTHS = (4, 6, 8, 12, 16)
PHRASE_MAX_DICT = 255
PHRASE_SAMPLE_THRESHOLD = 0.90


def choose_phrase_length(data: bytes):
    """Return one phrase length or ``None`` using only a bounded sample."""
    sample = bytes(data[:SAMPLE_SIZE])
    if len(sample) < 8:
        return None

    best = None
    for k in PHRASE_LENGTHS:
        if len(sample) < k * 2:
            continue
        transformed, meta = phrase.encode(
            sample, phrase_len=k, max_dict=PHRASE_MAX_DICT)
        if transformed is None:
            continue
        score = len(transformed) + len(meta)
        if best is None or score < best[0]:
            best = (score, k)

    if best is None:
        return None
    score, k = best
    if score >= len(sample) * PHRASE_SAMPLE_THRESHOLD:
        return None
    return k


def translate_phrase(data: bytes, phrase_len: int):
    """Build exactly one full-block phrase representation."""
    return phrase.encode(data, phrase_len=phrase_len,
                         max_dict=PHRASE_MAX_DICT)
