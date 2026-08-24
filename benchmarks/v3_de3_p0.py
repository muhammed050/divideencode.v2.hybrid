from __future__ import annotations

import bz2
import csv
import gzip
import lzma
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from divideencode.de3_p0 import compress as de3_compress, decompress as de3_decompress
from divideencode.de2 import compress as de2_compress, decompress as de2_decompress

CORPUS = ROOT / "benchmarks" / "corpus"


def timed(fn, data, runs=1):
    best = float("inf")
    result = None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = fn(data)
        best = min(best, time.perf_counter() - t0)
    return result, best


def row(name, data, codec, enc, dec):
    blob, et = timed(enc, data)
    restored, dt = timed(dec, blob)
    ok = restored == data
    ratio = len(blob) / len(data) if data else 0.0
    return [name, codec, len(data), len(blob), ratio, (1-ratio)*100, et, dt, ok]


def main():
    rows = []
    files = sorted(p for p in CORPUS.iterdir() if p.is_file())
    codecs = [
        ("DE3-P0", de3_compress, de3_decompress),
        ("DE2", de2_compress, de2_decompress),
        ("deflate", lambda d: zlib.compress(d, 9), zlib.decompress),
        ("gzip", lambda d: gzip.compress(d, compresslevel=9), gzip.decompress),
        ("bz2", lambda d: bz2.compress(d, compresslevel=9), bz2.decompress),
        ("xz", lambda d: lzma.compress(d, preset=9), lzma.decompress),
    ]
    for path in files:
        data = path.read_bytes()
        print("\n" + "=" * 96)
        print(f"{path.name}  original={len(data):,} B")
        best = None
        for name, enc, dec in codecs:
            r = row(path.name, data, name, enc, dec)
            rows.append(r)
            _, codec, original, size, ratio, saved, et, dt, ok = r
            print(f"  {codec:<10} {size:12,} B ratio={ratio:7.4f} saved={saved:+7.2f}% enc={et:.3f}s dec={dt:.3f}s {'ok' if ok else 'FAIL'}")
            if ok and (best is None or size < best[3]):
                best = r
        if best:
            print(f"  WINNER: {best[1]} -> {best[3]:,} B ({best[4]:.4f}x)")
    out = ROOT / "benchmarks" / "results" / "de3-p0.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "codec", "original", "compressed", "ratio", "saved_pct", "enc_s", "dec_s", "ok"])
        w.writerows(rows)
    print(f"\nCSV: {out}")


if __name__ == "__main__":
    main()
