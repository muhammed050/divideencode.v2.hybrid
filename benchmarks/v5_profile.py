from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from divideencode.v2.codec import compress as de2_compress
from divideencode.v2.structural_v5 import analyze

N = 131072

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

def profile(name, data):
    t0 = time.perf_counter()
    candidates = analyze(data, max_depth=3)
    analyze_ms = (time.perf_counter() - t0) * 1000

    groups = {}
    valid = 0
    rejected = 0
    score_ms = 0.0
    best = (len(de2_compress(data)), "raw", len(data))

    for c in candidates:
        kind = "+".join(c.kinds) or "raw"
        groups[kind] = groups.get(kind, 0) + 1
        t1 = time.perf_counter()
        try:
            size = len(de2_compress(c.blob))
            valid += 1
            if size < best[0]:
                best = (size, kind, len(c.blob))
        except (OverflowError, ValueError):
            rejected += 1
        score_ms += (time.perf_counter() - t1) * 1000

    print(f"\n[{name}] {len(data):,} B")
    print(f"candidates : {len(candidates)} | valid={valid} rejected={rejected}")
    print(f"analyze    : {analyze_ms:,.2f} ms")
    print(f"DE2 scoring: {score_ms:,.2f} ms")
    print(f"best       : {best[1]} -> {best[0]:,} B (structural {best[2]:,} B)")
    print("candidate groups:")
    for kind, count in sorted(groups.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {kind:<35} {count}")


def main():
    print("=" * 100)
    print("DIVIDE STRUCTURAL V5 — SEARCH PROFILER")
    print("Purpose: identify candidate explosion and DE2 scoring cost before V6 optimization")
    print("=" * 100)
    for name, data in DATASETS.items():
        profile(name, data)

if __name__ == "__main__":
    main()
