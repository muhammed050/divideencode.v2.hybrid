"""Research analyzer for discovering why a UBIR transform helps DE2.

This is deliberately a research tool, not part of the compression hot path.
It compares DIRECT with selected reversible transforms and reports the
features that changed, with special attention to NIBBLE (the current
src_small.c winner).

Usage:
    python benchmarks/analyze_ubir2_transform.py corpus/src_small.c
    python benchmarks/analyze_ubir2_transform.py corpus/src_small.c --kinds NIBBLE,DELTA8,XOR8,BITPLANE
"""
from __future__ import annotations

import argparse
import math
from collections import Counter
from pathlib import Path

from divideencode.de2 import compress as de2_compress
from divideencode.de2.classifier import MODE_NAMES, classify
from divideencode.de2.features import scan_features
from divideencode.universal_ir import Kind, transform, inverse


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in Counter(data).values())


def zero_ratio(data: bytes) -> float:
    return data.count(0) / len(data) if data else 0.0


def run_ratio(data: bytes) -> float:
    if len(data) < 2:
        return 0.0
    return sum(a == b for a, b in zip(data, data[1:])) / (len(data) - 1)


def nibble_zero_ratios(data: bytes) -> tuple[float, float]:
    if not data:
        return 0.0, 0.0
    lo = sum((b & 0x0F) == 0 for b in data) / len(data)
    hi = sum((b >> 4) == 0 for b in data) / len(data)
    return lo, hi


def pair_repeat_ratio(data: bytes, width: int = 2) -> float:
    if len(data) < width * 2:
        return 0.0
    sample = data[: min(len(data), 256 * 1024)]
    grams = Counter(sample[i:i + width] for i in range(len(sample) - width + 1))
    repeated = sum(c for c in grams.values() if c > 1)
    return repeated / max(1, len(sample) - width + 1)


def prefix_suffix_repetition(data: bytes) -> tuple[float, float]:
    sample = data[: min(len(data), 256 * 1024)]
    if len(sample) < 16:
        return 0.0, 0.0
    chunk = 4
    prefixes = Counter(sample[i:i + chunk] for i in range(0, len(sample) - chunk + 1, chunk))
    suffixes = Counter(sample[i:i + chunk] for i in range(0, len(sample) - chunk + 1, chunk))
    p = sum(c for c in prefixes.values() if c > 1) / max(1, len(prefixes))
    s = sum(c for c in suffixes.values() if c > 1) / max(1, len(suffixes))
    return p, s


def describe(label: str, data: bytes, original_size: int | None = None) -> dict[str, object]:
    fs = scan_features(data)
    mode, hint = classify(fs)
    lo, hi = nibble_zero_ratios(data)
    pfx, sfx = prefix_suffix_repetition(data)
    packed = de2_compress(data, level="BALANCED")
    return {
        "label": label,
        "size": len(data),
        "de2": len(packed),
        "ratio": len(packed) / max(1, original_size or len(data)),
        "entropy": entropy(data),
        "unique": len(set(data)),
        "zero": zero_ratio(data),
        "runs": run_ratio(data),
        "pair2": pair_repeat_ratio(data, 2),
        "pair4": pair_repeat_ratio(data, 4),
        "nib_lo0": lo,
        "nib_hi0": hi,
        "prefix4": pfx,
        "suffix4": sfx,
        "mode": MODE_NAMES[mode],
        "hint": hint.decode("ascii", "replace") if hint else "-",
        "features": fs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--kinds",
        default="NIBBLE,DELTA8,XOR8,BITPLANE,TRANSPOSE4,TRANSPOSE8,STRIDE2,STRIDE4,STRIDE8",
        help="comma-separated UBIR kinds to compare",
    )
    args = parser.parse_args()

    src = args.path.read_bytes()
    base = describe("DIRECT", src)
    print(f"UBIR2 transform research: {args.path}")
    print("=" * 96)
    print(f"original={len(src):,} B")
    print(
        "DIRECT: DE2={de2:,} ratio={ratio:.4f} entropy={entropy:.3f} "
        "unique={unique} zero={zero:.4f} runs={runs:.4f} mode={mode}".format(**base)
    )
    print(
        f"        pair2={base['pair2']:.4f} pair4={base['pair4']:.4f} "
        f"nib_lo0={base['nib_lo0']:.4f} nib_hi0={base['nib_hi0']:.4f} "
        f"prefix4={base['prefix4']:.4f} suffix4={base['suffix4']:.4f}"
    )
    print("-" * 96)

    for name in [x.strip().upper() for x in args.kinds.split(",") if x.strip()]:
        try:
            kind = Kind[name]
        except KeyError:
            print(f"SKIP unknown kind: {name}")
            continue
        payload = transform(src, kind)
        restored = inverse(payload, kind, original_size=len(src))
        if restored != src:
            raise SystemExit(f"ROUNDTRIP FAILURE: {name}")
        row = describe(name, payload, original_size=len(src))
        gain = base["de2"] - row["de2"]
        pct = gain * 100.0 / max(1, base["de2"])
        print(
            f"{name:<10} size={row['size']:>9,} DE2={row['de2']:>8,} "
            f"gain={gain:>7,} ({pct:+.2f}%) mode={row['mode']:<10} "
            f"H={row['entropy']:.3f} zero={row['zero']:.4f} runs={row['runs']:.4f}"
        )
        print(
            f"           pair2={row['pair2']:.4f} pair4={row['pair4']:.4f} "
            f"nib_lo0={row['nib_lo0']:.4f} nib_hi0={row['nib_hi0']:.4f} "
            f"prefix4={row['prefix4']:.4f} suffix4={row['suffix4']:.4f}"
        )
        print(f"           features={row['features']!r}")


if __name__ == "__main__":
    main()
