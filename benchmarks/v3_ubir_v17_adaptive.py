"""V1.7 DE2-oriented adaptive routing experiment.

Research only: compare direct DE2 with UBIR V1.6 -> DE2 and record the
candidate that produces the smallest DE2 output. The experiment deliberately
treats IR size as diagnostic rather than an optimization target.

This benchmark is intentionally generic at the routing layer. V1.6 itself
currently supports JSON only, so non-JSON corpus files are measured as direct
DE2 baselines and reported as unsupported-by-UBIR rather than being forced
through a JSON transform.
"""
from __future__ import annotations
import time
from pathlib import Path
from divideencode.v3 import ubir_v16 as v16

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"

try:
    from divideencode.v3 import universal_binary_ir as de
except ImportError:
    de = None

# Keep corpus discovery generic; do not hard-code JSON as the only workload.
FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def de2(blob: bytes):
    """Run the project's DE2 codec if its public API is available."""
    # Existing V3 benchmarks expose DE2 through the top-level v1 module.
    if hasattr(de, "encode"):
        t = time.perf_counter()
        packed = de.encode(blob)
        et = time.perf_counter() - t
        t = time.perf_counter()
        out = de.decode(packed)
        dt = time.perf_counter() - t
        if out != blob:
            raise AssertionError("DE2 roundtrip mismatch")
        return len(packed), et, dt
    raise RuntimeError("DE2 API not found")


def main():
    print("V1.7 DE2-ORIENTED ADAPTIVE ROUTING")
    print("criterion=final_DE2_size; IR_size_is_diagnostic_only")
    for path in FILES:
        data = path.read_bytes()
        direct, det, ddt = de2(data)
        print(f"\n{path.name}")
        print(f"  direct DE2={direct:7d} B encode={det:.2f}s de2={ddt:.2f}s")

        # V1.6 is currently JSON-only. Never force other formats through it.
        if path.suffix.lower() == ".json":
            t = time.perf_counter()
            ir = v16.encode(data, "json")
            iet = time.perf_counter() - t
            packed, pet, pdt = de2(ir)
            recovered = v16.decode(ir)
            if recovered != data:
                raise AssertionError("V1.6 roundtrip mismatch")
            print(f"  V1.6  IR={len(ir):7d} B DE2={packed:7d} B "
                  f"delta={packed-direct:+7d} B encode={iet:.2f}s de2={pdt:.2f}s")
            winner = "direct" if direct <= packed else "V1.6"
            print(f"  adaptive winner={winner}")
        else:
            print("  V1.6  unsupported (not JSON) -> adaptive keeps direct")
            print("  adaptive winner=direct")


if __name__ == "__main__":
    main()
