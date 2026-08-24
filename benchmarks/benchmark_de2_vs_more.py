from __future__ import annotations

import argparse
import bz2
import gzip
import hashlib
import lzma
import shutil
import subprocess
import time
import zlib
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress

ROOT = Path(__file__).parent / "corpus"


def optional(cmd: str):
    return shutil.which(cmd)


def run_cmd(cmd, data: bytes):
    p = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode(errors="replace"))
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--limit", type=int, default=0, help="maximum bytes per file; 0 = unlimited")
    args = ap.parse_args()

    algorithms = {
        "DE2": lambda x: de2_compress(x, level="BALANCED"),
        "zlib-9": lambda x: zlib.compress(x, 9),
        "gzip-9": lambda x: gzip.compress(x, 9),
        "bz2-9": lambda x: bz2.compress(x, 9),
        "lzma-9": lambda x: lzma.compress(x, preset=9),
    }
    if optional("zstd"):
        algorithms["zstd-19"] = lambda x: run_cmd(["zstd", "-19", "-q", "-c"], x)
    if optional("brotli"):
        algorithms["brotli-11"] = lambda x: run_cmd(["brotli", "-11", "-q", "-c"], x)
    if optional("lz4"):
        algorithms["lz4"] = lambda x: run_cmd(["lz4", "-q", "-c"], x)
    if optional("xz"):
        algorithms["xz-9"] = lambda x: run_cmd(["xz", "-9", "-c"], x)
    if optional("7z"):
        algorithms["7z-xz"] = lambda x: run_cmd(["7z", "a", "-si", "-so", "-txz", "-mx=9"], x)

    files = sorted(p for p in args.root.rglob("*") if p.is_file())
    if not files:
        raise SystemExit(f"No files found under {args.root}")

    totals = {k: 0 for k in algorithms}
    wins = {k: 0 for k in algorithms}
    times = {k: 0.0 for k in algorithms}
    original_total = 0
    rows = []

    print("DE2 BROAD COMPRESSION BENCHMARK")
    print("=" * 150)
    print("Algorithms: " + ", ".join(algorithms))
    print(f"Files: {len(files)}")
    print("-" * 150)

    for path in files:
        data = path.read_bytes()
        if args.limit and len(data) > args.limit:
            data = data[:args.limit]
        original_total += len(data)
        result = {}
        for name, fn in algorithms.items():
            t = time.perf_counter()
            blob = fn(data)
            elapsed = time.perf_counter() - t
            result[name] = (len(blob), elapsed)
            totals[name] += len(blob)
            times[name] += elapsed

        best = min(result, key=lambda k: result[k][0])
        wins[best] += 1
        rows.append((path.name, len(data), result, best))
        print(f"{path.name:<30}{len(data):>12,}  " + "  ".join(f"{k}={v[0]:>10,}" for k, v in result.items()) + f"  WIN={best}")

    print("=" * 150)
    print(f"TOTAL ORIGINAL: {original_total:,} B")
    print("\nTOTAL SIZE")
    for name in sorted(algorithms, key=lambda k: totals[k]):
        print(f"{name:<16} {totals[name]:>14,} B  ratio={totals[name] / original_total:.4f}  saving={(1-totals[name]/original_total)*100:.2f}%  wins={wins[name]}")

    print("\nTOTAL ENCODE TIME")
    for name in sorted(algorithms, key=lambda k: times[k]):
        print(f"{name:<16} {times[name]:>10.3f} s")


if __name__ == "__main__":
    main()
