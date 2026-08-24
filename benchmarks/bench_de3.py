from __future__ import annotations

import argparse
import csv
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from divideencode.v2.codec import compress as de2_compress, decompress as de2_decompress
from divideencode.de3 import transform, inverse


def timed(fn, runs):
    vals = []
    result = None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = fn()
        vals.append(time.perf_counter() - t0)
    return result, statistics.median(vals)


def run_one(path, runs):
    raw = path.read_bytes()

    de2_blob, de2_enc = timed(lambda: de2_compress(raw), runs)
    _, de2_dec = timed(lambda: de2_decompress(de2_blob), runs)

    transformed, prep = timed(lambda: transform(raw), runs)
    de3_blob, de3_enc = timed(lambda: de2_compress(transformed), runs)

    def decode_de3():
        return inverse(de2_decompress(de3_blob))

    restored, de3_dec = timed(decode_de3, runs)
    if restored != raw:
        raise AssertionError(f"DE3 roundtrip failed: {path}")

    return {
        "file": path.name,
        "orig": len(raw),
        "de2_size": len(de2_blob),
        "de3_size": len(de3_blob),
        "transformed_size": len(transformed),
        "de2_ratio": len(de2_blob) / len(raw) if raw else 0,
        "de3_ratio": len(de3_blob) / len(raw) if raw else 0,
        "de2_enc": de2_enc,
        "de3_prep": prep,
        "de3_enc": de3_enc,
        "de3_total_enc": prep + de3_enc,
        "de2_dec": de2_dec,
        "de3_dec": de3_dec,
        "lossless": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("samples", type=pathlib.Path)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--csv", type=pathlib.Path, default=ROOT / "benchmarks/results/de3_benchmark.csv")
    args = ap.parse_args()

    files = sorted(p for p in args.samples.rglob("*") if p.is_file())
    rows = []
    for i, path in enumerate(files, 1):
        row = run_one(path, args.runs)
        rows.append(row)
        print(f"[{i}/{len(files)}] {path} ({row['orig']:,} B)")
        print(f"    DE2  {row['de2_size']:>9,} B ratio={row['de2_ratio']:.4f} enc={row['de2_enc']:.4f}s")
        print(f"    DE3  {row['de3_size']:>9,} B ratio={row['de3_ratio']:.4f} prep={row['de3_prep']:.4f}s enc={row['de3_enc']:.4f}s total={row['de3_total_enc']:.4f}s")

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    total_orig = sum(r["orig"] for r in rows)
    total_de2 = sum(r["de2_size"] for r in rows)
    total_de3 = sum(r["de3_size"] for r in rows)
    de2_enc = sum(r["de2_enc"] for r in rows)
    de3_enc = sum(r["de3_total_enc"] for r in rows)
    print("\nFINAL DE3 TEST")
    print("=" * 82)
    print(f"{'Algorithm':<12}{'Orig':>14}{'Comp':>14}{'Ratio':>10}{'Saved':>10}{'Enc(s)':>12}")
    print("-" * 82)
    for name, size, enc in [("DE2", total_de2, de2_enc), ("DE3", total_de3, de3_enc)]:
        ratio = size / total_orig
        print(f"{name:<12}{total_orig:>14,}{size:>14,}{ratio:>10.4f}{(1-ratio)*100:>9.2f}%{enc:>12.3f}")
    print("=" * 82)
    print(f"CSV: {args.csv}")


if __name__ == "__main__":
    main()
