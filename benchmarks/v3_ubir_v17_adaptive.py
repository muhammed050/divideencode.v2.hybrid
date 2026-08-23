"""V1.7 DE2-oriented adaptive routing experiment.

Research only: compare direct DE2 with UBIR V1.6 -> DE2 and record the
candidate that produces the smallest DE2 output. IR size is diagnostic only.

A suffix is only a routing hint: the universal codec may still reject the
actual bytes (for example, a non-canonical CSV). Such a candidate is marked
unsupported instead of aborting the complete corpus benchmark.
"""
from __future__ import annotations
import time
from pathlib import Path
from divideencode.v3 import ubir_v16 as v16
from divideencode.v3 import universal_binary_ir as de

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"
FILES = sorted(p for p in CORPUS.iterdir() if p.is_file())


def kind_for(path: Path) -> str | None:
    s = path.suffix.lower()
    if s in {".json", ".jsonl"}:
        return "json"
    if s == ".csv":
        return "csv"
    return None


def de2(blob: bytes, kind: str):
    t = time.perf_counter()
    packed = de.encode(blob, kind)
    et = time.perf_counter() - t
    t = time.perf_counter()
    out = de.decode(packed)
    dt = time.perf_counter() - t
    if out != blob:
        raise AssertionError(f"DE2 roundtrip mismatch for kind={kind}")
    return len(packed), et, dt


def try_de2(blob: bytes, kind: str):
    """Return DE2 metrics, or None when the input is not accepted by the codec."""
    try:
        return de2(blob, kind)
    except (ValueError, UnicodeError, UnicodeDecodeError) as exc:
        print(f"  direct DE2 unsupported/incompatible: {exc}")
        return None


def main():
    print("V1.7 DE2-ORIENTED ADAPTIVE ROUTING")
    print("criterion=final_DE2_size; IR_size_is_diagnostic_only")
    print("dispatch: .json/.jsonl -> json, .csv -> csv; unsupported candidates are skipped")

    for path in FILES:
        data = path.read_bytes()
        kind = kind_for(path)
        print(f"\n{path.name}")

        if kind is None:
            print("  direct DE2=unsupported by universal codec")
            print("  adaptive winner=unsupported")
            continue

        direct_result = try_de2(data, kind)
        if direct_result is None:
            print("  adaptive winner=unsupported")
            continue

        direct, det, ddt = direct_result
        print(f"  direct DE2={direct:7d} B encode={det:.2f}s de2={ddt:.2f}s kind={kind}")

        # V1.6 is currently JSON-only. Never force other formats through it.
        if kind == "json":
            t = time.perf_counter()
            ir = v16.encode(data, "json")
            iet = time.perf_counter() - t
            packed_result = try_de2(ir, "json")
            if packed_result is None:
                print("  V1.6 -> DE2 unsupported/incompatible")
                print("  adaptive winner=direct")
                continue

            packed, pet, pdt = packed_result
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
