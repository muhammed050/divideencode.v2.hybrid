from __future__ import annotations

import argparse
from pathlib import Path
import time

from divideencode.v2.codec import compress as de2_compress
from divideencode.v2.external_symbols import compress, decompress, to_decimal_digits


def timed(fn, runs):
    result = None
    t0 = time.perf_counter()
    for _ in range(runs):
        result = fn()
    return result, (time.perf_counter() - t0) / runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    files = [p for p in Path(args.root).rglob("*") if p.is_file()]
    print(f"External-symbol DE2 test: {len(files)} files | runs={args.runs}")
    for p in files:
        raw = p.read_bytes()
        direct, dt = timed(lambda: de2_compress(raw), args.runs)
        ext, et = timed(lambda: compress(raw), args.runs)
        assert decompress(ext) == raw
        digits = to_decimal_digits(raw)
        print(f"{p.name:24} orig={len(raw):9,} direct={len(direct):9,} ext={len(ext):9,} "
              f"ratio={len(ext)/len(raw):.4f} direct_t={dt:.4f}s ext_t={et:.4f}s "
              f"digit_stream={len(digits):,}")


if __name__ == "__main__":
    main()
