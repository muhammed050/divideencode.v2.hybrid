"""Universal adaptive DE2 benchmark for the current v3 universal-binary branch.

The benchmark intentionally does not modify the DE2 core. It compares direct DE2
against reversible representations that already exist in this branch and chooses
only by the final verified container size.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress
from divideencode.universal import encode as du1_encode, decode as du1_decode

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"


@dataclass(frozen=True)
class Candidate:
    name: str
    data: bytes
    restore: object


def run_de2(data: bytes):
    t0 = time.perf_counter()
    blob = de2_compress(data, block_size=1 << 20, level="BALANCED")
    enc = time.perf_counter() - t0
    t0 = time.perf_counter()
    out = de2_decompress(blob)
    dec = time.perf_counter() - t0
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return blob, enc, dec


def candidates(src: bytes):
    # Identity is included only for a uniform candidate table; direct-DE2 is
    # reported separately so we can measure the overhead of each representation.
    yield Candidate("DU1-residual", du1_encode(src), du1_decode)


def main() -> None:
    files = sorted(p for p in CORPUS.iterdir() if p.is_file()) if CORPUS.exists() else []
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")

    print("CURRENT UNIVERSAL ADAPTIVE DE2")
    print("winner = smallest verified final DE2 blob; representation overhead included")

    for path in files:
        src = path.read_bytes()
        original = len(src)
        direct, enc, dec = run_de2(src)
        print("\n" + "=" * 100)
        print(f"{path.name}  original={original:,} B")
        print(f"  direct-DE2    final={len(direct):,} B ratio={len(direct)/original:.4f} enc={enc:.3f}s dec={dec:.3f}s")

        best = (len(direct), "direct-DE2", direct)
        for cand in candidates(src):
            packed = cand.data
            blob, cenc, cdec = run_de2(packed)
            restored = cand.restore(de2_decompress(blob), original)
            if restored != src:
                raise AssertionError(f"{cand.name} roundtrip mismatch")
            final_size = len(blob)
            print(
                f"  {cand.name:<14} final={final_size:>8,} B "
                f"ratio={final_size/original:.4f} representation={len(packed)-original:+,} B "
                f"enc={cenc:.3f}s dec={cdec:.3f}s ok"
            )
            if final_size < best[0]:
                best = (final_size, cand.name, blob)

        if best[0] < len(direct):
            print(f"  WINNER = {best[1]} -> {best[0]:,} B; gain_vs_direct=+{len(direct)-best[0]:,} B")
        else:
            print(f"  WINNER = direct-DE2 -> {len(direct):,} B; best_candidate_delta={best[0]-len(direct):+,} B")

        # If even direct DE2 expands the source, report that explicitly. This
        # keeps the benchmark honest: representation candidates never get credit
        # merely for beating DE2; they must beat the original when possible.
        if best[0] >= original:
            print(f"  NOTE = no candidate beats original; best_vs_original={best[0]-original:+,} B")


if __name__ == "__main__":
    main()
