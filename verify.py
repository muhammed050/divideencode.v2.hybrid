#!/usr/bin/env python3
"""Standalone lossless-verification script for this DivideEncode build.

Runs divideencode.v2 (compress -> decompress) on every file in samples/,
checks byte-for-byte equality and SHA-256 match against the original,
and prints size/ratio/timing per file plus a corpus total.

Usage:
    python3 verify.py
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from divideencode.v2 import compress, decompress  # noqa: E402


def main():
    samples_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
    if not os.path.isdir(samples_dir):
        print("samples/ directory not found next to this script.", file=sys.stderr)
        return 1

    total_orig = 0
    total_comp = 0
    all_ok = True

    print(f"{'file':22s} {'orig':>9s} {'comp':>9s} {'ratio':>8s} "
          f"{'c(s)':>7s} {'d(s)':>7s}  lossless")
    print("-" * 78)

    for fn in sorted(os.listdir(samples_dir)):
        path = os.path.join(samples_dir, fn)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()

        t0 = time.perf_counter()
        blob = compress(data)
        t1 = time.perf_counter()
        restored = decompress(blob)
        t2 = time.perf_counter()

        ok = (restored == data and
              hashlib.sha256(restored).hexdigest() == hashlib.sha256(data).hexdigest())
        all_ok = all_ok and ok

        total_orig += len(data)
        total_comp += len(blob)
        ratio = len(blob) / len(data) if data else 1.0

        print(f"{fn:22s} {len(data):9d} {len(blob):9d} {ratio:8.4f} "
              f"{t1 - t0:7.3f} {t2 - t1:7.3f}  {'OK' if ok else 'FAIL !!!'}")

    print("-" * 78)
    overall_ratio = (total_comp / total_orig) if total_orig else 1.0
    print(f"TOTAL: {total_orig} -> {total_comp} bytes  (ratio {overall_ratio:.4f})")
    print(f"ALL LOSSLESS: {all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
