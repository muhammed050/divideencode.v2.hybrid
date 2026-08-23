#!/usr/bin/env python3
"""CLI for the experimental Universal Divide architecture.

Usage:
    python deuniversal.py compress input output.duv
    python deuniversal.py decompress input.duv output
    python deuniversal.py compare input
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from divideencode.v2 import codec
from divideencode.v2 import universal


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compress")
    c.add_argument("input")
    c.add_argument("output")
    c.add_argument("--block-size", type=int, default=universal.DEFAULT_BLOCK_SIZE)

    d = sub.add_parser("decompress")
    d.add_argument("input")
    d.add_argument("output")

    b = sub.add_parser("compare")
    b.add_argument("input")
    b.add_argument("--block-size", type=int, default=universal.DEFAULT_BLOCK_SIZE)

    a = ap.parse_args()
    if a.cmd == "compress":
        data = open(a.input, "rb").read()
        t = time.perf_counter()
        blob = universal.compress(data, a.block_size)
        dt = time.perf_counter() - t
        open(a.output, "wb").write(blob)
        print("universal : %d -> %d bytes  ratio=%.4f  time=%.3fs" %
              (len(data), len(blob), len(blob) / len(data) if data else 1.0, dt))
        return 0
    if a.cmd == "decompress":
        blob = open(a.input, "rb").read()
        data = universal.decompress(blob)
        open(a.output, "wb").write(data)
        print("restored  : %d bytes" % len(data))
        return 0

    data = open(a.input, "rb").read()
    t = time.perf_counter()
    normal = codec.compress(data)
    normal_dt = time.perf_counter() - t
    t = time.perf_counter()
    uni = universal.compress(data, a.block_size)
    uni_dt = time.perf_counter() - t
    print("original  : %d" % len(data))
    print("DE2       : %d  ratio=%.4f  time=%.3fs" %
          (len(normal), len(normal) / len(data) if data else 1.0, normal_dt))
    print("UNIVERSAL : %d  ratio=%.4f  time=%.3fs" %
          (len(uni), len(uni) / len(data) if data else 1.0, uni_dt))
    print("winner    : %s" % ("UNIVERSAL" if len(uni) < len(normal) else "DE2"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
