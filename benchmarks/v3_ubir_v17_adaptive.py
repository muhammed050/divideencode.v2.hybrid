"""V1.7 DE2-oriented adaptive routing experiment.

The important distinction here is:
  * UBIR is the representation layer.
  * DE2 is the downstream compressor.

Therefore DE2 must be measured with divideencode.de2.compress(), not by
feeding an already-binary UBIR blob back into the UBIR codec.  The latter
was the source of the bogus multi-megabyte JSON result in the previous
benchmark.

Research only: compare direct DE2 with UBIR V1.6 -> DE2 and record the
candidate that produces the smallest DE2 output. IR size is diagnostic only.
"""
from __future__ import annotations
import time
from pathlib import Path
from divideencode.de2 import compress
from divideencode.v3 import ubir_v16 as v16

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"
FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def kind_for(path: Path) -> str | None:
    s = path.suffix.lower()
    if s in {".json", ".jsonl"}:
        return "json"
    return None


def de2(blob: bytes):
    """Compress one byte stream with the real DE2 backend and verify it."""
    t = time.perf_counter()
    packed = compress(blob, block_size=1 << 20, level="BALANCED")
    et = time.perf_counter() - t
    # DE2 has its own decoder; keep the benchmark honest with a roundtrip.
    from divideencode.de2 import decompress
    t = time.perf_counter()
    out = decompress(packed)
    dt = time.perf_counter() - t
    if out != blob:
        raise AssertionError("DE2 roundtrip mismatch")
    return len(packed), et, dt


def main():
    print("V1.7 DE2-ORIENTED ADAPTIVE ROUTING")
    print("criterion=final_DE2_size; IR_size_is_diagnostic_only")
    print("direct candidate = DE2(data); JSON candidate = DE2(V1.6(data))")

    for path in FILES:
        data = path.read_bytes()
        kind = kind_for(path)
        print(f"\n{path.name}")

        # Baseline: every corpus file gets a fair direct-DE2 measurement.
        direct, det, ddt = de2(data)
        print(f"  direct DE2={direct:7d} B encode={det:.2f}s de2={ddt:.2f}s")

        # V1.6 is intentionally restricted to JSON for this experiment.
        if kind != "json":
            print("  V1.6 candidate=skipped (V1.6 currently JSON-only)")
            print("  adaptive winner=direct")
            continue

        t = time.perf_counter()
        ir = v16.encode(data, kind)
        iet = time.perf_counter() - t
        if v16.decode(ir) != data:
            raise AssertionError("V1.6 roundtrip mismatch")

        packed, pet, pdt = de2(ir)
        print(
            f"  V1.6  IR={len(ir):7d} B DE2={packed:7d} B "
            f"delta={packed-direct:+7d} B encode={iet:.2f}s de2={pdt:.2f}s"
        )
        winner = "direct" if direct <= packed else "V1.6"
        print(f"  adaptive winner={winner}")


if __name__ == "__main__":
    main()
