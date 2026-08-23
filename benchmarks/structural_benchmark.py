"""Benchmark Structural Engine against DE2 and standard baselines.

Run from the repository root:
    python benchmarks/structural_benchmark.py
"""
from __future__ import annotations

# Make direct execution from the repository root independent of the caller's
# PYTHONPATH. pytest already does this implicitly, but `python benchmarks/...`
# does not because Python starts with the benchmarks directory on sys.path.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import gzip
import io
import json
import struct
import time
import zipfile
import zlib
from dataclasses import dataclass

from divideencode.v2.codec import compress as de2_compress, decompress as de2_decompress
from divideencode.v2.structural import analyze, inverse, transform


@dataclass
class Result:
    name: str
    original: int
    structural: int
    de2: int
    structural_de2: int
    zlib: int
    gzip: int
    zip: int
    structural_kind: str
    transform_ms: float
    de2_ms: float
    structural_de2_ms: float


def _repeat_to_size(block: bytes, size: int) -> bytes:
    if not block:
        return b""
    return (block * ((size + len(block) - 1) // len(block)))[:size]


def make_numeric(size: int) -> bytes:
    n = max(4, size // 4)
    return b"".join(struct.pack("<I", 1000 + i * 7) for i in range(n))[:size]


def make_csv(size: int) -> bytes:
    rows = []
    for i in range(max(1, size // 70)):
        rows.append(
            f"{i},Istanbul,{20 + i % 31},{1000 + (i * 7) % 9000},"
            f"ACTIVE,2026-08-{1 + i % 28:02d}\n"
        )
    return _repeat_to_size("".join(rows).encode(), size)


def make_json(size: int) -> bytes:
    rows = []
    for i in range(max(1, size // 150)):
        rows.append({
            "id": i,
            "city": "Istanbul",
            "status": "active" if i % 5 else "pending",
            "score": 1000 + i * 7,
            "category": "standard",
            "tags": ["user", "record", "2026"],
        })
    data = json.dumps(rows, separators=(",", ":")).encode()
    return _repeat_to_size(data, size)


def make_logs(size: int) -> bytes:
    levels = ("INFO", "INFO", "INFO", "WARN", "ERROR")
    services = ("api", "worker", "auth", "billing")
    rows = []
    i = 0
    total = 0
    while total < size:
        level = levels[i % len(levels)]
        service = services[i % len(services)]
        row = (
            f"2026-08-23T11:{i % 60:02d}:{i % 60:02d}Z {level} "
            f"service={service} request_id={i % 4096:04d} "
            f"user_id={1000 + i % 5000} status={200 if level != 'ERROR' else 500} "
            f"message=request_completed latency_ms={3 + i % 97}\n"
        )
        rows.append(row)
        total += len(row)
        i += 1
    return "".join(rows).encode()[:size]


def make_binary(size: int) -> bytes:
    out = bytearray()
    i = 0
    while len(out) + 24 <= size:
        out += struct.pack(
            "<IIHBBQII",
            i,
            1000 + i * 3,
            i % 4096,
            i % 8,
            1 if i % 10 else 2,
            1700000000 + i * 60,
            42,
            7,
        )
        i += 1
    return bytes(out[:size])


def datasets(size: int):
    return [
        ("numeric-delta", make_numeric(size)),
        ("csv", make_csv(size)),
        ("json", make_json(size)),
        ("logs", make_logs(size)),
        ("binary-records", make_binary(size)),
    ]


def zip_deflate(data: bytes) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("data.bin", data)
    return bio.getvalue()


def _best_kind(data: bytes) -> str:
    candidates = analyze(data)
    return candidates[0].kind if candidates else "raw"


def bench_one(name: str, data: bytes) -> Result:
    t0 = time.perf_counter()
    structural = transform(data)
    transform_ms = (time.perf_counter() - t0) * 1000
    assert inverse(structural) == data, f"structural roundtrip failed: {name}"

    t0 = time.perf_counter()
    de2 = de2_compress(data)
    de2_ms = (time.perf_counter() - t0) * 1000
    assert de2_decompress(de2) == data, f"DE2 roundtrip failed: {name}"

    t0 = time.perf_counter()
    structural_de2 = de2_compress(structural)
    structural_de2_ms = (time.perf_counter() - t0) * 1000
    assert de2_decompress(structural_de2) == structural
    assert inverse(de2_decompress(structural_de2)) == data

    z = zlib.compress(data, 9)
    g = gzip.compress(data, compresslevel=9, mtime=0)
    zz = zip_deflate(data)

    return Result(
        name=name,
        original=len(data),
        structural=len(structural),
        de2=len(de2),
        structural_de2=len(structural_de2),
        zlib=len(z),
        gzip=len(g),
        zip=len(zz),
        structural_kind=_best_kind(data),
        transform_ms=transform_ms,
        de2_ms=de2_ms,
        structural_de2_ms=structural_de2_ms,
    )


def pct(size: int, original: int) -> str:
    return f"{100.0 * (1.0 - size / original):6.2f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=128 * 1024, help="bytes per generated sample")
    args = ap.parse_args()

    print("=" * 118)
    print("DIVIDE STRUCTURAL ENGINE — COMPRESSION BENCHMARK")
    print(f"sample size : {args.size:,} bytes per workload")
    print("pipeline    : raw -> structural -> DE2")
    print("baselines   : DE2, zlib-9, gzip-9, ZIP-deflate-9")
    print("=" * 118)
    print()

    results = []
    for name, data in datasets(args.size):
        r = bench_one(name, data)
        results.append(r)
        print(f"[{r.name}] structural={r.structural_kind:5s} "
              f"transform={r.transform_ms:8.1f}ms "
              f"DE2={r.de2_ms:8.1f}ms "
              f"struct+DE2={r.structural_de2_ms:8.1f}ms")
        print(f"  original        {r.original:9,} B")
        print(f"  structural      {r.structural:9,} B  saved {pct(r.structural, r.original)}")
        print(f"  structural+DE2  {r.structural_de2:9,} B  saved {pct(r.structural_de2, r.original)}")
        print(f"  DE2             {r.de2:9,} B  saved {pct(r.de2, r.original)}")
        print(f"  zlib-9          {r.zlib:9,} B  saved {pct(r.zlib, r.original)}")
        print(f"  gzip-9          {r.gzip:9,} B  saved {pct(r.gzip, r.original)}")
        print(f"  ZIP-deflate-9   {r.zip:9,} B  saved {pct(r.zip, r.original)}")
        print()

    print("=" * 118)
    print("SUMMARY — final compressed size (smaller is better)")
    print("workload          struct+DE2       DE2          zlib          gzip           ZIP")
    print("-" * 118)
    for r in results:
        print(f"{r.name:16s} {r.structural_de2:12,} {r.de2:12,} {r.zlib:12,} "
              f"{r.gzip:12,} {r.zip:12,}")

    wins = sum(r.structural_de2 < min(r.de2, r.zlib, r.gzip, r.zip) for r in results)
    print()
    print(f"structural+DE2 wins: {wins}/{len(results)} workloads")
    print("NOTE: this is an empirical benchmark; no claim of universal superiority is made.")


if __name__ == "__main__":
    main()
