"""Fast DE2-aware phrase6 preconditioner benchmark.

Phrase6 is the strongest candidate found so far. This version keeps the
experiment focused on frequency-ranked 6-byte dictionaries, removes the
expensive greedy/non-overlap search, uses O(1) phrase lookup during encoding,
and uses a cheap proxy stage to avoid running DE2 for every dictionary size.

DE2 trials are executed in parallel processes so wall-clock time is closer to
the slowest trial instead of the sum of all trials. Use --workers to tune the
CPU/memory trade-off (default: up to 3 workers).
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from concurrent.futures import ProcessPoolExecutor
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


def _trial_candidate(cand: Candidate, src: bytes):
    """Run one candidate in a worker process."""
    blob, enc, dec = run_de2(cand.packed)
    ok = _decode(cand.packed) == src
    if not ok:
        raise AssertionError(f"preconditioner roundtrip mismatch: {cand.name}")
    return cand.name, len(blob), enc, dec


def _trial_direct(src: bytes):
    """Run direct DE2 in a worker process."""
    blob, enc, dec = run_de2(src)
    return len(blob), enc, dec


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
    """Discover repeated 6-byte phrases with bounded deterministic work."""
    length = 6
    if len(src) < length * min_count:
        return []
    counts: dict[bytes, int] = {}
    total = len(src) - length + 1
    stride = max(1, total // 2_000_000)
    for i in range(0, total, stride):
        p = src[i:i + length]
        counts[p] = counts.get(p, 0) + 1
    ranked = [(n, p) for p, n in counts.items() if n >= min_count]
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return [p for _, p in ranked[:max_entries]]


def _encode(src: bytes, dictionary: list[bytes]) -> bytes:
    """Fast phrase6 encoder: all phrases have length six, so use O(1) lookup."""
    ids = {p: idx for idx, p in enumerate(dictionary, 1)}
    out = bytearray()
    literal_start = 0
    i = 0
    n = len(src)

    while i + 6 <= n:
        idx = ids.get(src[i:i + 6])
        if idx is None:
            i += 1
            continue
        if literal_start < i:
            literal = src[literal_start:i]
            pos = 0
            while pos < len(literal):
                chunk = literal[pos:pos + 255]
                out.append(0)
                out.append(len(chunk))
                out += chunk
                pos += len(chunk)
        out.append(idx)
        i += 6
        literal_start = i

    if literal_start < n:
        literal = src[literal_start:]
        pos = 0
        while pos < len(literal):
            chunk = literal[pos:pos + 255]
            out.append(0)
            out.append(len(chunk))
            out += chunk
            pos += len(chunk)
    return bytes(out)


def _frequency6(pool: list[bytes], limit: int) -> list[bytes]:
    return pool[:limit]


def candidates(src: bytes, max_de2_trials: int = 3):
    """Build cheap proxies, then send only the most promising to DE2."""
    pool = _discover6(src)
    if not pool:
        return

    limits = (64, 96, 112, 128, 144, 160, 192, 255)
    proxies: list[tuple[int, int, Candidate]] = []
    for limit in limits:
        dictionary = _frequency6(pool, limit)
        if not dictionary:
            continue
        packed = _pack(dictionary, _encode(src, dictionary), len(src))
        proxies.append((len(packed), limit, Candidate(
            f"phrase6_freq{limit}", packed, tuple(dictionary))))

    proxies.sort(key=lambda x: (x[0], x[1]))
    chosen: list[tuple[int, int, Candidate]] = []
    seen: set[int] = set()

    def add_at(index: int):
        if 0 <= index < len(proxies):
            item = proxies[index]
            if item[1] not in seen and len(chosen) < max_de2_trials:
                chosen.append(item)
                seen.add(item[1])

    add_at(0)
    for idx, item in enumerate(proxies):
        if item[1] == 255:
            add_at(idx)
            break
    add_at(len(proxies) // 2)

    for _, _, cand in chosen:
        yield cand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int,
                    default=min(3, max(1, os.cpu_count() or 1)),
                    help="parallel DE2 worker processes (default: up to 3)")
    args = ap.parse_args()
    workers = max(1, args.workers)

    files = sorted(p for p in CORPUS.iterdir() if p.is_file()) if CORPUS.exists() else []
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")

    print("DE2-AWARE PHRASE6 — SPEED-AWARE SEARCH")
    print(f"cheap proxy ranking + parallel DE2 trials + direct-DE2 fallback (workers={workers})", flush=True)

    total_files = len(files)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for file_no, path in enumerate(files, 1):
            src = path.read_bytes()
            print(f"\n[{file_no}/{total_files}] {path.name}: preparing candidates...", flush=True)
            cands = list(candidates(src, max_de2_trials=3))

            # Direct DE2 and all selected phrase trials start together.
            futures = [
                ("direct", pool.submit(_trial_direct, src)),
                *[(cand.name, pool.submit(_trial_candidate, cand, src)) for cand in cands],
            ]

            print("=" * 100)
            print(f"{path.name} original={len(src):,} B")
            results = {}
            for name, future in futures:
                if name == "direct":
                    size, enc, dec = future.result()
                    results[name] = (size, enc, dec)
                    print(f"  direct-DE2 final={size:,} B ratio={size/len(src):.4f} enc={enc:.3f}s dec={dec:.3f}s", flush=True)
                else:
                    cname, size, enc, dec = future.result()
                    results[cname] = (size, enc, dec)
                    print(f"  {cname:<25} DE2={size:,} B ({enc:.3f}s) ok", flush=True)

            best_name, best = min(results.items(), key=lambda x: x[1][0])
            direct_size = results["direct"][0]
            print(f"  WINNER {best_name}; gain_vs_direct={direct_size-best[0]:+,} B", flush=True)
            sys.stdout.flush()


if __name__ == "__main__":
    main()
