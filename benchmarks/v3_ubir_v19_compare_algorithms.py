"""V1.9 full-corpus algorithm comparison.

Final metric is compressed size after each algorithm. Every available
candidate is roundtrip-verified. JSON candidates also include V1.6 -> DE2.
Standard-library baselines are included so the experiment does not depend on
optional third-party packages.
"""
from __future__ import annotations

import bz2
import gzip
import lzma
import time
import zlib
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress
from divideencode.v3 import universal_binary_ir as ubir
from divideencode.v3 import ubir_v16 as v16

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"
FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def timed(name, data, enc, dec):
    try:
        t = time.perf_counter()
        packed = enc(data)
        et = time.perf_counter() - t
        t = time.perf_counter()
        out = dec(packed)
        dt = time.perf_counter() - t
        if out != data:
            raise AssertionError("roundtrip mismatch")
        return name, len(packed), et, dt, "ok"
    except Exception as exc:
        return name, None, 0.0, 0.0, f"skip: {type(exc).__name__}: {exc}"


def main():
    print("V1.9 ALL-ALGORITHM COMPARISON")
    print("metric = final compressed bytes; all successful candidates roundtrip-verified")
    print("baselines = DE2, zlib/deflate, gzip, bz2, lzma/xz, UBIR direct; JSON also V1.6->DE2")

    for path in FILES:
        data = path.read_bytes()
        original = len(data)
        rows = [
            timed("DE2", data,
                  lambda x: de2_compress(x, block_size=1 << 20, level="BALANCED"),
                  de2_decompress),
            timed("deflate", data, lambda x: zlib.compress(x, 9), zlib.decompress),
            timed("gzip", data, lambda x: gzip.compress(x, compresslevel=9), gzip.decompress),
            timed("bz2", data, lambda x: bz2.compress(x, compresslevel=9), bz2.decompress),
            timed("xz", data, lambda x: lzma.compress(x, preset=9), lzma.decompress),
        ]

        kind = "json" if path.suffix.lower() in {".json", ".jsonl"} else None
        if kind:
            rows.append(timed("UBIR-direct", data,
                              lambda x: ubir.encode(x, kind), ubir.decode))
            try:
                t = time.perf_counter(); ir = v16.encode(data, kind); ir_et = time.perf_counter() - t
                if v16.decode(ir) != data:
                    raise AssertionError("V1.6 roundtrip mismatch")
                rows.append(timed(f"V1.6->DE2 (IR {len(ir):,} B)", ir,
                                  lambda x: de2_compress(x, block_size=1 << 20, level="BALANCED"),
                                  de2_decompress))
                rows[-1] = (*rows[-1][:4], rows[-1][4] + f"; V1.6_encode={ir_et:.2f}s")
            except Exception as exc:
                rows.append(("V1.6->DE2", None, 0.0, 0.0,
                             f"skip: {type(exc).__name__}: {exc}"))

        good = [r for r in rows if r[1] is not None]
        best = min(good, key=lambda r: r[1]) if good else None
        print("\n" + "=" * 96)
        print(f"{path.name}  original={original:,} B")
        for name, size, et, dt, status in rows:
            if size is None:
                print(f"  {name:24s} {status}")
            else:
                print(f"  {name:24s} {size:10,} B ratio={size/original:7.4f} "
                      f"saved={original-size:+,} enc={et:.2f}s dec={dt:.2f}s {status}")
        if best:
            print(f"  WINNER: {best[0]} -> {best[1]:,} B ({best[1]/original:.4f}x)")


if __name__ == "__main__":
    main()
