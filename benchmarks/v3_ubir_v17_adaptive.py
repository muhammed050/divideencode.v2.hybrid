"""V1.7 DE2-oriented adaptive routing experiment.

Research only: compare direct DE2 with UBIR V1.6 -> DE2 and record the
candidate that produces the smallest DE2 output. The experiment deliberately
treats IR size as diagnostic rather than an optimization target.

V1.6 is JSON-only. Direct DE2, however, requires an explicit kind, so this
benchmark dispatches JSON/CSV by suffix and keeps unsupported formats as a
clear direct-DE2-only baseline.
"""
from __future__ import annotations
import time
from pathlib import Path
from divideencode.v3 import ubir_v16 as v16

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"

from divideencode.v3 import universal_binary_ir as de

FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def kind_for(path: Path) -> str | None:
    """Return the DE2/UBIR kind supported by the public universal codec."""
    s = path.suffix.lower()
    if s in {".json", ".jsonl"}:
        return "json"
    if s == ".csv":
        return "csv"
    return None


def de2(blob: bytes, kind: str):
    """Run DE2 with its required explicit input kind and verify roundtrip."""
    t = time.perf_counter()
    packed = de.encode(blob, kind)
    et = time.perf_counter() - t
    t = time.perf_counter()
    out = de.decode(packed)
    dt = time.perf_counter() - t
    if out != blob:
        raise AssertionError(f"DE2 roundtrip mismatch for kind={kind}")
    return len(packed), et, dt


def main():
    print("V1.7 DE2-ORIENTED ADAPTIVE ROUTING")
    print("criterion=final_DE2_size; IR_size_is_diagnostic_only")
    print("direct DE2 dispatch: .json/.jsonl -> json, .csv -> csv")

    for path in FILES:
        data = path.read_bytes()
        kind = kind_for(path)
        print(f"\n{path.name}")

        if kind is None:
            print("  direct DE2=unsupported by universal codec")
            print("  adaptive winner=unsupported")
            continue

        direct, det, ddt = de2(data, kind)
        print(f"  direct DE2={direct:7d} B encode={det:.2f}s de2={ddt:.2f}s kind={kind}")

        # V1.6 is currently JSON-only. Never force other formats through it.
        if kind == "json":
            t = time.perf_counter()
            ir = v16.encode(data, "json")
            iet = time.perf_counter() - t
            packed, pet, pdt = de2(ir, "json")
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
