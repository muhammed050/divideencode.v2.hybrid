"""UBIR5 — universal phrase/token translator for DE2.

Fast path: one-pass fixed-window counting, cheap gain ranking, then a single
materialization pass. The representation is reversible and may grow; DE2
chooses whether it is useful.
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


def _candidate_phrases(src: bytes, lengths: tuple[int, ...], max_dict: int) -> list[PhraseCandidate]:
    """Find useful phrases without repeatedly scanning the source.

    The old selector called ``bytes.find`` for every candidate and then rebuilt
    a temporary ``working`` byte string after every dictionary selection. That
    made preparation roughly O(candidates * input). We now rank candidates
    using one Counter pass per length and leave exact overlap handling to the
    final tokenization pass.
    """
    sample = src if len(src) <= 8 * 1024 * 1024 else src[:8 * 1024 * 1024]
    candidates: list[PhraseCandidate] = []
    for length in lengths:
        if length > len(sample):
            continue
        counts = Counter(sample[i:i + length] for i in range(len(sample) - length + 1))
        for phrase, freq in counts.most_common(max_dict * 2):
            if freq < 2:
                break
            gain = freq * (length - 2) - length
            if gain > 0:
                candidates.append(PhraseCandidate(phrase, freq, gain))
    candidates.sort(key=lambda x: (x.gain, x.count, len(x.phrase)), reverse=True)
    return candidates[: max_dict * 4]


def _select_dictionary(src: bytes, lengths: tuple[int, ...], max_dict: int) -> list[bytes]:
    """Select a compact non-redundant dictionary using estimated gains.

    Exact occurrence rescans are deliberately avoided here. Overlap is handled
    naturally by the longest-first token matcher below, which is both faster and
    gives a deterministic result.
    """
    selected: list[bytes] = []
    for cand in _candidate_phrases(src, lengths, max_dict):
        if len(selected) >= max_dict:
            break
        p = cand.phrase
        if any(p in q or q in p for q in selected):
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
    dictionary = _select_dictionary(src, phrase_lengths, max_dict)
    tokens = _encode_tokens(src, dictionary)
    if len(dictionary) > 255:
        raise ValueError("UBIR5 dictionary overflow")
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
