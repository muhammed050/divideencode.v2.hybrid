"""Compare production DE2 tokenizer with the experimental bounded parser.

This benchmark is intentionally not wired into production encoding. It reports
parser statistics and elapsed time so a bounded parser can earn promotion by
measurement rather than intuition.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from divideencode.v2.lz import tokenize, token_stats
from divideencode.v2.lz_opt import tokenize_bounded


def cases():
    rng = random.Random(0xDE2)
    return [
        ("text", b"the quick brown fox jumps over the lazy dog " * 2000),
        ("json", b'{"id":123,"name":"user","active":true,"items":[1,2,3]}\n' * 4000),
        ("logs", b"2026-08-23 INFO api status=200 latency=42ms\n" * 5000),
        ("periodic", b"0123456789abcdef" * 10000),
        ("mixed", (b"header\x00payload:" + bytes(range(64))) * 3000),
        ("random", bytes(rng.getrandbits(8) for _ in range(100000))),
    ]


def measure(fn, data):
    t0 = time.perf_counter()
    tokens = fn(data)
    ms = (time.perf_counter() - t0) * 1000
    return ms, token_stats(tokens)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookaheads", default="8,16,32,64")
    args = ap.parse_args()
    lookaheads = [int(x) for x in args.lookaheads.split(",") if x.strip()]

    print("case      baseline_ms baseline_tokens  " + "  ".join(
        "L%-4d_ms L%-4d_tok" % (x, x) for x in lookaheads))
    print("-" * (35 + len(lookaheads) * 20))
    for name, data in cases():
        bms, bst = measure(tokenize, data)
        row = "% -8s %10.2f %15d" % (name, bms, bst["tokens"])
        for look in lookaheads:
            oms, ost = measure(lambda d, l=look: tokenize_bounded(d, lookahead=l), data)
            row += " %7.2f %7d" % (oms, ost["tokens"])
        print(row)


if __name__ == "__main__":
    main()
