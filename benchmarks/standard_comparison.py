from __future__ import annotations

import gzip
import lzma
import os
import sys
import time
import zlib

# Allow `python benchmarks\standard_comparison.py` from the repository root.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import brotli
import zstandard as zstd

from divideencode.v2.codec import compress as de2_compress, decompress as de2_decompress
from divideencode.v2.structural_v5 import adaptive_transform, inverse

N = 131072
REPS = 3


def numeric_delta(n=N):
    vals = range(1000, 1000 + (n // 4) * 7, 7)
    return b"".join(v.to_bytes(4, "little") for v in vals)[:n]


def csv_data(n=N):
    row = b"100000,100001,100002,active,2026-08-23\n"
    return (row * (n // len(row) + 1))[:n]


def json_data(n=N):
    row = b'{"id":1000,"name":"user","active":true,"score":42}\n'
    return (row * (n // len(row) + 1))[:n]


def logs(n=N):
    row = b"2026-08-23T12:00:00 INFO worker request_id=123456 status=200\n"
    return (row * (n // len(row) + 1))[:n]


def binary_records(n=N):
    rows, total, i = [], 0, 0
    while total < n:
        row = i.to_bytes(4, "little") + (100000 + i * 3).to_bytes(4, "little") + bytes((i & 255, 7, 0, 1))
        rows.append(row)
        total += len(row)
        i += 1
    return b"".join(rows)[: n - (n % 12)]


DATASETS = {
    "numeric-delta": numeric_delta(),
    "csv": csv_data(),
    "json": json_data(),
    "logs": logs(),
    "binary-records": binary_records(),
}


def measure(fn, data):
    result = None
    best = float("inf")
    for _ in range(REPS):
        t0 = time.perf_counter()
        result = fn(data)
        best = min(best, time.perf_counter() - t0)
    return result, best


def standard(data, compressor, decompressor):
    blob, ct = measure(compressor, data)
    restored = decompressor(blob)
    if restored != data:
        raise RuntimeError("standard codec roundtrip failure")
    _, dt = measure(decompressor, blob)
    return len(blob), ct * 1000, dt * 1000


def de2(data):
    return standard(data, de2_compress, de2_decompress)


def v5(data):
    def score(blob):
        try:
            return len(de2_compress(blob))
        except (OverflowError, ValueError):
            return None

    t0 = time.perf_counter()
    decision = adaptive_transform(data, scorer=score, max_depth=3)
    search_ms = (time.perf_counter() - t0) * 1000
    if decision.downstream_size is None:
        raise RuntimeError("V5 found no DE2-valid representation")
    if inverse(decision.blob) != data:
        raise RuntimeError("V5 structural roundtrip failure")

    blob, ct = measure(de2_compress, decision.blob)
    restored = de2_decompress(blob)
    if inverse(restored) != data:
        raise RuntimeError("V5 + DE2 roundtrip failure")
    _, dt = measure(de2_decompress, blob)
    return len(blob), search_ms + ct * 1000, dt * 1000, "+".join(decision.kinds) or "raw"


def saved(original, size):
    return (1 - size / len(original)) * 100


def main():
    codecs = {
        "DE2": (de2_compress, de2_decompress),
        "Deflate-9": (lambda d: zlib.compress(d, 9), zlib.decompress),
        "GZIP-9": (lambda d: gzip.compress(d, compresslevel=9), gzip.decompress),
        "Zstd-19": (lambda d: zstd.ZstdCompressor(level=19).compress(d), zstd.ZstdDecompressor().decompress),
        "Brotli-11": (lambda d: brotli.compress(d, quality=11), brotli.decompress),
        "XZ-6": (lambda d: lzma.compress(d, preset=6, format=lzma.FORMAT_XZ), lambda d: lzma.decompress(d, format=lzma.FORMAT_XZ)),
    }
    totals = {name: 0 for name in codecs}
    totals["DE2+V5"] = 0
    wins = {name: 0 for name in totals}

    print("=" * 130)
    print("DIVIDEENCODE V5 vs STANDARD COMPRESSION ALGORITHMS")
    print(f"dataset size: {N:,} bytes | repetitions: {REPS}")
    print("=" * 130)

    for name, data in DATASETS.items():
        print(f"\n[{name}] {len(data):,} bytes")
        results = {}
        for codec, (enc, dec) in codecs.items():
            size, ct, dt = standard(data, enc, dec)
            results[codec] = (size, ct, dt, "-")
            totals[codec] += size
        size, ct, dt, kind = v5(data)
        results["DE2+V5"] = (size, ct, dt, kind)
        totals["DE2+V5"] += size

        winner = min(results, key=lambda k: results[k][0])
        for codec, (size, ct, dt, kind) in results.items():
            label = f"{codec} ({kind})" if codec == "DE2+V5" else codec
            print(f"{label:<32}{size:>9,} B  {saved(data,size):>7.2f}% saved  c={ct:>9.2f} ms  d={dt:>9.2f} ms")
        print(f"WINNER: {winner}")
        wins[winner] += 1

    print("\n" + "=" * 130)
    print("TOTAL SIZE ACROSS ALL DATASETS")
    print("=" * 130)
    for codec, total in sorted(totals.items(), key=lambda x: x[1]):
        print(f"{codec:<32}total={total:>10,} B  avg={total/len(DATASETS):>10.1f} B")

    print("\nWIN COUNT")
    for codec, count in sorted(wins.items(), key=lambda x: (-x[1], x[0])):
        print(f"{codec:<32}{count}/{len(DATASETS)}")

    print(f"\nBEST OVERALL BY TOTAL SIZE: {min(totals, key=totals.get)}")


if __name__ == "__main__":
    main()
