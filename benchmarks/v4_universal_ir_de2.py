"""Benchmark UBIR candidates against direct DE2.

This is the first experiment for the universal-binary-IR direction.  It does
not assume that a file is text, source, JSON, or already-binary.  Every input
gets the same reversible representation search.

Usage:
    python benchmarks/v4_universal_ir_de2.py
    python benchmarks/v4_universal_ir_de2.py --trials 2 --workers 3
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress
from divideencode.universal_ir import Kind, rank, inverse

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"


def _de2(data: bytes):
    t = time.perf_counter()
    blob = de2_compress(data, block_size=1 << 20, level="BALANCED")
    enc = time.perf_counter() - t
    t = time.perf_counter()
    out = de2_decompress(blob)
    dec = time.perf_counter() - t
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return len(blob), enc, dec


def _trial(kind_value: int, payload: bytes, source: bytes):
    kind = Kind(kind_value)
    size, enc, dec = _de2(payload)
    restored = inverse(payload, kind, original_size=len(source))
    if restored != source:
        raise AssertionError(f"UBIR roundtrip mismatch: {kind.name}")
    return kind.name, size, enc, dec, len(payload)


def _normalize_de2_result(result):
    """Accept the normal 3-tuple and tolerate legacy 4/5-value workers.

    The benchmark previously crashed when a worker returned metadata in
    addition to size/encode/decode timing.  Keeping this normalization here
    makes the parent process resilient while preserving the displayed metrics.
    """
    if not isinstance(result, tuple) or len(result) < 3:
        raise ValueError(f"invalid DE2 result: {result!r}")
    return result[0], result[1], result[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3, help="top UBIR candidates sent to DE2")
    ap.add_argument("--workers", type=int, default=min(3, max(1, os.cpu_count() or 1)))
    args = ap.parse_args()
    trials = max(1, args.trials)
    workers = max(1, args.workers)

    files = sorted(p for p in CORPUS.iterdir() if p.is_file()) if CORPUS.exists() else []
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")

    print("UBIR1 — UNIVERSAL BINARY IR -> DE2")
    print(f"proxy ranks all transforms; DE2 trials={trials}; workers={workers}", flush=True)

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for no, path in enumerate(files, 1):
            src = path.read_bytes()
            ranked = rank(src)
            selected = ranked[:trials]

            print(f"\n[{no}/{len(files)}] {path.name}: preparing universal IR...", flush=True)
            print("  proxy ranking: " + ", ".join(f"{c.kind.name}={c.score:.1f}" for c in ranked), flush=True)

            futures = [("DIRECT", pool.submit(_de2, src))]
            futures.extend((c.kind.name, pool.submit(_trial, int(c.kind), c.payload, src)) for c in selected)

            print("=" * 100)
            print(f"{path.name} original={len(src):,} B")
            results = {}
            for label, future in futures:
                result = future.result()
                if label == "DIRECT":
                    size, enc, dec = _normalize_de2_result(result)
                    results[label] = (size, enc, dec)
                    print(f"  direct-DE2 {size:,} B ratio={size/len(src):.4f} enc={enc:.3f}s dec={dec:.3f}s", flush=True)
                else:
                    name, size, enc, dec, ir_size = result
                    results[name] = (size, enc, dec)
                    print(f"  {name:<12} IR={ir_size:,} B -> DE2={size:,} B ratio={size/len(src):.4f} enc={enc:.3f}s dec={dec:.3f}s ok", flush=True)

            best_name, best = min(results.items(), key=lambda x: x[1][0])
            direct = results["DIRECT"][0]
            gain = direct - best[0]
            print(f"  WINNER {best_name}; gain_vs_direct={gain:+,} B", flush=True)


if __name__ == "__main__":
    main()
