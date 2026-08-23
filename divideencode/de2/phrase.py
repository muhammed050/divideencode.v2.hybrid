"""Fixed-width phrase IR used as an optional DE2 preconditioner.

The IR deliberately trades representation size for a more compressible byte
alphabet.  A phrase reference is two bytes (0xFF, id+1); literal 0xFF is
escaped as (0xFF, 0).  The dictionary is stored in block metadata, so the
candidate is always self-contained and lossless.

This is an IR, not a second compressor: DE2/LZ still does the actual entropy
coding after the transform.  The encoder is allowed to reject the IR when it
does not reduce the final DE2 block size.
"""
from collections import Counter

from ..bitstream import decode_varint, encode_varint
from ..errors import CorruptedError

MAGIC = b"P"
DEFAULT_PHRASE_LEN = 6
DEFAULT_MAX_DICT = 255
_ESCAPE = 0xFF


def _rolling_counts(data: bytes, k: int) -> Counter:
    """Count k-grams without allocating one bytes object per position."""
    n = len(data)
    out = Counter()
    if n < k:
        return out
    mask = (1 << (8 * k)) - 1
    key = int.from_bytes(data[:k], "little")
    out[key] += 1
    shift = 8 * (k - 1)
    for i in range(k, n):
        key = ((key >> 8) | (data[i] << shift)) & mask
        out[key] += 1
    return out


def _mine(data: bytes, k: int, max_dict: int) -> list[bytes]:
    counts = _rolling_counts(data, k)
    # A phrase used twice barely pays for its 6-byte dictionary entry; more
    # frequent phrases dominate.  Deterministic integer ordering keeps the
    # container reproducible.
    ranked = []
    for key, count in counts.items():
        if count < 2:
            continue
        phrase = key.to_bytes(k, "little")
        gross = (k - 2) * count - k
        if gross > 0:
            ranked.append((gross, count, phrase))
    ranked.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [phrase for _gross, _count, phrase in ranked[:max_dict]]


def encode(data: bytes, phrase_len: int = DEFAULT_PHRASE_LEN,
           max_dict: int = DEFAULT_MAX_DICT):
    """Return (phrase-IR bytes, metadata), or (None, b"") if not useful."""
    src = bytes(data)
    if phrase_len < 3 or phrase_len > 32:
        raise ValueError("phrase_len must be in [3, 32]")
    if max_dict < 1 or max_dict > 255:
        raise ValueError("max_dict must be in [1, 255]")
    if len(src) < phrase_len * 2:
        return None, b""

    dictionary = _mine(src, phrase_len, max_dict)
    if not dictionary:
        return None, b""
    lookup = {p: i for i, p in enumerate(dictionary)}

    out = bytearray()
    i = 0
    n = len(src)
    while i < n:
        if i + phrase_len <= n:
            p = src[i:i + phrase_len]
            idx = lookup.get(p)
            if idx is not None:
                out.extend((_ESCAPE, idx + 1))
                i += phrase_len
                continue
        b = src[i]
        if b == _ESCAPE:
            out.extend((_ESCAPE, 0))
        else:
            out.append(b)
        i += 1

    # Metadata is part of the DE2 block and therefore participates in the
    # final size comparison.  Reject the IR before LZ if its representation
    # plus dictionary is already not smaller than the source.
    meta = bytearray(MAGIC)
    meta.append(phrase_len)
    meta += encode_varint(len(dictionary))
    for p in dictionary:
        meta += p
    meta += encode_varint(len(out))
    if len(out) + len(meta) >= len(src):
        return None, b""
    return bytes(out), bytes(meta)


def _read_meta(meta: bytes):
    blob = bytes(meta)
    if len(blob) < 2 or blob[:1] != MAGIC:
        raise CorruptedError("bad phrase metadata")
    k = blob[1]
    if k < 3 or k > 32:
        raise CorruptedError("invalid phrase length")
    count, pos = decode_varint(blob, 2, len(blob))
    if count < 1 or count > 255:
        raise CorruptedError("invalid phrase dictionary size")
    need = count * k
    if need > len(blob) - pos:
        raise CorruptedError("truncated phrase dictionary")
    dictionary = [bytes(blob[pos + i * k:pos + (i + 1) * k])
                  for i in range(count)]
    pos += need
    transformed_len, pos = decode_varint(blob, pos, len(blob))
    if pos != len(blob):
        raise CorruptedError("trailing phrase metadata")
    return dictionary, transformed_len


def transformed_length(meta: bytes) -> int:
    """Return the exact post-IR length stored in phrase metadata."""
    _dictionary, n = _read_meta(meta)
    return n


def decode(data: bytes, meta: bytes, original_len: int) -> bytes:
    """Reverse a phrase IR representation."""
    dictionary, transformed_len = _read_meta(meta)
    if transformed_len != len(data):
        raise CorruptedError("phrase transformed size mismatch")

    src = bytes(data)
    out = bytearray()
    i = 0
    while i < len(src):
        b = src[i]
        i += 1
        if b != _ESCAPE:
            out.append(b)
            continue
        if i >= len(src):
            raise CorruptedError("truncated phrase escape")
        code = src[i]
        i += 1
        if code == 0:
            out.append(_ESCAPE)
            continue
        idx = code - 1
        if idx >= len(dictionary):
            raise CorruptedError("invalid phrase dictionary id")
        out += dictionary[idx]
        if len(out) > original_len:
            raise CorruptedError("phrase output exceeds original size")

    if len(out) != original_len:
        raise CorruptedError("phrase output size mismatch")
    return bytes(out)
