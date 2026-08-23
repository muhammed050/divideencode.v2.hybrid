"""Benchmark Structural Engine v4 against raw DE2."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from divideencode.v2.codec import compress as de2_compress, decompress as de2_decompress
from divideencode.v2.structural_v4 import adaptive_transform, inverse
from structural_benchmark import datasets


def main() -> None:
    size = 128 * 1024
    workloads = list(datasets(size))
    print("=" * 118)
    print("DIVIDE STRUCTURAL ENGINE v4 — DEEP STRUCTURAL BENCHMARK")
    print(f"sample size : {size:,} bytes per workload")
    print("search      : RAW + v3 transforms + XOR/transpose compositions")
    print("goal        : improve final DE2 size with zero regressions")
    print("=" * 118)

    wins = 0
    regressions = 0
    rejected = 0
    for name, data in workloads:
        baseline = len(de2_compress(data))

        def score(blob: bytes) -> int:
            nonlocal rejected
            try:
                return len(de2_compress(blob))
            except (OverflowError, ValueError):
                # A structural candidate is not useful if the downstream
                # codec cannot represent it. Treat it as an invalid/high-cost
                # candidate instead of allowing the benchmark to abort.
                rejected += 1
                return 1 << 60

        decision = adaptive_transform(data, scorer=score, max_depth=3)
        final_blob = de2_compress(decision.blob)
        assert de2_decompress(final_blob) == decision.blob
        assert inverse(decision.blob) == data

        selected = baseline if not decision.kinds else len(final_blob)
        delta = selected - baseline
        if selected < baseline:
            wins += 1
        elif selected > baseline:
            regressions += 1

        path = " -> ".join(decision.kinds) if decision.kinds else "raw"
        print(f"[{name}] selected={path:30s} structural={decision.structural_size:9,} B "
              f"final={selected:9,} B DE2={baseline:9,} B delta={delta:+,} B")

    print("-" * 118)
    print(f"wins over raw DE2 : {wins}/{len(workloads)}")
    print(f"regressions       : {regressions}")
    print(f"rejected candidates: {rejected}")
    assert regressions == 0, "Structural Engine v4 regressed against raw DE2"
    print("PASS: v4 adaptive layer never forces a worse representation on this suite.")


if __name__ == "__main__":
    main()
