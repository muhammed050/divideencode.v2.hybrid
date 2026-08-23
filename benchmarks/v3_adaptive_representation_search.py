"""Reversible representation search on top of the current DE2 core.

This is an experiment only: it does not change the codec.  It tests generic
byte/bit transpositions that can expose structure to DE2, then measures the
FULL final DE2 blob.  A candidate only counts if its inverse is exact.
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


def transpose_bytes(src: bytes, width: int) -> bytes:
    n = len(src)
    usable = n - (n % width)
    out = bytearray(usable + (n - usable))
    k = 0
    for lane in range(width):
        for i in range(lane, usable, width):
            out[k] = src[i]
            k += 1
    out[usable:] = src[usable:]
    return bytes(out)


def untranspose_bytes(src: bytes, width: int, original_size: int) -> bytes:
    usable = original_size - (original_size % width)
    tail = original_size - usable
    out = bytearray(original_size)
    per = usable // width
    k = 0
    for lane in range(width):
        for i in range(lane, usable, width):
            out[i] = src[k]
            k += 1
    if tail:
        out[usable:] = src[usable:usable + tail]
    return bytes(out)


def bitplane(src: bytes) -> bytes:
    # Eight MSB->LSB bit planes, each packed into bytes.
    out = bytearray((len(src) + 7) // 8 * 8)
    for bit in range(8):
        base = bit * ((len(src) + 7) // 8)
        for i, value in enumerate(src):
            out[base + (i >> 3)] |= ((value >> (7 - bit)) & 1) << (7 - (i & 7))
    return bytes(out[: ((len(src) + 7) // 8) * 8])


def unbitplane(src: bytes, original_size: int) -> bytes:
    block = (original_size + 7) // 8
    out = bytearray(original_size)
    for i in range(original_size):
        value = 0
        for bit in range(8):
            value |= ((src[bit * block + (i >> 3)] >> (7 - (i & 7))) & 1) << (7 - bit)
        out[i] = value
    return bytes(out)


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


def make_candidates(src: bytes):
    # Widths > 4 are deliberately included: the current DE2 numeric transform
    # only searches 1/2/4-byte words, so this tests genuinely new structure.
    for width in (8, 16, 32, 64):
        if len(src) >= width:
            transformed = transpose_bytes(src, width)
            yield Candidate(
                f"transpose{width}",
                transformed,
                lambda x, w=width, n=len(src): untranspose_bytes(x, w, n),
            )
    if src:
        transformed = bitplane(src)
        yield Candidate("bitplanes", transformed, lambda x, n=len(src): unbitplane(x, n))


def main():
    files = sorted(p for p in CORPUS.iterdir() if p.is_file()) if CORPUS.exists() else []
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")

    print("DE2 ADAPTIVE REPRESENTATION SEARCH")
    print("Every candidate is lossless and judged only by final DE2 bytes.")

    for path in files:
        src = path.read_bytes()
        original = len(src)
        direct, enc, dec = run_de2(src)
        best_size = len(direct)
        best_name = "direct-DE2"
        print("\n" + "=" * 100)
        print(f"{path.name} original={original:,} B")
        print(f"  direct-DE2 final={len(direct):,} B ratio={len(direct)/original:.4f} enc={enc:.3f}s dec={dec:.3f}s")

        for cand in make_candidates(src):
            blob, cenc, cdec = run_de2(cand.data)
            restored = cand.restore(de2_decompress(blob))
            if restored != src:
                raise AssertionError(f"{cand.name} roundtrip mismatch")
            delta_vs_direct = len(blob) - len(direct)
            print(f"  {cand.name:<14} final={len(blob):>9,} B ratio={len(blob)/original:.4f} rep_delta={len(cand.data)-original:+,} B vs_direct={delta_vs_direct:+,} B enc={cenc:.3f}s dec={cdec:.3f}s ok")
            if len(blob) < best_size:
                best_size = len(blob)
                best_name = cand.name

        if best_name == "direct-DE2":
            print(f"  WINNER = direct-DE2 ({best_size:,} B)")
        else:
            print(f"  WINNER = {best_name} ({best_size:,} B), gain_vs_direct={len(direct)-best_size:,} B")
        print(f"  vs_original={best_size-original:+,} B")


if __name__ == "__main__":
    main()
