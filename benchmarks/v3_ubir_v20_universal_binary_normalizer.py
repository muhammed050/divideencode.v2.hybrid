"""V2.0 universal binary normalizer benchmark.

Every input is bytes. We generate reversible binary layouts, compress each
layout with DE2, decode DE2, restore the original bytes, and select the
smallest verified final container. The IR may grow substantially; only final
DE2 size decides the winner.
"""
from __future__ import annotations

import time
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress
from divideencode.v3 import universal_binary_normalizer as ubn

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"
FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def de2(data: bytes):
    t = time.perf_counter()
    packed = de2_compress(data, block_size=1 << 20, level="BALANCED")
    et = time.perf_counter() - t
    t = time.perf_counter()
    out = de2_decompress(packed)
    dt = time.perf_counter() - t
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return packed, et, dt


def candidate(data: bytes, name: str, transformed: bytes):
    envelope = ubn.pack(name, transformed, len(data))
    packed, et, dt = de2(envelope)
    restored = ubn.restore(de2_decompress(packed))
    if restored != data:
        raise AssertionError(f"{name} roundtrip mismatch")
    return packed, et, dt, len(envelope), len(transformed)


def main():
    print("V2.0 UNIVERSAL BINARY NORMALIZER -> DE2")
    print("metric = final DE2 bytes; IR expansion is allowed; every winner roundtrip-verified")
    print("baseline = DE2(original); candidates = reversible binary layouts -> DE2")

    for path in FILES:
        data = path.read_bytes()
        baseline, bet, bdt = de2(data)
        rows = [("DE2-direct", len(baseline), bet, bdt, len(data), len(data))]

        print("\n" + "=" * 108)
        print(f"{path.name}  original={len(data):,} B")
        print(f"  {'DE2-direct':<14} final={len(baseline):>10,} B ratio={len(baseline)/len(data):.4f} enc={bet:.2f}s dec={bdt:.2f}s")

        for name, transformed in ubn.candidates(data):
            if name == "raw":
                continue
            packed, et, dt, ir_size, transformed_size = candidate(data, name, transformed)
            rows.append((name, len(packed), et, dt, ir_size, transformed_size))
            print(
                f"  {name:<14} final={len(packed):>10,} B ratio={len(packed)/len(data):.4f} "
                f"IR={ir_size:,} B ({ir_size/len(data):.3f}x) transform={transformed_size:,} B "
                f"enc={et:.2f}s dec={dt:.2f}s"
            )

        winner = min(rows, key=lambda r: r[1])
        if winner[0] == "DE2-direct":
            improvement = 0
        else:
            improvement = len(baseline) - winner[1]
        print(
            f"  WINNER = {winner[0]} -> {winner[1]:,} B "
            f"({winner[1]/len(data):.4f}x), improvement_vs_direct={improvement:+,} B"
        )


if __name__ == "__main__":
    main()
