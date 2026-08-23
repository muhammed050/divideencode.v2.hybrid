"""DE2-friendly structure preconditioner experiment.

Goal: make bytes easier for DE2 even when the intermediate representation is
larger. This is deliberately a benchmark-only experiment; the production core
is untouched.

Candidates:
- direct bytes
- byte transpose for several record widths
- stable byte-frequency rank remapping (with a reversible 256-byte table)
- byte-plane grouping

Every candidate is accepted only after exact round-trip verification and is
scored by the final DE2 blob size plus representation metadata.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"


@dataclass(frozen=True)
class Candidate:
    name: str
    data: bytes
    restore: object
    metadata: int


def de2(data: bytes):
    t0 = time.perf_counter()
    blob = de2_compress(data, block_size=1 << 20, level="BALANCED")
    enc = time.perf_counter() - t0
    t0 = time.perf_counter()
    out = de2_decompress(blob)
    dec = time.perf_counter() - t0
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return blob, enc, dec


def transpose(data: bytes, width: int):
    n = len(data)
    out = bytearray(n)
    pos = 0
    for col in range(width):
        i = col
        while i < n:
            out[pos] = data[i]
            pos += 1
            i += width
    return bytes(out)


def untranspose(data: bytes, width: int, original_len: int):
    out = bytearray(original_len)
    pos = 0
    for col in range(width):
        i = col
        while i < original_len:
            out[i] = data[pos]
            pos += 1
            i += width
    return bytes(out)


def frequency_rank(data: bytes):
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    # Most frequent symbols receive the smallest codes. Stable tie-breaking
    # keeps the transform deterministic and makes the table reproducible.
    order = sorted(range(256), key=lambda b: (-freq[b], b))
    enc = [0] * 256
    dec = [0] * 256
    for code, symbol in enumerate(order):
        enc[symbol] = code
        dec[code] = symbol
    return bytes(enc[b] for b in data), bytes(dec)


def inv_frequency(data: bytes, table: bytes):
    return bytes(table[b] for b in data)


def candidates(src: bytes):
    yield Candidate("transpose2", transpose(src, 2), lambda x, n: untranspose(x, 2, n), 1)
    yield Candidate("transpose4", transpose(src, 4), lambda x, n: untranspose(x, 4, n), 1)
    yield Candidate("transpose8", transpose(src, 8), lambda x, n: untranspose(x, 8, n), 1)
    yield Candidate("transpose16", transpose(src, 16), lambda x, n: untranspose(x, 16, n), 2)
    yield Candidate("transpose32", transpose(src, 32), lambda x, n: untranspose(x, 32, n), 2)
    ranked, table = frequency_rank(src)
    # 256-byte inverse table is part of the representation cost.
    yield Candidate("freq-rank", ranked, lambda x, n, t=table: inv_frequency(x, t), 256)


def main():
    files = sorted(p for p in CORPUS.iterdir() if p.is_file()) if CORPUS.exists() else []
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")

    print("DE2 PRECONDITIONER V1")
    print("Goal: structure first, compression second; intermediate size may grow")

    for path in files:
        src = path.read_bytes()
        original = len(src)
        direct, de, dd = de2(src)
        print("\n" + "=" * 100)
        print(f"{path.name} original={original:,} B")
        print(f"  direct-DE2 final={len(direct):,} B ratio={len(direct)/original:.4f} enc={de:.3f}s dec={dd:.3f}s")
        best = (len(direct), "direct-DE2")

        for cand in candidates(src):
            blob, enc, dec = de2(cand.data)
            restored = cand.restore(de2_decompress(blob), original)
            if restored != src:
                raise AssertionError(f"{cand.name} roundtrip mismatch")
            # Metadata is intentionally included in the score. The actual
            # production container can later encode this compactly; v1 uses a
            # conservative explicit byte count so experiments cannot cheat.
            final = len(blob) + cand.metadata
            print(
                f"  {cand.name:<12} repr={len(cand.data):>9,} B "
                f"DE2={len(blob):>9,} B meta={cand.metadata:>4} "
                f"FINAL={final:>9,} B ratio={final/original:.4f} "
                f"enc={enc:.3f}s dec={dec:.3f}s ok"
            )
            if final < best[0]:
                best = (final, cand.name)

        if best[1] == "direct-DE2":
            print(f"  WINNER direct-DE2; preconditioner_delta={best[0]-len(direct):+,} B")
        else:
            print(f"  WINNER {best[1]}; gain_vs_direct={len(direct)-best[0]:+,} B")
        if best[0] >= original:
            print(f"  NOTE no candidate beats original; best_vs_original={best[0]-original:+,} B")


if __name__ == "__main__":
    main()
