"""V1.8 all-files comparison: adaptive DE2 vs traditional compressors.

V1.8 is treated as a routing strategy, not a new compressor:
  - every file gets direct DE2(data)
  - JSON/JSONL additionally gets V1.6 representation -> DE2
  - V1.8 chooses the smallest verified DE2 result

Traditional baselines are zlib/deflate, gzip, bz2 and lzma/xz.
Final metric is compressed byte size. Every successful candidate is
roundtrip-verified against the original input.
"""
from __future__ import annotations

import bz2
import gzip
import lzma
import time
import zlib
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress
from divideencode.v3 import ubir_v16 as v16

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"
FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def timed_roundtrip(name, encode, decode, data: bytes):
    t = time.perf_counter()
    packed = encode(data)
    et = time.perf_counter() - t
    t = time.perf_counter()
    out = decode(packed)
    dt = time.perf_counter() - t
    if out != data:
        raise AssertionError(f"{name} roundtrip mismatch")
    return len(packed), et, dt


def de2(data: bytes):
    return timed_roundtrip(
        "DE2",
        lambda b: de2_compress(b, block_size=1 << 20, level="BALANCED"),
        de2_decompress,
        data,
    )


def v18_candidate(data: bytes, path: Path):
    # Direct DE2 is always a candidate.
    direct = de2(data)
    candidates = [("direct-DE2", direct)]

    if path.suffix.lower() in {".json", ".jsonl"}:
        t = time.perf_counter()
        ir = v16.encode(data, "json")
        v16_et = time.perf_counter() - t
        if v16.decode(ir) != data:
            raise AssertionError("V1.6 roundtrip mismatch")
        packed = de2(ir)
        candidates.append(("V1.6->DE2", packed))
        return min(candidates, key=lambda x: x[1][0]), direct, len(ir), v16_et

    return min(candidates, key=lambda x: x[1][0]), direct, None, None


def traditional(data: bytes):
    return {
        "deflate": timed_roundtrip("deflate", lambda b: zlib.compress(b, 9), zlib.decompress, data),
        "gzip": timed_roundtrip("gzip", lambda b: gzip.compress(b, compresslevel=9), gzip.decompress, data),
        "bz2": timed_roundtrip("bz2", lambda b: bz2.compress(b, compresslevel=9), bz2.decompress, data),
        "xz": timed_roundtrip("xz", lambda b: lzma.compress(b, format=lzma.FORMAT_XZ, preset=9), lambda b: lzma.decompress(b, format=lzma.FORMAT_XZ), data),
    }


def fmt(result):
    size, et, dt = result
    return f"{size:10,d} B ratio={size / CURRENT_ORIGINAL:.4f} enc={et:.2f}s dec={dt:.2f}s"


def main():
    global CURRENT_ORIGINAL
    print("V1.8 ADAPTIVE DE2 vs ALL BASELINE ALGORITHMS")
    print("metric = final compressed bytes; all successful candidates roundtrip-verified")
    print("V1.8 = direct DE2 + JSON V1.6->DE2 routing; IR size is diagnostic only")

    for path in FILES:
        data = path.read_bytes()
        CURRENT_ORIGINAL = len(data)
        print("\n" + "=" * 96)
        print(f"{path.name}  original={CURRENT_ORIGINAL:,} B")

        winner, direct, ir_size, v16_et = v18_candidate(data, path)
        print(f"  DE2-direct   {fmt(direct)}")
        if ir_size is not None:
            v16_result = de2(v16.encode(data, "json"))
            print(f"  V1.6->DE2     {fmt(v16_result)} IR={ir_size:,} B V1.6_enc={v16_et:.2f}s")
            print(f"  V1.8 winner   {winner[0]} -> {winner[1][0]:,} B")
        else:
            print(f"  V1.8 winner   {winner[0]} -> {winner[1][0]:,} B")

        for name, result in traditional(data).items():
            print(f"  {name:<12} {fmt(result)}")

        all_results = {"V1.8": winner[1], **traditional(data)}
        best_name, best_result = min(all_results.items(), key=lambda kv: kv[1][0])
        print(f"  OVERALL WINNER = {best_name} -> {best_result[0]:,} B ({best_result[0] / CURRENT_ORIGINAL:.4f}x)")


if __name__ == "__main__":
    main()
