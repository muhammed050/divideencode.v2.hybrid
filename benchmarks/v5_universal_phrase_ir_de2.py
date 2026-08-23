"""UBIR5 benchmark: universal phrase language -> DE2."""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress
from divideencode.universal_ir_v5 import encode, decode

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"


def de2(data: bytes):
    t = time.perf_counter()
    blob = de2_compress(data, block_size=1 << 20, level="BALANCED")
    enc = time.perf_counter() - t
    t = time.perf_counter()
    out = de2_decompress(blob)
    dec = time.perf_counter() - t
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return len(blob), enc, dec


def trial(src: bytes, lengths: tuple[int, ...], max_dict: int):
    t = time.perf_counter()
    ir, dictionary = encode(src, phrase_lengths=lengths, max_dict=max_dict)
    prep = time.perf_counter() - t
    if decode(ir) != src:
        raise AssertionError("UBIR5 roundtrip mismatch")
    size, enc, dec = de2(ir)
    return size, enc, dec, len(ir), len(dictionary), prep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=min(3, max(1, os.cpu_count() or 1)))
    ap.add_argument("--dict", type=int, default=255)
    args = ap.parse_args()
    files = sorted(p for p in CORPUS.iterdir() if p.is_file())
    configs = [
        ((4, 5, 6), args.dict),
        ((4, 5, 6, 8), args.dict),
        ((4, 5, 6, 8, 12, 16), args.dict),
        ((3, 4, 5, 6, 8, 12), min(args.dict, 128)),
    ]
    print("UBIR5 — UNIVERSAL PHRASE LANGUAGE -> DE2", flush=True)
    print("representation may grow; winner is verified final DE2 size", flush=True)
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for no, path in enumerate(files, 1):
            src = path.read_bytes()
            print(f"\n[{no}/{len(files)}] {path.name}: preparing phrase language...", flush=True)
            direct_future = pool.submit(de2, src)
            futures = [(lengths, pool.submit(trial, src, lengths, md)) for lengths, md in configs]
            dsize, denc, ddec = direct_future.result()
            print("=" * 100)
            print(f"{path.name} original={len(src):,} B")
            print(f"  DIRECT DE2={dsize:,} B ratio={dsize/len(src):.4f} enc={denc:.3f}s dec={ddec:.3f}s", flush=True)
            best = (dsize, denc, ddec, "DIRECT")
            for lengths, fut in futures:
                size, enc, dec, ir_size, dict_size, prep = fut.result()
                label = "PHRASE[" + ",".join(map(str, lengths)) + "]"
                print(f"  {label:<20} dict={dict_size:3d} IR={ir_size:,} -> DE2={size:,} ratio={size/len(src):.4f} prep={prep:.3f}s enc={enc:.3f}s dec={dec:.3f}s ok", flush=True)
                if size < best[0]:
                    best = (size, enc, dec, label)
            print(f"  WINNER {best[3]}; gain_vs_direct={dsize-best[0]:+,} B", flush=True)

if __name__ == "__main__":
    main()
