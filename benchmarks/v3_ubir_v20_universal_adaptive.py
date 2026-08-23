"""V2.0 universal adaptive DE2 benchmark.

No filename/extension routing. Every file gets the same generic candidate set
and the winner is selected by final verified DE2 bytes.
"""
from __future__ import annotations

import time
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress
from divideencode.universal import candidates, _pack, _unpack, _inverse

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"
FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def run_de2(data: bytes):
    t = time.perf_counter()
    blob = de2_compress(data, block_size=1 << 20, level="BALANCED")
    enc = time.perf_counter() - t
    t = time.perf_counter()
    out = de2_decompress(blob)
    dec = time.perf_counter() - t
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return blob, enc, dec


def main() -> None:
    print("V2.0 UNIVERSAL ADAPTIVE DE2")
    print("same generic transforms for every file; winner = smallest final DE2")
    print("no extension-based routing; all successful candidates roundtrip-verified")

    for path in FILES:
        data = path.read_bytes()
        original = len(data)
        direct, de, dd = run_de2(data)
        print("\n" + "=" * 100)
        print(f"{path.name}  original={original:,} B")
        print(f"  direct-DE2   final={len(direct):,} B ratio={len(direct)/original:.4f} enc={de:.2f}s dec={dd:.2f}s")

        rows = []
        for cand in candidates(data):
            packed = _pack(cand.ident, original, cand.data)
            try:
                blob, enc, dec = run_de2(packed)
                decoded = de2_decompress(blob)
                ident, size, transformed = _unpack(decoded)
                restored = _inverse(ident, transformed)
                if size != original or restored != data:
                    raise AssertionError("universal roundtrip mismatch")
                rows.append((len(blob), cand, enc, dec))
                print(
                    f"  {cand.name:<14} final={len(blob):>8,} B "
                    f"ratio={len(blob)/original:.4f} IR={cand.transform_size:,} B "
                    f"transform={cand.transform_size-original:+,} B enc={enc:.2f}s dec={dec:.2f}s ok"
                )
            except Exception as exc:
                print(f"  {cand.name:<14} FAILED {exc}")

        if not rows:
            print("  WINNER = direct-DE2 (no valid universal candidate)")
            continue
        rows.sort(key=lambda x: x[0])
        best_size, best, _, _ = rows[0]
        if best_size < len(direct):
            gain = len(direct) - best_size
            winner = f"{best.name}"
            print(f"  WINNER = UNIVERSAL/{winner} -> {best_size:,} B ({best_size/original:.4f}x), gain_vs_direct=+{gain:,} B")
        else:
            print(f"  WINNER = direct-DE2 -> {len(direct):,} B ({len(direct)/original:.4f}x), universal_best_delta={best_size-len(direct):+,} B")


if __name__ == "__main__":
    main()
