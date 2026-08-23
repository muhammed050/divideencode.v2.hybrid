"""DE2-aware phrase6 preconditioner experiments.

Phrase6 is the strongest general candidate found so far.  This benchmark
removes the broad phrase-length matrix and concentrates the search budget on
variants derived from 6-byte phrases.  Every candidate is judged by the final
DE2 size and must round-trip exactly.
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


def _discover6(src: bytes, max_entries: int = 255, min_count: int = 3):
    """Rank all repeated 6-byte phrases by useful coverage.

    Unlike the old mixed-length search, the experiment deliberately spends its
    discovery budget only on six-byte phrases.  This keeps comparisons clean
    and makes each new variant a real improvement over phrase6 rather than a
    different compressor.
    """
    length = 6
    if len(src) < length * min_count:
        return []
    counts: dict[bytes, int] = {}
    total = len(src) - length + 1
    # Keep runtime bounded while still sampling every offset on normal corpus
    # files.  Large files use a deterministic dense stride.
    stride = max(1, total // 2_000_000)
    for i in range(0, total, stride):
        p = src[i:i + length]
        counts[p] = counts.get(p, 0) + 1
    ranked = [(n, p) for p, n in counts.items() if n >= min_count]
    ranked.sort(key=lambda x: (-(x[0] * 4), -x[0], x[1]))
    return [p for _, p in ranked[:max_entries]]


def _encode(src: bytes, dictionary: list[bytes]) -> bytes:
    by_first: dict[int, list[tuple[bytes, int]]] = {}
    for idx, p in enumerate(dictionary, 1):
        by_first.setdefault(p[0], []).append((p, idx))
    out = bytearray()
    literal = bytearray()
    i = 0
    while i < len(src):
        found = None
        for p, idx in by_first.get(src[i], ()):
            if src.startswith(p, i):
                found = (p, idx)
                break
        if found:
            if literal:
                while literal:
                    n = min(255, len(literal))
                    out.append(0); out.append(n); out += literal[:n]
                    del literal[:n]
            p, idx = found
            out.append(idx)
            i += 6
        else:
            literal.append(src[i])
            i += 1
    while literal:
        n = min(255, len(literal))
        out.append(0); out.append(n); out += literal[:n]
        del literal[:n]
    return bytes(out)


def _frequency6(src: bytes, pool: list[bytes], limit: int) -> list[bytes]:
    """Original phrase6 strategy: frequency/coverage ranking."""
    return pool[:limit]


def _nonoverlap6(src: bytes, pool: list[bytes], limit: int) -> list[bytes]:
    """Prefer phrases whose occurrences are useful without overlap waste."""
    scored = []
    for p in pool:
        count = 0
        pos = 0
        while True:
            j = src.find(p, pos)
            if j < 0:
                break
            count += 1
            pos = j + 6
        scored.append((count * 4, count, p))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [p for _, _, p in scored[:limit]]


def _greedy6(src: bytes, pool: list[bytes], limit: int, top_probe: int = 24) -> list[bytes]:
    """Greedy phrase6 dictionary: choose entries by measured stream gain."""
    selected: list[bytes] = []
    selected_set: set[bytes] = set()
    current_len = len(src)
    remaining = pool[:]
    while len(selected) < limit and remaining:
        best = None
        best_gain = 0
        for p in remaining[:top_probe]:
            trial = _encode(src, selected + [p])
            gain = current_len - len(trial)
            # One dictionary entry costs one length byte plus six phrase bytes.
            gain -= 7
            if gain > best_gain:
                best_gain = gain
                best = p
        if best is None:
            break
        selected.append(best)
        selected_set.add(best)
        current_len = len(_encode(src, selected))
        remaining = [p for p in remaining if p not in selected_set]
    return selected


def _greedy6_reorder(src: bytes, pool: list[bytes], limit: int) -> list[bytes]:
    """Build with measured gains, then reorder IDs by stream frequency.

    The byte stream is semantically identical after re-encoding, but putting
    the most frequent IDs first can improve DE2's symbol statistics in some
    inputs because IDs become a compact low-valued alphabet.
    """
    selected = _greedy6(src, pool, limit, top_probe=32)
    if not selected:
        return []
    freq = []
    stream = _encode(src, selected)
    counts = [0] * len(selected)
    i = 0
    while i < len(stream):
        code = stream[i]; i += 1
        if code:
            counts[code - 1] += 1
        else:
            if i >= len(stream):
                break
            n = stream[i]; i += 1 + n
    freq = sorted(range(len(selected)), key=lambda i: (-counts[i], selected[i]))
    return [selected[i] for i in freq]


def candidates(src: bytes):
    pool = _discover6(src)
    if not pool:
        return

    # Only phrase6-derived candidates remain.  Limits cover the useful small,
    # medium and full dictionaries without reopening the old length matrix.
    for limit in (48, 96, 128, 192, 255):
        variants = (
            (f"phrase6_freq{limit}", _frequency6(src, pool, limit)),
            (f"phrase6_nonoverlap{limit}", _nonoverlap6(src, pool, limit)),
            (f"phrase6_greedy{limit}", _greedy6(src, pool, limit)),
            (f"phrase6_greedy_reorder{limit}", _greedy6_reorder(src, pool, limit)),
        )
        for name, dictionary in variants:
            if not dictionary:
                continue
            packed = _pack(dictionary, _encode(src, dictionary), len(src))
            yield Candidate(name, packed, tuple(dictionary))


def main():
    files = sorted(p for p in CORPUS.iterdir() if p.is_file()) if CORPUS.exists() else []
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")
    print("DE2-AWARE PHRASE6 VARIANTS")
    print("frequency + non-overlap + greedy + ID-reorder; winner = smallest verified final DE2")

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
            ok = _decode(cand.packed) == src
            if not ok:
                raise AssertionError(f"preconditioner roundtrip mismatch: {cand.name}")
            if len(blob) < best_size:
                best_size = len(blob)
                best_name = cand.name
            print(f"  {cand.name:<25} dict={len(cand.dictionary):3d} repr={len(cand.packed):9,d} DE2={len(blob):9,d} ratio={len(blob)/len(src):.4f} enc={enc:.3f}s dec={dec:.3f}s ok")
        print(f"  WINNER {best_name}; gain_vs_direct={len(direct)-best_size:+,} B")


if __name__ == "__main__":
    main()
