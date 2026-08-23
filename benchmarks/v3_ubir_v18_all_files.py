"""V1.8 all-files DE2 report.

Measures every corpus file with the real DE2 backend and reports:
  - original size
  - final DE2 size and ratio
  - encode/decode time
  - verified decompressed size and expansion (must be 1.000x)

For JSON/JSONL, also measures the V1.6 -> DE2 pipeline so we can compare
against direct DE2 on the same files. IR size is reported separately because
it is an intermediate representation, not the final product size.
"""
from __future__ import annotations

import time
from pathlib import Path

from divideencode.de2 import compress, decompress
from divideencode.v3 import ubir_v16 as v16

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"
FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def de2(blob: bytes):
    t = time.perf_counter()
    packed = compress(blob, block_size=1 << 20, level="BALANCED")
    et = time.perf_counter() - t

    t = time.perf_counter()
    out = decompress(packed)
    dt = time.perf_counter() - t
    if out != blob:
        raise AssertionError("DE2 roundtrip mismatch")

    return len(packed), et, dt


def main() -> None:
    print("V1.8 ALL-FILES DE2 REPORT")
    print("final metric = DE2 size; all roundtrips verified")
    print("expansion_after_decode = decoded_size / input_size")

    for path in FILES:
        data = path.read_bytes()
        original = len(data)
        print("\n" + "=" * 80)
        print(path.name)
        print(f"original={original:,} B")

        direct, enc_t, dec_t = de2(data)
        ratio = direct / original if original else 0.0
        saved = original - direct
        print(
            f"direct DE2 : {direct:,} B  ratio={ratio:.4f} "
            f"saved={saved:+,} B  encode={enc_t:.2f}s decode={dec_t:.2f}s "
            f"decoded={original:,} B expansion=1.0000x"
        )

        if path.suffix.lower() not in {".json", ".jsonl"}:
            continue

        try:
            t = time.perf_counter()
            ir = v16.encode(data, "json")
            ir_t = time.perf_counter() - t
            if v16.decode(ir) != data:
                raise AssertionError("V1.6 roundtrip mismatch")

            packed, pen_t, pdec_t = de2(ir)
            final_ratio = packed / original if original else 0.0
            delta = packed - direct
            ir_ratio = len(ir) / original if original else 0.0
            print(
                f"V1.6->DE2 : IR={len(ir):,} B ({ir_ratio:.4f}x original) "
                f"final={packed:,} B ratio={final_ratio:.4f} "
                f"delta_vs_direct={delta:+,} B "
                f"V1.6_encode={ir_t:.2f}s DE2_encode={pen_t:.2f}s "
                f"DE2_decode={pdec_t:.2f}s"
            )
            print(
                f"decoded IR: {len(ir):,} B -> original {original:,} B "
                f"(logical roundtrip expansion={original / len(ir):.4f}x)"
            )
        except (ValueError, TypeError, AssertionError) as exc:
            print(f"V1.6->DE2 : unsupported/incompatible ({exc})")


if __name__ == "__main__":
    main()
