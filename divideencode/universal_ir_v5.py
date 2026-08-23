"""UBIR5 — universal phrase/token translator for DE2.

Goal: turn arbitrary byte streams into a small alphabet + explicit dictionary
language that DE2 can model easily.  It is reversible and may grow; DE2
chooses whether the representation is actually useful.
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


def _count_nonoverlap(src: bytes, phrase: bytes) -> int:
    n = len(phrase)
    if n == 0:
        return 0
    count = 0
    i = 0
    while i <= len(src) - n:
        j = src.find(phrase, i)
        if j < 0:
            break
        count += 1
        i = j + n
    return count


def _candidate_phrases(src: bytes, lengths: tuple[int, ...], max_dict: int) -> list[PhraseCandidate]:
    candidates: list[PhraseCandidate] = []
    # Fixed-length windows keep analysis predictable and fast.  We sample the
    # whole input for small files and a bounded prefix for very large files.
    sample = src if len(src) <= 8 * 1024 * 1024 else src[:8 * 1024 * 1024]
    for length in lengths:
        if length > len(sample):
            continue
        counts = Counter(sample[i:i + length] for i in range(len(sample) - length + 1))
        for phrase, freq in counts.most_common(max_dict * 3):
            if freq < 2:
                break
            # A token costs 2 bytes in the IR (ESC + id).  Dictionary storage
            # costs the phrase length once.  Only retain phrases with a clear
            # gross saving before overlap effects.
            gain = freq * max(0, length - 2) - length
            if gain > 0:
                candidates.append(PhraseCandidate(phrase, freq, gain))
    candidates.sort(key=lambda x: (x.gain, x.count, len(x.phrase)), reverse=True)
    return candidates[: max_dict * 8]


def _select_dictionary(src: bytes, lengths: tuple[int, ...], max_dict: int) -> list[bytes]:
    selected: list[bytes] = []
    working = src
    for cand in _candidate_phrases(src, lengths, max_dict):
        if len(selected) >= max_dict:
            break
        # Re-evaluate against already selected phrases.  This discourages a
        # large dictionary full of overlapping variants.
        if any(cand.phrase in p or p in cand.phrase for p in selected):
            continue
        count = _count_nonoverlap(working, cand.phrase)
        if count >= 2 and count * (len(cand.phrase) - 2) > len(cand.phrase):
            selected.append(cand.phrase)
            working = _replace_with_marker(working, cand.phrase, b"")
    return selected


def _replace_with_marker(src: bytes, phrase: bytes, marker: bytes) -> bytes:
    if not phrase:
        return src
    out = bytearray()
    i = 0
    n = len(phrase)
    while i < len(src):
        if i + n <= len(src) and src[i:i + n] == phrase:
            out.extend(marker)
            i += n
        else:
            out.append(src[i])
            i += 1
    return bytes(out)


def _encode_tokens(src: bytes, dictionary: list[bytes]) -> bytes:
    # Literal bytes are escaped only when they equal ESC.  Phrase references
    # are ESC, id+1.  Thus the token alphabet remains tiny and deterministic.
    by_first: dict[int, list[tuple[bytes, int]]] = {}
    for idx, phrase in enumerate(dictionary):
        by_first.setdefault(phrase[0], []).append((phrase, idx + 1))
    for values in by_first.values():
        values.sort(key=lambda x: len(x[0]), reverse=True)
    out = bytearray()
    i = 0
    while i < len(src):
        matches = by_first.get(src[i])
        matched = None
        if matches:
            for phrase, token in matches:
                if src.startswith(phrase, i):
                    matched = (phrase, token)
                    break
        if matched:
            out.extend((ESC, matched[1]))
            i += len(matched[0])
        else:
            b = src[i]
            if b == ESC:
                out.extend((ESC, 0))
            else:
                out.append(b)
            i += 1
    return bytes(out)


def _decode_tokens(tokens: bytes, dictionary: list[bytes]) -> bytes:
    out = bytearray()
    i = 0
    while i < len(tokens):
        b = tokens[i]
        if b != ESC:
            out.append(b)
            i += 1
            continue
        if i + 1 >= len(tokens):
            raise ValueError("truncated UBIR5 escape")
        code = tokens[i + 1]
        if code == 0:
            out.append(ESC)
        elif code - 1 < len(dictionary):
            out.extend(dictionary[code - 1])
        else:
            raise ValueError("invalid UBIR5 dictionary reference")
        i += 2
    return bytes(out)


def encode(src: bytes, *, phrase_lengths: tuple[int, ...] = (4, 5, 6, 8, 12, 16), max_dict: int = 255) -> tuple[bytes, list[bytes]]:
    src = bytes(src)
    dictionary = _select_dictionary(src, phrase_lengths, max_dict)
    tokens = _encode_tokens(src, dictionary)
    # Dictionary and token stream are kept as separate regions.  The container
    # is intentionally simple: MAGIC, count, lengths, dictionary bytes, tokens.
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
