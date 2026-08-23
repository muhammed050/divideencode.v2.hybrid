"""Run the experimental bounded parser with live terminal diagnostics."""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from divideencode.v2.lz import apply_tokens
from divideencode.v2.lz_opt import tokenize_bounded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="file to parse")
    ap.add_argument("--lookahead", type=int, default=32)
    ap.add_argument("--chain", type=int, default=32)
    ap.add_argument("--window", type=int, default=None)
    ap.add_argument("--every", type=int, default=4096)
    args = ap.parse_args()

    if args.file:
        with open(args.file, "rb") as f:
            data = f.read()
        name = args.file
    else:
        data = (b"The quick brown fox jumps over the lazy dog. " * 10000)
        name = "synthetic-text"

    print("=" * 72)
    print("DE2 BOUNDED PARSER — LIVE MODE")
    print(f"file      : {name}")
    print(f"input     : {len(data):,} bytes")
    print(f"lookahead : {args.lookahead}")
    print(f"chain     : {args.chain}")
    print("=" * 72)

    kwargs = dict(lookahead=args.lookahead, max_chain=args.chain,
                  progress=True, progress_every=args.every)
    if args.window is not None:
        kwargs["window_size"] = args.window

    started = time.perf_counter()
    tokens = tokenize_bounded(data, **kwargs)
    elapsed = time.perf_counter() - started

    print(f"roundtrip : {apply_tokens(tokens) == data}")
    print(f"tokens    : {len(tokens):,}")
    print(f"elapsed   : {elapsed:.3f}s")
    print("=" * 72)


if __name__ == "__main__":
    main()
