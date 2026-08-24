from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from divideencode.v2.codec import compress as de2_compress
from divideencode.v2.numberized import compress as numberized_compress
from divideencode.v2.numberized import decompress as numberized_decompress
from divideencode.v2.numberized import pack_number


def timed(fn, runs):
    best = float("inf")
    result = None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = fn()
        best = min(best, time.perf_counter() - t0)
    return result, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    files = sorted(p for p in Path(args.root).rglob("*") if p.is_file())
    for i, path in enumerate(files, 1):
        raw = path.read_bytes()
        direct, dt = timed(lambda: de2_compress(raw), args.runs)
        packed = pack_number(raw)
        numberized, nt = timed(lambda: numberized_compress(raw), args.runs)
        assert numberized_decompress(numberized) == raw
        print(
            f"[{i}/{len(files)}] {path} orig={len(raw):,} "
            f"number={len(packed):,} direct={len(direct):,} "
            f"numberized={len(numberized):,} "
            f"direct_ratio={len(direct)/len(raw):.6f} "
            f"number_ratio={len(numberized)/len(raw):.6f} "
            f"direct_t={dt:.4f}s numberized_t={nt:.4f}s"
        )


if __name__ == "__main__":
    main()
