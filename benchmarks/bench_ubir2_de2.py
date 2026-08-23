from __future__ import annotations

import argparse
import pathlib
import time

from divideencode.de2 import compress as de2_compress
from divideencode.de2 import decompress as de2_decompress
from divideencode.universal_binary import compress_with_stats, decompress as ubir_decompress

CORPUS = pathlib.Path(__file__).with_name("corpus")
DEFAULT_FILES = [
    "app.log", "binary.bin", "compressed.zip", "data.csv",
    "json_large.json", "json_small.json", "natural.txt", "page.html",
    "random.raw", "repeat.txt", "src_medium.c", "src_small.c", "styles.css",
]


def run_one(path: pathlib.Path, mode: str) -> None:
    src = path.read_bytes()

    t0 = time.perf_counter()
    direct = de2_compress(src, level="BALANCED")
    direct_enc = time.perf_counter() - t0

    t0 = time.perf_counter()
    direct_dec = de2_decompress(direct, verify=True)
    direct_dec_t = time.perf_counter() - t0
    assert direct_dec == src

    t0 = time.perf_counter()
    result = compress_with_stats(src, mode=mode, level="BALANCED")
    ubir_enc = time.perf_counter() - t0

    t0 = time.perf_counter()
    restored = ubir_decompress(result.data, verify=True)
    ubir_dec_t = time.perf_counter() - t0
    assert restored == src

    gain = len(direct) - result.de2_size
    gain_pct = (gain / len(direct) * 100.0) if direct else 0.0
    ratio_direct = len(direct) / len(src) if src else 0.0
    ratio_ubir = result.de2_size / len(src) if src else 0.0

    print(f"{path.name}: original={len(src):,} B")
    print(f"  DIRECT  de2={len(direct):,} ratio={ratio_direct:.4f} enc={direct_enc:.3f}s dec={direct_dec_t:.3f}s")
    print(f"  UBIR2   de2={result.de2_size:,} ratio={ratio_ubir:.4f} kind={result.kind.name} ir={result.ir_size:,} tested={result.candidates_tested} enc={ubir_enc:.3f}s dec={ubir_dec_t:.3f}s")
    if gain > 0:
        print(f"  WINNER  UBIR2; gain_vs_direct=+{gain:,} B ({gain_pct:.2f}%)")
    elif gain < 0:
        print(f"  WINNER  DIRECT; UBIR2 penalty={-gain:,} B")
    else:
        print("  WINNER  TIE")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["FAST", "BALANCED", "MAX"], default="BALANCED")
    ap.add_argument("--files", nargs="*", default=DEFAULT_FILES)
    args = ap.parse_args()
    print(f"UBIR2 — UNIVERSAL BINARY IR -> DE2 [{args.mode}]")
    print("IR size is not the objective; winner is verified final DE2 size")
    print("=" * 80)
    for name in args.files:
        run_one(CORPUS / name, args.mode)


if __name__ == "__main__":
    main()
