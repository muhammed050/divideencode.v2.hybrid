from __future__ import annotations
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from divideencode.v2.codec import compress as de2_compress
from divideencode.v2.structural_v5 import adaptive_transform, inverse


def numeric_delta(n=131072):
    vals = range(1000, 1000 + (n // 4) * 7, 7)
    return b"".join(v.to_bytes(4, "little") for v in vals)[:n]

def csv_data(n=131072):
    row = b"100000,100001,100002,active,2026-08-23\n"
    return (row * (n // len(row) + 1))[:n]

def binary_records(n=131072):
    rows = []
    i = 0
    total = 0
    while total < n:
        row = i.to_bytes(4, "little") + (100000 + i * 3).to_bytes(4, "little") + bytes((i & 255, 7, 0, 1))
        rows.append(row); total += len(row); i += 1
    return b"".join(rows)[: n - (n % 12)]

def json_data(n=131072):
    row = b'{"id":1000,"name":"user","active":true,"score":42}\n'
    return (row * (n // len(row) + 1))[:n]

def logs(n=131072):
    row = b"2026-08-23T12:00:00 INFO worker request_id=123456 status=200\n"
    return (row * (n // len(row) + 1))[:n]

def main():
    workloads = {"numeric-delta": numeric_delta(), "csv": csv_data(), "json": json_data(), "logs": logs(), "binary-records": binary_records()}
    print("=" * 118)
    print("DIVIDE STRUCTURAL ENGINE v5 — STRUCTURE DISCOVERY BENCHMARK")
    print("sample size : ~131,072 bytes per workload")
    print("search      : RAW + record/column transforms + bounded compositions")
    print("goal        : minimize final DE2 size with zero regressions")
    print("=" * 118)
    wins = regressions = 0
    for name, data in workloads.items():
        raw_de2 = len(de2_compress(data))
        started = time.perf_counter()
        def score(blob): return len(de2_compress(blob))
        decision = adaptive_transform(data, scorer=score, max_depth=3)
        elapsed = time.perf_counter() - started
        final = decision.downstream_size
        assert final is not None and inverse(decision.blob) == data
        if final < raw_de2: wins += 1
        if final > raw_de2: regressions += 1
        print(f"[{name}] selected={'+'.join(decision.kinds) or 'raw':<34} structural={decision.structural_size:8d} B final={final:8d} B DE2={raw_de2:8d} B delta={final-raw_de2:+d} B search={elapsed:7.2f}s")
    print("-" * 118)
    print(f"wins over raw DE2 : {wins}/{len(workloads)}")
    print(f"regressions       : {regressions}")
    assert regressions == 0, "Structural Engine v5 regressed against raw DE2"
    print("PASS: v5 adaptive layer never forces a worse representation on this suite.")

if __name__ == "__main__":
    main()
