"""UBIR5 — universal phrase/token translator for DE2.

The selector deliberately estimates *actual* token savings instead of relying
on overlapping substring counts. A phrase reference costs two bytes, while a
dictionary entry costs its phrase bytes plus two bytes of length metadata.
This keeps the phrase IR from selecting patterns that look frequent but do
not survive the longest-first tokenization pass.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

MAGIC = b"UB5"
VERSION = 1
ESC = 0


@dataclass(frozen=True)
class PhraseCandidate:
    phrase: bytes
    count: int
    gain: int


def _nonoverlap_count(data: bytes, phrase: bytes) -> int:
    """Count occurrences exactly as the token stream can consume them.

    ``bytes.count`` is implemented in C and counts non-overlapping matches,
    which is a good cheap proxy for the longest-first tokenizer.
    """
    return data.count(phrase)


def _candidate_phrases(src: bytes, lengths: tuple[int, ...], max_dict: int) -> list[PhraseCandidate]:
    """Find candidates using frequency first, then exact token savings.

    Counting every source position is still done only once per phrase length.
    We then re-score a bounded shortlist with ``bytes.count`` so overlapping
    occurrences cannot inflate the estimated benefit.
    """
    sample = src if len(src) <= 8 * 1024 * 1024 else src[:8 * 1024 * 1024]
    rough: list[tuple[bytes, int, int]] = []
    per_length = max(32, min(max_dict * 2, 256))

    for length in lengths:
        if length > len(sample):
            continue
        counts = Counter(sample[i:i + length] for i in range(len(sample) - length + 1))
        for phrase, freq in counts.most_common(per_length):
            if freq < 2:
                break
            # Upper-bound screening; exact non-overlap scoring follows.
            rough_gain = freq * (length - 2) - (length + 2)
            if rough_gain > 0:
                rough.append((phrase, freq, rough_gain))

    # Bound the expensive C-level count calls while keeping representation
    # diversity across phrase lengths.
    rough.sort(key=lambda x: (x[2], x[1], len(x[0])), reverse=True)
    shortlist = rough[: min(max_dict * 2, 256)]

    candidates: list[PhraseCandidate] = []
    for phrase, freq, _ in shortlist:
        actual = _nonoverlap_count(sample, phrase)
        length = len(phrase)
        gain = actual * (length - 2) - (length + 2)
        if gain > 0:
            candidates.append(PhraseCandidate(phrase, actual, gain))

    candidates.sort(key=lambda x: (x.gain, x.count, len(x.phrase)), reverse=True)
    return candidates[: max_dict * 4]


def _select_dictionary(src: bytes, lengths: tuple[int, ...], max_dict: int) -> list[bytes]:
    """Select a compact dictionary from exact non-overlap savings.

    Substring redundancy is avoided because the tokenizer is longest-first;
    keeping both a phrase and a strict substring usually adds dictionary
    overhead without adding useful coverage.
    """
    selected: list[bytes] = []
    for cand in _candidate_phrases(src, lengths, max_dict):
        if len(selected) >= max_dict:
            break
        p = cand.phrase
        if any(p == q or (len(p) <= len(q) and p in q) for q in selected):
            continue
        selected.append(p)
    return selected


def _encode_tokens(src: bytes, dictionary: list[bytes]) -> bytes:
    # Index phrases by first byte and test longest phrases first. This avoids
    # comparing every dictionary entry at every input position.
    by_first: dict[int, list[tuple[bytes, int]]] = {}
    for idx, phrase in enumerate(dictionary):
        by_first.setdefault(phrase[0], []).append((phrase, idx + 1))
    for values in by_first.values():
        values.sort(key=lambda x: len(x[0]), reverse=True)

    out = bytearray()
    append = out.extend
    startswith = src.startswith
    i = 0
    n = len(src)
    while i < n:
        matches = by_first.get(src[i])
        if matches:
            for phrase, token in matches:
                if startswith(phrase, i):
                    append((ESC, token))
                    i += len(phrase)
                    break
            else:
                b = src[i]
                append((ESC, 0) if b == ESC else (b,))
                i += 1
        else:
            b = src[i]
            append((ESC, 0) if b == ESC else (b,))
            i += 1
    return bytes(out)


def _decode_tokens(tokens: bytes, dictionary: list[bytes]) -> bytes:
    out = bytearray()
    append = out.extend
    i = 0
    n = len(tokens)
    while i < n:
        b = tokens[i]
        if b != ESC:
            out.append(b)
            i += 1
            continue
        if i + 1 >= n:
            raise ValueError("truncated UBIR5 escape")
        code = tokens[i + 1]
        if code == 0:
            out.append(ESC)
        elif code - 1 < len(dictionary):
            append(dictionary[code - 1])
        else:
            raise ValueError("invalid UBIR5 dictionary reference")
        i += 2
    return bytes(out)


def encode(src: bytes, *, phrase_lengths: tuple[int, ...] = (4, 5, 6, 8, 12, 16), max_dict: int = 255) -> tuple[bytes, list[bytes]]:
    src = bytes(src)
    if max_dict < 0 or max_dict > 255:
        raise ValueError("max_dict must be between 0 and 255")
    dictionary = _select_dictionary(src, phrase_lengths, max_dict)
    tokens = _encode_tokens(src, dictionary)
    header = bytearray(MAGIC)
    header.append(VERSION)
    header.append(len(dictionary))
    for phrase in dictionary:
        if len(phrase) > 65535:
            raise ValueError("phrase too long")
        header.extend(len(phrase).to_bytes(2, "big"))
        header.extend(phrase)
    header.extend(len(tokens).to_bytes(8, "big"))
    header.extend(tokens)
    return bytes(header), dictionary


def decode(blob: bytes) -> bytes:
    blob = bytes(blob)
    if len(blob) < 5 or blob[:3] != MAGIC or blob[3] != VERSION:
        raise ValueError("invalid UBIR5 header")
    count = blob[4]
    i = 5
    dictionary: list[bytes] = []
    for _ in range(count):
        if i + 2 > len(blob):
            raise ValueError("truncated UBIR5 dictionary")
        n = int.from_bytes(blob[i:i + 2], "big")
        i += 2
        if i + n > len(blob):
            raise ValueError("truncated UBIR5 phrase")
        dictionary.append(blob[i:i + n])
        i += n
    if i + 8 > len(blob):
        raise ValueError("truncated UBIR5 token length")
    n = int.from_bytes(blob[i:i + 8], "big")
    i += 8
    if i + n != len(blob):
        raise ValueError("invalid UBIR5 token region")
    return _decode_tokens(blob[i:i + n], dictionary)


def verify(src: bytes, **kwargs) -> bytes:
    blob, _ = encode(src, **kwargs)
    if decode(blob) != bytes(src):
        raise AssertionError("UBIR5 roundtrip mismatch")
    return blob
