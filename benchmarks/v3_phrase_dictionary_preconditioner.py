"""DE2-aware phrase dictionary preconditioner experiment.

Discovers repeated byte phrases at arbitrary offsets, then lets DE2 judge the
*final* representation.  This version also builds mixed-length dictionaries:
a single dictionary can contain short phrases for local repetition and longer
phrases for repeated records/headers.  The dictionary is selected by measured
representation savings before the final DE2 test.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"


@dataclass(frozen=True)
class Candidate:
    name: str
    packed: bytes
    dictionary: tuple[bytes, ...]


def run_de2(data: bytes):
    t = time.perf_counter()
    blob = de2_compress(data, block_size=1 << 20, level="BALANCED")
    enc = time.perf_counter() - t
    t = time.perf_counter()
    out = de2_decompress(blob)
    dec = time.perf_counter() - t
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return blob, enc, dec


def _pack(dictionary: list[bytes], stream: bytes, original_size: int) -> bytes:
    if len(dictionary) > 255:
        raise ValueError("dictionary too large")
    out = bytearray(b"PD3")
    out.append(len(dictionary))
    out += struct.pack(">I", original_size)
    for phrase in dictionary:
        if not (3 <= len(phrase) <= 255):
            raise ValueError("invalid phrase length")
        out.append(len(phrase))
        out += phrase
    out += stream
    return bytes(out)


def _unpack(blob: bytes) -> tuple[tuple[bytes, ...], bytes, int]:
    if len(blob) < 8 or blob[:3] != b"PD3":
        raise ValueError("bad PD3")
    count = blob[3]
    original_size = struct.unpack(">I", blob[4:8])[0]
    pos = 8
    d: list[bytes] = []
    for _ in range(count):
        if pos >= len(blob):
            raise ValueError("truncated dictionary")
        n = blob[pos]
        pos += 1
        if n < 3 or pos + n > len(blob):
            raise ValueError("invalid dictionary entry")
        d.append(bytes(blob[pos:pos + n]))
        pos += n
    return tuple(d), bytes(blob[pos:]), original_size


def _decode(blob: bytes) -> bytes:
    dictionary, stream, original_size = _unpack(blob)
    out = bytearray()
    i = 0
    while i < len(stream):
        code = stream[i]
        i += 1
        if code == 0:
            if i >= len(stream):
                raise ValueError("truncated literal length")
            n = stream[i]
            i += 1
            if i + n > len(stream):
                raise ValueError("truncated literal")
            out += stream[i:i + n]
            i += n
        else:
            idx = code - 1
            if idx >= len(dictionary):
                raise ValueError("bad phrase id")
            out += dictionary[idx]
    if len(out) != original_size:
        raise ValueError(f"size mismatch: {len(out)} != {original_size}")
    return bytes(out)


def _discover(src: bytes, length: int, max_entries: int = 96, min_count: int = 3):
    """Find repeated phrases with bounded overlapping n-gram counting.

    The previous sampler stepped by length//2, which could miss highly useful
    phrases whose repetitions were shifted by a few bytes.  We scan every
    offset, but cap the number of positions for large inputs by using a stable
    stride only after the first window budget is exhausted.
    """
    if len(src) < length * min_count:
        return []

    counts: dict[bytes, int] = {}
    # Full-offset scan is cheap for short phrases. For long phrases, bound the
    # work while retaining several offset classes instead of one fixed stride.
    total = len(src) - length + 1
    if total <= 1_500_000:
        positions = range(total)
    else:
        stride = max(1, total // 1_500_000)
        positions = range(0, total, stride)

    for i in positions:
        p = src[i:i + length]
        counts[p] = counts.get(p, 0) + 1

    ranked = [(n, p) for p, n in counts.items() if n >= min_count]
    # Approximate byte coverage, not just occurrence count.  This favors phrases
    # that can remove more bytes from the intermediate representation.
    ranked.sort(key=lambda x: (-(x[0] * (x[1].__len__() - 2)), -x[0], x[1]))
    return [p for _, p in ranked[:max_entries]]


def _encode(src: bytes, dictionary: list[bytes]) -> bytes:
    by_first: dict[int, list[tuple[bytes, int]]] = {}
    for idx, p in enumerate(dictionary, 1):
        by_first.setdefault(p[0], []).append((p, idx))
    for k in by_first:
        by_first[k].sort(key=lambda x: len(x[0]), reverse=True)

    out = bytearray()
    i = 0
    literal = bytearray()
    while i < len(src):
        matches = by_first.get(src[i])
        found = None
        if matches:
            for p, idx in matches:
                if src.startswith(p, i):
                    found = (p, idx)
                    break
        if found:
            if literal:
                while literal:
                    n = min(255, len(literal))
                    out.append(0)
                    out.append(n)
                    out += literal[:n]
                    del literal[:n]
            p, idx = found
            out.append(idx)
            i += len(p)
        else:
            literal.append(src[i])
            i += 1
    while literal:
        n = min(255, len(literal))
        out.append(0)
        out.append(n)
        out += literal[:n]
        del literal[:n]
    return bytes(out)


def _mixed_dictionary(src: bytes, pools: dict[int, list[bytes]], limit: int = 255):
    """Build a mixed-length dictionary using measured encoded-size gain.

    A phrase gets credit for the bytes it removes from the current stream.  We
    repeatedly choose the best phrase by gain per dictionary byte, then re-encode
    once at the end.  This avoids spending the whole 255-entry budget on one
    phrase length.
    """
    selected: list[bytes] = []
    selected_set: set[bytes] = set()
    # Start with the strongest phrases from every length so mixed candidates do
    # not collapse to whichever length happened to have the largest pool.
    for length in sorted(pools):
        if pools[length]:
            p = pools[length][0]
            selected.append(p)
            selected_set.add(p)

    while len(selected) < limit:
        current = _encode(src, selected) if selected else src
        best = None
        best_score = 0.0
        # Only inspect a small top slice from each pool; the expensive part is
        # encoding, so this keeps the experiment bounded.
        for length, pool in pools.items():
            for p in pool[:16]:
                if p in selected_set:
                    continue
                trial = selected + [p]
                trial_stream = _encode(src, trial)
                gain = len(current) - len(trial_stream)
                # Dictionary entry costs one length byte + phrase bytes.  Give a
                # slight bonus to repeated use without hard-coding one phrase size.
                cost = len(p) + 1
                score = gain / cost if cost else 0.0
                if gain > 0 and score > best_score:
                    best_score = score
                    best = p
        if best is None:
            break
        selected.append(best)
        selected_set.add(best)
        # Once gains become tiny, remaining entries are unlikely to help DE2.
        if best_score < 0.15:
            break
    return selected


def candidates(src: bytes):
    lengths = (3, 4, 5, 6, 8, 12, 16, 24, 32, 48, 64)
    pools = {length: _discover(src, length) for length in lengths}

    # Keep the original single-length matrix for an honest apples-to-apples
    # comparison with the previous experiment.
    for length in lengths:
        dictionary = pools[length]
        if dictionary:
            packed = _pack(dictionary, _encode(src, dictionary), len(src))
            yield Candidate(f"phrase{length}", packed, tuple(dictionary))

    # New adaptive candidates.  Different budgets matter because DE2 may prefer
    # a small dictionary with a very clean symbol stream over a maximal one.
    for limit in (32, 64, 96, 128, 192, 255):
        dictionary = _mixed_dictionary(src, pools, limit=limit)
        if len(dictionary) < 2:
            continue
        packed = _pack(dictionary, _encode(src, dictionary), len(src))
        yield Candidate(f"mixed{limit}", packed, tuple(dictionary))


def main():
    files = sorted(p for p in CORPUS.iterdir() if p.is_file()) if CORPUS.exists() else []
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")
    print("DE2-AWARE PHRASE DICTIONARY v2")
    print("single-length + mixed adaptive dictionaries -> IDs -> DE2; winner = smallest verified final DE2")

    for path in files:
        src = path.read_bytes()
        direct, de, dd = run_de2(src)
        print("\n" + "=" * 100)
        print(f"{path.name} original={len(src):,} B")
        print(f"  direct-DE2 final={len(direct):,} B ratio={len(direct)/len(src):.4f} enc={de:.3f}s dec={dd:.3f}s")
        best_size = len(direct)
        best_name = "direct-DE2"
        for cand in candidates(src):
            blob, enc, dec = run_de2(cand.packed)
            restored = _decode(de2_decompress(blob))
            if restored != src:
                raise AssertionError(f"{cand.name} roundtrip mismatch")
            final = len(blob)
            print(f"  {cand.name:<10} dict={len(cand.dictionary):>3} repr={len(cand.packed):>9,} B DE2={final:>9,} B ratio={final/len(src):.4f} enc={enc:.3f}s dec={dec:.3f}s ok")
            if final < best_size:
                best_size = final
                best_name = cand.name
        if best_name == "direct-DE2":
            print(f"  WINNER direct-DE2; candidate_delta={best_size-len(direct):+,} B")
        else:
            print(f"  WINNER {best_name}; gain_vs_direct={len(direct)-best_size:+,} B")


if __name__ == "__main__":
    main()
