"""Fast single-pass universal front-end for DE2.

The translator makes exactly one representation decision per block.  It does
not run several full transforms and compare compressed outputs.  A small
sample is used only to decide whether phrase IR is worthwhile and which
phrase length to use; the selected representation is then built once and
passed to DE2 once.

Supported representations:
    RAW       - incompressible/unknown data
    RLE       - long runs
    DELTA_LZ  - numeric monotonic data
    LZ        - normal bytes
    PHRASE_LZ - printable/structured data with useful repeated phrases
"""
from . import phrase, transforms, lz
from .classifier import (MODE_RAW, MODE_RLE, MODE_LZ, MODE_DELTA_LZ,
                         MODE_STRUCT_LZ, classify)
from .features import scan_features
from ..patterns import rle_encode

SAMPLE_SIZE = 65536
PHRASE_LENGTHS = (4, 6, 8, 12, 16)
PHRASE_MAX_DICT = 255
PHRASE_SAMPLE_THRESHOLD = 0.90


def _sample_phrase_choice(data: bytes):
    """Choose one phrase length using only a bounded sample.

    The score is the transformed sample size plus a small dictionary cost.
    This is deliberately a proxy: it avoids expensive DE2 trial encoding.
    """
    sample = data[:SAMPLE_SIZE]
    best = None
    for k in PHRASE_LENGTHS:
        if len(sample) < k * 2:
            continue
        transformed, meta = phrase.encode(sample, phrase_len=k,
                                          max_dict=PHRASE_MAX_DICT)
        if transformed is None:
            continue
        score = len(transformed) + len(meta)
        if best is None or score < best[0]:
            best = (score, k, len(transformed), len(sample))
    if best is None:
        return None
    score, k, transformed_len, sample_len = best
    # Require a meaningful reduction on the sample.  This is what keeps
    # already-compressed/binary data on the normal LZ path without trying a
    # second full compression candidate.
    if score >= sample_len * PHRASE_SAMPLE_THRESHOLD:
        return None
    return k


def translate(data: bytes, fs=None):
    """Return ``(mode, transformed, metadata)`` for exactly one IR choice."""
    src = bytes(data)
    if not src:
        return MODE_RAW, b"", b""

    if fs is None:
        fs = scan_features(src)
    mode, _hint = classify(fs)

    if mode == MODE_RLE:
        blob = rle_encode(src)
        if blob is not None and len(blob) < len(src):
            return MODE_RLE, blob, b""
        mode = MODE_LZ

    if mode == MODE_DELTA_LZ:
        frame, meta = transforms.numeric_encode(
            src, mono=fs.mono32, hi_gain=fs.delta_ratio, _enc=lz.encode_v2)
        if frame is not None and len(frame) < len(src):
            return MODE_DELTA_LZ, frame, meta
        mode = MODE_LZ

    phrase_allowed = mode in (MODE_LZ, MODE_STRUCT_LZ)
    phrase_allowed = phrase_allowed and len(src) >= 64
    phrase_allowed = phrase_allowed and fs.printable_frac >= 0.70
    phrase_allowed = phrase_allowed and fs.match_density >= 0.01

    if phrase_allowed:
        k = _sample_phrase_choice(src)
        if k is not None:
            transformed, meta = phrase.encode(
                src, phrase_len=k, max_dict=PHRASE_MAX_DICT)
            if transformed is not None:
                return MODE_STRUCT_LZ, transformed, meta

    if mode == MODE_STRUCT_LZ:
        mode = MODE_LZ
    return mode, src, b""
