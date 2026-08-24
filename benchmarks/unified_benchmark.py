#!/usr/bin/env python3
"""Unified lossless compression benchmark.

Compares DE1, DE2, Hybrid, zlib, gzip, Brotli, Zstandard and XZ/LZMA
on exactly the same input bytes. Produces a per-file CSV and a final
aggregate Markdown table.

Examples:
    python benchmarks/unified_benchmark.py samples/ --out benchmarks/results/unified
    python benchmarks/unified_benchmark.py samples/ --runs 3
    python benchmarks/unified_benchmark.py samples/ --algorithms DE2 zstd brotli

The benchmark never compares compressed streams by their internal format;
it compares actual container bytes produced by each encoder. Every result
is round-trip verified before it is accepted.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib
import lzma
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class Codec:
    name: str
    compress: Callable[[bytes], bytes]
    decompress: Callable[[bytes], bytes]
    available: bool = True
    note: str = ""


def _de1() -> Codec:
    m = importlib.import_module("divideencode")
    return Codec("DE1", m.compress, m.decompress)


def _de2() -> Codec:
    m = importlib.import_module("divideencode.v2")
    return Codec("DE2", m.compress, m.decompress)


def _hybrid() -> Codec:
    m = importlib.import_module("divideencode.v2.hybrid")
    # Hybrid's compress returns (blob, method), unlike the other codecs.
    return Codec("Hybrid", lambda d: m.compress(d)[0], m.decompress)


def _zlib() -> Codec:
    return Codec("zlib-9", lambda d: zlib.compress(d, 9), zlib.decompress)


def _gzip() -> Codec:
    return Codec("gzip-9", lambda d: gzip.compress(d, compresslevel=9, mtime=0), gzip.decompress)


def _lzma() -> Codec:
    return Codec(
        "xz-9e",
        lambda d: lzma.compress(d, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME),
        lzma.decompress,
    )


def _brotli() -> Codec:
    m = importlib.import_module("brotli")
    return Codec("brotli-11", lambda d: m.compress(d, quality=11), m.decompress)


def _zstd() -> Codec:
    m = importlib.import_module("zstandard")
    cctx = m.ZstdCompressor(level=19, write_checksum=True)
    dctx = m.ZstdDecompressor()
    return Codec("zstd-19", cctx.compress, dctx.decompress)


FACTORIES = {
    "DE1": _de1,
    "DE2": _de2,
    "Hybrid": _hybrid,
    "zlib": _zlib,
    "gzip": _gzip,
    "brotli": _brotli,
    "zstd": _zstd,
    "xz": _lzma,
}
DEFAULT_ORDER = ["DE1", "DE2", "Hybrid", "zlib", "gzip", "brotli", "zstd", "xz"]


def load_codecs(names: list[str]) -> tuple[list[Codec], list[str]]:
    codecs: list[Codec] = []
    skipped: list[str] = []
    for name in names:
        try:
            codecs.append(FACTORIES[name]())
        except (ImportError, ModuleNotFoundError) as exc:
            skipped.append(f"{name}: unavailable ({exc})")
        except Exception as exc:
            skipped.append(f"{name}: failed to initialize ({type(exc).__name__}: {exc})")
    return codecs, skipped


def iter_files(paths: list[str], include_empty: bool) -> Iterable[Path]:
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            candidates = [p]
        elif p.is_dir():
            candidates = sorted(x for x in p.rglob("*") if x.is_file())
        else:
            print(f"WARN: path not found: {p}", file=sys.stderr)
            continue
        for f in candidates:
            f = f.resolve()
            if f in seen:
                continue
            seen.add(f)
            try:
                if include_empty or f.stat().st_size:
                    yield f
            except OSError:
                continue


def timed(fn: Callable[[bytes], bytes], data: bytes, runs: int) -> tuple[bytes, float, float]:
    enc_times: list[float] = []
    blob = b""
    for _ in range(runs):
        t0 = time.perf_counter()
        blob = fn(data)
        enc_times.append(time.perf_counter() - t0)
    enc = statistics.median(enc_times)

    dec_times: list[float] = []
    restored = b""
    for _ in range(runs):
        t0 = time.perf_counter()
        restored = current_decompress(blob)
        dec_times.append(time.perf_counter() - t0)
    dec = statistics.median(dec_times)
    if restored != data:
        raise ValueError("round-trip mismatch")
    return blob, enc, dec


current_decompress: Callable[[bytes], bytes]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bench_codec(codec: Codec, data: bytes, runs: int) -> tuple[bytes, float, float]:
    global current_decompress
    current_decompress = codec.decompress
    return timed(codec.compress, data, runs)


def fmt_num(v: float) -> str:
    return f"{v:.4f}"


def run(args: argparse.Namespace) -> int:
    codecs, skipped = load_codecs(args.algorithms)
    if not codecs:
        print("ERROR: no codecs are available", file=sys.stderr)
        for s in skipped:
            print("  " + s, file=sys.stderr)
        return 2

    files = list(iter_files(args.paths, args.include_empty))
    if not files:
        print("ERROR: no input files", file=sys.stderr)
        return 2

    out_base = Path(args.out)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    csv_path = out_base.with_suffix(".csv")
    md_path = out_base.with_suffix(".md")

    fields = [
        "file", "size_bytes", "algorithm", "compressed_bytes", "ratio",
        "saved_pct", "encode_s", "decode_s", "encode_MBps", "decode_MBps",
        "roundtrip", "orig_sha256", "error",
    ]
    rows: list[dict[str, object]] = []

    print(f"Inputs: {len(files)} files | Codecs: {', '.join(c.name for c in codecs)} | runs={args.runs}")
    if skipped:
        print("Skipped codecs:")
        for s in skipped:
            print("  " + s)

    for index, path in enumerate(files, 1):
        data = path.read_bytes()
        digest = sha256(data)
        print(f"[{index}/{len(files)}] {path} ({len(data):,} B)")
        for codec in codecs:
            try:
                blob, enc, dec = bench_codec(codec, data, args.runs)
                size = len(blob)
                ratio = size / len(data) if data else 1.0
                enc_mbps = (len(data) / 1048576.0 / enc) if enc > 0 else float("inf")
                dec_mbps = (len(data) / 1048576.0 / dec) if dec > 0 else float("inf")
                row = {
                    "file": str(path), "size_bytes": len(data), "algorithm": codec.name,
                    "compressed_bytes": size, "ratio": fmt_num(ratio),
                    "saved_pct": fmt_num(100.0 * (1.0 - ratio)),
                    "encode_s": f"{enc:.6f}", "decode_s": f"{dec:.6f}",
                    "encode_MBps": f"{enc_mbps:.3f}", "decode_MBps": f"{dec_mbps:.3f}",
                    "roundtrip": "PASS", "orig_sha256": digest, "error": "",
                }
                print(f"    {codec.name:10s} {size:10,d} B  ratio={ratio:.4f}  enc={enc:.4f}s  dec={dec:.4f}s")
            except Exception as exc:
                row = {
                    "file": str(path), "size_bytes": len(data), "algorithm": codec.name,
                    "compressed_bytes": "", "ratio": "", "saved_pct": "",
                    "encode_s": "", "decode_s": "", "encode_MBps": "", "decode_MBps": "",
                    "roundtrip": "FAIL", "orig_sha256": digest,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                print(f"    {codec.name:10s} FAIL: {exc}")
            rows.append(row)

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    summary: list[dict[str, object]] = []
    for codec in codecs:
        rs = [r for r in rows if r["algorithm"] == codec.name and r["roundtrip"] == "PASS"]
        total_orig = sum(int(r["size_bytes"]) for r in rs)
        total_comp = sum(int(r["compressed_bytes"]) for r in rs)
        enc = sum(float(r["encode_s"]) for r in rs)
        dec = sum(float(r["decode_s"]) for r in rs)
        weighted_ratio = total_comp / total_orig if total_orig else 1.0
        summary.append({
            "algorithm": codec.name, "files": len(rs), "orig": total_orig,
            "compressed": total_comp, "ratio": weighted_ratio,
            "saved": 100.0 * (1.0 - weighted_ratio), "enc": enc, "dec": dec,
            "enc_mbps": total_orig / 1048576.0 / enc if enc else float("inf"),
            "dec_mbps": total_orig / 1048576.0 / dec if dec else float("inf"),
            "ok": len(rs) == len(files),
        })
    summary.sort(key=lambda x: float(x["ratio"]))

    lines = [
        "# Unified Compression Benchmark",
        "",
        f"Generated: `{time.strftime('%Y-%m-%d %H:%M:%S')}`",
        f"Inputs: **{len(files)} files** | Runs per codec: **{args.runs}**",
        "",
        "Weighted corpus totals (sum of compressed bytes / sum of original bytes):",
        "",
        "| Rank | Algorithm | Files | Original | Compressed | Ratio | Saved | Enc s | Dec s | Enc MB/s | Dec MB/s | Lossless |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for rank, s in enumerate(summary, 1):
        lines.append(
            f"| {rank} | {s['algorithm']} | {s['files']} | {s['orig']:,} | {s['compressed']:,} | "
            f"{s['ratio']:.4f} | {s['saved']:.2f}% | {s['enc']:.3f} | {s['dec']:.3f} | "
            f"{s['enc_mbps']:.2f} | {s['dec_mbps']:.2f} | {'PASS' if s['ok'] else 'FAIL'} |"
        )
    lines += [
        "",
        "## Ranking",
        "",
        "1. **Compression ratio:** lower is better; ranking above uses weighted corpus ratio.",
        "2. **Speed:** compare encode/decode seconds or MB/s separately; ratio and speed are not collapsed into one score.",
        "3. **Losslessness:** a codec is only considered successful when decompression exactly equals the original bytes.",
        "",
        f"Per-file raw measurements: `{csv_path.name}`",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nFINAL TABLE")
    print("=" * 112)
    print(f"{'Rank':>4} {'Algorithm':<10} {'Orig':>12} {'Comp':>12} {'Ratio':>8} {'Saved':>9} {'Enc(s)':>9} {'Dec(s)':>9} {'Lossless':>9}")
    print("-" * 112)
    for rank, s in enumerate(summary, 1):
        print(f"{rank:>4} {str(s['algorithm']):<10} {s['orig']:>12,} {s['compressed']:>12,} {s['ratio']:>8.4f} {s['saved']:>8.2f}% {s['enc']:>9.3f} {s['dec']:>9.3f} {'PASS' if s['ok'] else 'FAIL':>9}")
    print("=" * 112)
    print(f"CSV: {csv_path}")
    print(f"MD : {md_path}")
    return 0 if all(bool(s["ok"]) for s in summary) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="files/directories to benchmark")
    ap.add_argument("--out", default="benchmarks/results/unified_benchmark", help="output basename (without .csv/.md)")
    ap.add_argument("--runs", type=int, default=3, help="median timing repetitions per encode/decode (default: 3)")
    ap.add_argument("--include-empty", action="store_true", help="include zero-byte files")
    ap.add_argument("--algorithms", nargs="+", choices=DEFAULT_ORDER, default=DEFAULT_ORDER,
                    help="codecs to test (default: all available)")
    args = ap.parse_args()
    if args.runs < 1:
        ap.error("--runs must be >= 1")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
