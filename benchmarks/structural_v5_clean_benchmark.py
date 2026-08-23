from __future__ import annotations
import time
import sys
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
    rows, total, i = [], 0, 0
    while total < n:
        row = i.to_bytes(4, "little") + (100000 + i * 3).to_bytes(4, "little") + bytes((i & 255, 7, 0, 1))
        rows.append(row)
        total += len(row)
        i += 1
    return b"".join(rows)[: n - (n % 12)]


def json_data(n=131072):
    row = b'{"id":1000,"name":"user","active":true,"score":42}\n'
    return (row * (n // len(row) + 1))[:n]


def logs(n=131072):
    row = b"2026-08-23T12:00:00 INFO worker request_id=123456 status=200\n"
    return (row * (n // len(row) + 1))[:n]


def score(blob):
    # Invalid downstream candidates are rejected by raising.  Do not encode
    # rejection as sys.maxsize: that can make an invalid candidate look like
    # a real compressed result when the RAW score is also unavailable.
    try:
        return len(de2_compress(blob))
    except (OverflowError, ValueError) as exc:
        raise ValueError("DE2 rejected structural candidate") from exc


def main():
    workloads = {
        "numeric-delta": numeric_delta(),
        "csv": csv_data(),
        "json": json_data(),
        "logs": logs(),
        "binary-records": binary_records(),
    }
    print("=" * 118)
    print("DIVIDE STRUCTURAL ENGINE v5 — CLEAN DE2 VALIDATION BENCHMARK")
    print("invalid DE2 candidates: rejected, never represented as a size")
    print("goal: minimize final DE2 size with zero regressions")
    print("=" * 118)
    wins = regressions = 0
    for name, data in workloads.items():
        raw = score(data)
        started = time.perf_counter()
        decision = adaptive_transform(data, scorer=score, max_depth=3)
        elapsed = time.perf_counter() - started
        if decision.downstream_size is None:
            raise RuntimeError(f"no DE2-valid representation: {name}")
        final = decision.downstream_size
        assert inverse(decision.blob) == data
        delta = final - raw
        wins += final < raw
        regressions += final > raw
        print(f"[{name}] selected={'+'.join(decision.kinds) or 'raw':<30} final={final:8d} B raw-DE2={raw:8d} B delta={delta:+d} B search={elapsed:6.2f}s")
    print("-" * 118)
    print(f"wins over raw DE2 : {wins}/{len(workloads)}")
    print(f"regressions       : {regressions}")
    assert regressions == 0
    print("PASS: no invalid DE2 candidate is counted as a compression result.")


if __name__ == "__main__":
    main()
