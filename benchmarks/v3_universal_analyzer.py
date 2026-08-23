"""V2 Universal Analyzer benchmark.

Compares direct DE2 against analyzer representations. The analyzer is a
front-end: it detects file structure, creates reversible candidates, and
selects the smallest verified DE2 result. Traditional compressors are kept
out of this benchmark so the experiment isolates representation quality.
"""
from __future__ import annotations

import time
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress
from divideencode.v3 import universal_analyzer as ua

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"
FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def timed_de2(data: bytes):
    t = time.perf_counter()
    packed = de2_compress(data, block_size=1 << 20, level="BALANCED")
    et = time.perf_counter() - t
    t = time.perf_counter()
    out = de2_decompress(packed)
    dt = time.perf_counter() - t
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return packed, et, dt


def main():
    print("V2 UNIVERSAL ANALYZER -> DE2")
    print("goal = make file structure readable to the DE2 front-end")
    print("all candidates are reversible and roundtrip-verified")

    for path in FILES:
        data = path.read_bytes()
        original = len(data)
        print("\n" + "=" * 100)
        print(f"{path.name}  original={original:,} B  detected={ua.detect(data, path.suffix)}")

        direct, direct_et, direct_dt = timed_de2(data)
        print(f"  direct-DE2       final={len(direct):9,d} B ratio={len(direct)/original:.4f} enc={direct_et:.2f}s dec={direct_dt:.2f}s")

        results = [("direct-DE2", direct, direct_et, direct_dt)]
        for cand in ua.candidates(data, path.suffix):
            packed, et, dt = timed_de2(cand.blob)
            results.append((cand.kind + "->DE2", packed, et, dt))
            print(f"  {cand.kind + '->DE2':16} final={len(packed):9,d} B ratio={len(packed)/original:.4f} IR={len(cand.blob):,} B transform_delta={cand.transform_bytes:+,} B enc={et:.2f}s dec={dt:.2f}s")

        winner = min(results, key=lambda x: len(x[1]))
        print(f"  WINNER           {winner[0]} -> {len(winner[1]):,} B ({len(winner[1])/original:.4f}x)")


if __name__ == "__main__":
    main()
