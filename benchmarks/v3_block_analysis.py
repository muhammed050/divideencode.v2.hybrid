"""Explain where larger DE2 blocks save bytes.

This is a measurement-only benchmark. It compares 512 KiB, 1 MiB and 4 MiB
per file, reports block counts and per-file deltas, and highlights whether the
gain is concentrated in multi-block inputs.
"""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from divideencode import de2

CORPUS = Path(__file__).parent / "corpus"
BLOCKS = (524288, 1048576, 4194304)


def corpus():
    return [(p.name, p.read_bytes()) for p in sorted(CORPUS.iterdir()) if p.is_file()]


def fmt(n):
    return f"{n:,}"


def run(rows):
    print("=" * 112)
    print("V3 BLOCK-SIZE ANALYSIS — WHERE DOES 512 KiB → 1 MiB ACTUALLY WIN?")
    print("BALANCED matcher; same input and format, only block_size changes")
    print("=" * 112)

    results = {}
    totals = {bs: 0 for bs in BLOCKS}
    times = {bs: 0.0 for bs in BLOCKS}

    for name, data in rows:
        results[name] = {}
        for bs in BLOCKS:
            t0 = time.perf_counter()
            blob = de2.compress(data, block_size=bs, level="BALANCED")
            dt = time.perf_counter() - t0
            assert de2.decompress(blob) == data, name
            blocks = max(1, (len(data) + bs - 1) // bs)
            results[name][bs] = (len(blob), blocks)
            totals[bs] += len(blob)
            times[bs] += dt

    print(f"{'file':24s} {'orig':>10s} {'512KiB':>11s} {'1MiB':>11s} {'4MiB':>11s} {'512→1MiB':>11s} {'1→4MiB':>11s}")
    print("-" * 112)
    for name, data in rows:
        a = results[name][524288][0]
        b = results[name][1048576][0]
        c = results[name][4194304][0]
        print(f"{name:24s} {fmt(len(data)):>10s} {fmt(a):>11s} {fmt(b):>11s} {fmt(c):>11s} {b-a:>+11,d} {c-b:>+11,d}")

    print("-" * 112)
    print(f"{'TOTAL':24s} {fmt(sum(len(d) for _, d in rows)):>10s} {fmt(totals[524288]):>11s} {fmt(totals[1048576]):>11s} {fmt(totals[4194304]):>11s} {totals[1048576]-totals[524288]:>+11,d} {totals[4194304]-totals[1048576]:>+11,d}")
    print()
    for bs in BLOCKS:
        print(f"block={bs:7d} total={fmt(totals[bs]):>12s} B  enc={times[bs]:7.2f}s")

    print("\n=== MULTI-BLOCK CONTRIBUTION ===")
    for threshold in (524288, 1048576):
        multi = [(name, len(data), results[name][threshold][1]) for name, data in rows if results[name][threshold][1] > 1]
        print(f"block={threshold:7d}: {len(multi)} files use >1 block")
        for name, size, count in multi:
            print(f"  {name:24s} {fmt(size):>10s} B  blocks={count}")

    print("\n=== INTERPRETATION ===")
    d1 = totals[1048576] - totals[524288]
    d2 = totals[4194304] - totals[1048576]
    print(f"512 KiB → 1 MiB: {d1:+,} B")
    print(f"1 MiB → 4 MiB:   {d2:+,} B")
    if d1 < 0 and d2 > d1:
        print("The first jump is materially larger than the second; this points to")
        print("per-block representation/matcher context loss rather than fixed headers alone.")
    print("This script does not modify production compression settings.")


if __name__ == "__main__":
    run(corpus())
