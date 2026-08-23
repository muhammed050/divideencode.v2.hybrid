"""Benchmark the downstream-aware Structural Decision Layer.

Run from repository root:
    python benchmarks/structural_adaptive_benchmark.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from divideencode.v2.codec import compress as de2_compress, decompress as de2_decompress
from divideencode.v2.structural import adaptive_transform, inverse
from structural_benchmark import datasets


def main() -> None:
    size = 128 * 1024
    print("=" * 112)
    print("DIVIDE STRUCTURAL ENGINE — ADAPTIVE DECISION BENCHMARK")
    print(f"sample size : {size:,} bytes per workload")
    print("decision    : RAW + structural candidates scored by DE2")
    print("goal        : never force a structural transform that hurts DE2")
    print("=" * 112)

    wins = 0
    regressions = 0
    for name, data in datasets(size):
        raw_de2 = de2_compress(data)

        def score(blob: bytes) -> int:
            return len(de2_compress(blob))

        decision = adaptive_transform(data, scorer=score)
        final = de2_compress(decision.blob)
        assert de2_decompress(final) == decision.blob
        assert inverse(decision.blob) == data

        baseline = len(raw_de2)
        selected = len(final)
        if selected < baseline:
            wins += 1
        elif selected > baseline:
            regressions += 1

        print(f"[{name}] selected={decision.kind:5s} "
              f"structural={decision.structural_size:9,} B "
              f"final={selected:9,} B "
              f"DE2={baseline:9,} B "
              f"delta={selected - baseline:+,} B")

    print("-" * 112)
    print(f"wins over raw DE2 : {wins}/{len(list(datasets(size)))}")
    print(f"regressions       : {regressions}")
    assert regressions == 0, "adaptive decision layer regressed against raw DE2"
    print("PASS: adaptive layer never forces a worse representation on this suite.")


if __name__ == "__main__":
    main()
