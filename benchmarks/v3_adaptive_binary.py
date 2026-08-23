"""ABR -> DE2 experiment.

Compares direct DE2 against a lossless Adaptive Binary Representation (ABR)
preconditioner followed by the same 1 MiB DE2 engine.  ABR is accepted only
when the complete packed result wins; direct DE2 remains the fallback.
"""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from divideencode import de2
from divideencode.v3 import adaptive_binary as abr

CORPUS = Path(__file__).parent / "corpus"
BLOCK_SIZE = 1 << 20


def corpus():
    return [(p.name, p.read_bytes()) for p in sorted(CORPUS.iterdir()) if p.is_file()]


def run(rows):
    print("=" * 116)
    print("V3 ABR EXPERIMENT — STRUCTURED TEXT/JSON/CSV -> BINARY -> DE2")
    print("same DE2 engine, 1 MiB blocks; ABR is selected only on end-to-end size")
    print("=" * 116)
    total_direct = total_abr = 0
    for name, data in rows:
        t0 = time.perf_counter()
        direct = de2.compress(data, block_size=BLOCK_SIZE, level="BALANCED")
        td = time.perf_counter() - t0
        assert de2.decompress(direct) == data

        best = None
        for kind, encoded in abr.candidates(data, Path(name).suffix):
            t1 = time.perf_counter()
            packed = de2.compress(encoded, block_size=BLOCK_SIZE, level="BALANCED")
            ta = time.perf_counter() - t1
            assert abr.decode(de2.decompress(packed)) == data
            if best is None or len(packed) < len(best[1]):
                best = (kind, packed, ta, len(encoded))

        if best is None or len(direct) <= len(best[1]):
            chosen = "direct"
            out = direct
            tc = td
            intermediate = len(data)
        else:
            chosen = "ABR:" + best[0]
            out = best[1]
            tc = best[2]
            intermediate = best[3]

        total_direct += len(direct)
        total_abr += len(out)
        delta = len(out) - len(direct)
        print(f"{name:24s} direct={len(direct):9,d}  best={len(out):9,d}  delta={delta:+9,d}  choice={chosen:10s}  mid={intermediate:9,d}  enc={tc:6.2f}s")

    print("-" * 116)
    print(f"TOTAL direct={total_direct:,} B  adaptive={total_abr:,} B  delta={total_abr-total_direct:+,} B")
    if total_abr < total_direct:
        print("RESULT: ABR wins end-to-end on this corpus.")
    else:
        print("RESULT: ABR does not win yet; direct DE2 remains the selected baseline.")


if __name__ == "__main__":
    run(corpus())
