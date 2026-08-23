#!/usr/bin/env python3
"""dehybrid -- CLI for divideencode.v2.hybrid, the adaptive strong+fast codec.

Usage:
    python3 dehybrid.py compress   <input> <output.deh>
    python3 dehybrid.py decompress <input.deh> <output>
    python3 dehybrid.py bench      <file-or-directory> [file-or-directory ...]

`compress`/`decompress` verify SHA-256 round-trip integrity is possible
(decompress always re-checks CRC-32 internally and raises on corruption);
`bench` reports size, ratio, and timing without external dependencies,
compared against stdlib zlib and lzma for context.
"""
import argparse
import hashlib
import os
import sys
import time
import zlib
import lzma

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from divideencode.v2.hybrid import compress, decompress  # noqa: E402
from divideencode.errors import DivideEncodeError  # noqa: E402


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def cmd_compress(args):
    if not os.path.isfile(args.input):
        print("error: input file not found: %s" % args.input, file=sys.stderr)
        return 2
    with open(args.input, "rb") as fh:
        data = fh.read()
    t0 = time.perf_counter()
    blob, method = compress(data)
    dt = time.perf_counter() - t0
    with open(args.output, "wb") as fh:
        fh.write(blob)
    orig, comp = len(data), len(blob)
    ratio = comp / orig if orig else 1.0
    print("original:     %d bytes" % orig)
    print("compressed:   %d bytes" % comp)
    print("method:       %s" % method)
    print("ratio:        %.4f (%.2f%% saved)" % (ratio, 100 * (1 - ratio)))
    print("time:         %.3f s (%.2f MB/s)" %
          (dt, (orig / 1048576.0) / dt if dt > 0 else float("inf")))
    if args.sha:
        print("sha256(in):   %s" % _sha256(data))
    return 0


def cmd_decompress(args):
    if not os.path.isfile(args.input):
        print("error: input file not found: %s" % args.input, file=sys.stderr)
        return 2
    with open(args.input, "rb") as fh:
        blob = fh.read()
    t0 = time.perf_counter()
    try:
        data = decompress(blob)
    except DivideEncodeError as exc:
        print("error: corrupted or invalid container: %s" % exc, file=sys.stderr)
        return 1
    dt = time.perf_counter() - t0
    with open(args.output, "wb") as fh:
        fh.write(data)
    print("restored:     %d bytes" % len(data))
    print("time:         %.3f s" % dt)
    if args.sha:
        print("sha256(out):  %s" % _sha256(data))
    return 0


def _iter_files(paths):
    for p in paths:
        if os.path.isfile(p):
            yield p
        elif os.path.isdir(p):
            for root, _, files in os.walk(p):
                for fn in files:
                    yield os.path.join(root, fn)


def cmd_bench(args):
    header = "%-30s %10s %10s %10s %8s %8s %8s  %s" % (
        "file", "orig", "zlib9", "lzma9e", "hybrid", "ratio", "c(s)", "method")
    print(header)
    print("-" * len(header))
    total_orig = total_hyb = 0
    all_ok = True
    for path in _iter_files(args.paths):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if not data and not args.include_empty:
            continue
        t0 = time.perf_counter()
        blob, method = compress(data)
        dt = time.perf_counter() - t0
        restored = decompress(blob)
        ok = restored == data
        all_ok = all_ok and ok
        z = zlib.compress(data, 9) if data else b""
        try:
            xz = lzma.compress(data, preset=9 | lzma.PRESET_EXTREME) if data else b""
        except Exception:
            xz = b""
        total_orig += len(data)
        total_hyb += len(blob)
        ratio = len(blob) / len(data) if data else 1.0
        print("%-30s %10d %10d %10d %8d %8.4f %8.3f  %s%s" % (
            os.path.basename(path)[:30], len(data), len(z), len(xz),
            len(blob), ratio, dt, method, "" if ok else "  LOSSLESS-FAIL"))
    print("-" * len(header))
    if total_orig:
        print("TOTAL: %d -> %d bytes (ratio %.4f)  all lossless: %s" %
              (total_orig, total_hyb, total_hyb / total_orig, all_ok))
    return 0 if all_ok else 1


def main():
    ap = argparse.ArgumentParser(prog="dehybrid", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compress", help="compress a file")
    c.add_argument("input")
    c.add_argument("output")
    c.add_argument("--sha", action="store_true", help="print SHA-256 of input")
    c.set_defaults(func=cmd_compress)

    d = sub.add_parser("decompress", help="decompress a file")
    d.add_argument("input")
    d.add_argument("output")
    d.add_argument("--sha", action="store_true", help="print SHA-256 of output")
    d.set_defaults(func=cmd_decompress)

    b = sub.add_parser("bench", help="benchmark files or directories")
    b.add_argument("paths", nargs="+")
    b.add_argument("--include-empty", action="store_true")
    b.set_defaults(func=cmd_bench)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
