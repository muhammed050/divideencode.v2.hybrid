"""Benchmark Structural Engine v3 against raw DE2.

Run from repository root:
    python benchmarks/structural_v3_benchmark.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from divideencode.v2.codec import compress as de2_compress, decompress as de2_decompress
from divideencode.v2.structural_v3 import adaptive_transform, inverse
from structural_benchmark import datasets


def main() -> None:
    size = 128 * 1024
    workloads = list(datasets(size))
    print("=" * 118)
    print("DIVIDE STRUCTURAL ENGINE v3 — COMPOSITIONAL ADAPTIVE BENCHMARK")
    print(f"sample size : {size:,} bytes per workload")
    print("search      : RAW + bounded compositions, scored by DE2")
    print("goal        : minimize final DE2 size without regressions")
    print("=" * 118)

    wins = 0
    regressions = 0
    for name, data in workloads:
        baseline_blob = de2_compress(data)
        baseline = len(baseline_blob)

        def score(blob: bytes) -> int:
            return len(de2_compress(blob))

        decision = adaptive_transform(data, scorer=score, max_depth=2)
        final = de2_compress(decision.blob)
        assert de2_decompress(final) == decision.blob
        assert inverse(decision.blob) == data

        selected = len(final)
        delta = selected - baseline
        if selected < baseline:
            wins += 1
        elif selected > baseline:
            regressions += 1

        path = " -> ".join(decision.kinds) if decision.kinds else "raw"
        print(f"[{name}] selected={path:18s} "
              f"structural={decision.structural_size:9,} B "
              f"final={selected:9,} B "
              f"DE2={baseline:9,} B "
              f"delta={delta:+,} B")

    print("-" * 118)
    print(f"wins over raw DE2 : {wins}/{len(workloads)}")
    print(f"regressions       : {regressions}")
    assert regressions == 0, "Structural Engine v3 regressed against raw DE2"
    print("PASS: v3 adaptive layer never forces a worse representation on this suite.")


if __name__ == "__main__":
    main()
