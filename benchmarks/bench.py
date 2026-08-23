"""DivideEncode benchmark harness.

Measures every compressor over benchmarks/corpus/: compressed size,
ratio, percent saved, encode/decode wall time, MB/s, tracemalloc peak.
Writes machine-readable JSON to benchmarks/results/<name>.json so runs
from different commits can be diffed automatically.

Usage:
    python benchmarks/bench.py --name baseline [--reps 3] [--levels]
"""
import argparse
import bz2
import gc
import gzip
import json
import lzma
import os
import platform
import subprocess
import sys
import time
import tracemalloc
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
RESULTS = os.path.join(HERE, "results")

MB = 1024.0 * 1024.0


def git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(HERE)).decode().strip()
    except Exception:
        return "unknown"


# ------------------------------------------------------------- codecs ----

def _de2_compress(data, level=None):
    from divideencode import de2
    return de2.compress(data)


def _de2_decompress(blob):
    from divideencode import de2
    return de2.decompress(blob)


def make_codec_registry(levels=False):
    """Return {impl_name: {"compress": fn(data)->bytes,
                           "decompress": fn(blob)->bytes}}."""
    reg = {}

    def add(name, comp, decomp):
        reg[name] = {"compress": comp, "decompress": decomp}

    add("de2", _de2_compress, _de2_decompress)

    if levels:
        # DE2 matcher levels for the tuning matrix
        def mk(level):
            def c(data):
                from divideencode.de2 import lz
                return lz.encode(data, level=level)
            return c

        for name in ("FAST", "BALANCED", "MAX"):
            add("lz_" + name.lower(), mk(name), None)   # size probe only

    add("zlib_9",
        lambda d: zlib.compress(d, 9),
        lambda b: zlib.decompress(b))
    add("gzip_9",
        lambda d: gzip.compress(d, 9),
        lambda b: gzip.decompress(b))
    add("bz2_9",
        lambda d: bz2.compress(d, 9),
        lambda b: bz2.decompress(b))
    add("lzma_p6e",
        lambda d: lzma.compress(d, preset=9 | lzma.PRESET_EXTREME),
        lambda b: lzma.decompress(b))

    try:
        import zstandard
        zc = zstandard.ZstdCompressor(level=19)
        zd = zstandard.ZstdDecompressor()
        add("zstd_19", zc.compress, zd.decompress)
    except ImportError:
        pass
    try:
        import brotli
        add("brotli_q11", lambda d: brotli.compress(d, quality=11),
            brotli.decompress)
    except ImportError:
        pass
    return reg


def load_corpus():
    files = sorted(os.listdir(CORPUS))
    out = []
    for name in files:
        path = os.path.join(CORPUS, name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                out.append((name, fh.read()))
    return out


def timed(fn, arg, reps):
    best = float("inf")
    result = None
    for _ in range(reps):
        gc.collect()
        t0 = time.perf_counter()
        result = fn(arg)
        best = min(best, time.perf_counter() - t0)
    return best, result


def peak_mem(fn, arg):
    gc.collect()
    tracemalloc.start()
    r = fn(arg)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return r, peak


def measure_one(codec, data, reps, check=True, size_probe=False):
    n = len(data)
    row = {"orig": n}
    enc_t, blob = timed(codec["compress"], data, max(1, reps - 1))
    blob, peak = peak_mem(codec["compress"], data)
    row["comp"] = len(blob)
    row["ratio"] = round(len(blob) / n, 5) if n else 0.0
    row["saved_pct"] = round(100.0 * (1.0 - len(blob) / n), 2) if n else 0.0
    row["enc_s"] = round(enc_t, 4)
    row["enc_mbs"] = round(n / MB / enc_t, 2) if enc_t > 0 else None
    row["enc_peak_mb"] = round(peak / MB, 2)
    if codec.get("decompress") and not size_probe:
        dec_t, back = timed(codec["decompress"], blob, max(1, reps - 1))
        if check and bytes(back) != data:
            raise AssertionError("%s roundtrip mismatch" % codec["__name"])
        row["dec_s"] = round(dec_t, 4)
        row["dec_mbs"] = round(n / MB / dec_t, 2) if dec_t > 0 else None
    else:
        row["dec_s"] = None
        row["dec_mbs"] = None
    return row


def run(name="run", reps=3, levels=False, impls=None, files=None):
    corpus = load_corpus()
    if files:
        corpus = [(f, d) for f, d in corpus if f in files]
    reg = make_codec_registry(levels=levels)
    if impls:
        reg = {k: v for k, v in reg.items() if k in impls}

    report = {
        "meta": {
            "name": name,
            "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "commit": git_commit(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "corpus_files": [f for f, _ in corpus],
            "corpus_bytes": sum(len(d) for _, d in corpus),
            "reps": reps,
        },
        "rows": [],
    }

    for fname, data in corpus:
        for cname, codec in reg.items():
            codec["__name"] = cname
            row = {"file": fname, "impl": cname}
            row.update(measure_one(codec, data, reps,
                                   size_probe=(codec["decompress"] is None)))
            report["rows"].append(row)
            print("%-18s %-14s %9d -> %9d  (%6.2f%% saved) "
                  "enc %7.3fs %8.2f MB/s%s" % (
                      fname, cname, row["orig"], row["comp"],
                      row["saved_pct"], row["enc_s"], row["enc_mbs"] or 0,
                      "" if row["dec_s"] is None else
                      "  dec %.3fs %.2f MB/s" % (row["dec_s"],
                                                 row["dec_mbs"] or 0)))

    os.makedirs(RESULTS, exist_ok=True)
    out_path = os.path.join(RESULTS, "%s.json" % name)
    with open(out_path, "w") as fh:
        json.dump(report, fh, indent=1)
    print("\nwrote %s" % out_path)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="run")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--levels", action="store_true")
    ap.add_argument("--impls", nargs="*")
    ap.add_argument("--files", nargs="*")
    args = ap.parse_args()
    run(name=args.name, reps=args.reps, levels=args.levels,
        impls=args.impls, files=set(args.files) if args.files else None)


if __name__ == "__main__":
    main()
