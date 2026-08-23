"""Adaptive Binary Representation -> DE2 experiment.

Production DE2 is untouched.  This benchmark measures whether a lossless
structural binary representation makes DE2 see stronger repetition in JSON,
CSV and text.  The ABR stream is never materialized as a second disk file.
"""
from pathlib import Path
import sys, time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from divideencode.adaptive_binary import encode as abr_encode, decode as abr_decode, choose_mode
from divideencode.de2 import compress as de2_compress

CORPUS = Path(__file__).parent / "corpus"
BLOCK = 1 << 20


def main():
    files = sorted(p for p in CORPUS.iterdir() if p.is_file())
    print("=" * 116)
    print("ADAPTIVE BINARY REPRESENTATION -> DE2")
    print("JSON / CSV / TEXT -> lossless typed binary -> DE2; production DE2 remains unchanged")
    print("=" * 116)
    total = [0, 0, 0]
    for path in files:
        data = path.read_bytes()
        mode = choose_mode(data)
        t0 = time.perf_counter(); direct = de2_compress(data, block_size=BLOCK, level="BALANCED"); t1 = time.perf_counter()
        t2 = time.perf_counter(); abr = abr_encode(data, mode); t3 = time.perf_counter()
        if abr_decode(abr) != data:
            raise AssertionError(f"ABR roundtrip failed: {path.name}")
        packed = de2_compress(abr, block_size=BLOCK, level="BALANCED"); t4 = time.perf_counter()
        delta = len(packed) - len(direct)
        pct = delta / len(direct) * 100 if direct else 0.0
        total[0] += len(data); total[1] += len(direct); total[2] += len(packed)
        print(f"{path.name:24s} mode={mode:4s} orig={len(data):9,d}  direct={len(direct):9,d}  abr={len(abr):9,d}  abr+de2={len(packed):9,d}  delta={delta:+8,d} ({pct:+6.2f}%)  transform={t3-t2:6.3f}s de2={t4-t3:6.3f}s direct={t1-t0:6.3f}s")
    delta = total[2] - total[1]
    pct = delta / total[1] * 100 if total[1] else 0.0
    print("-" * 116)
    print(f"TOTAL{'':18s} orig={total[0]:9,d}  direct={total[1]:9,d}  abr+de2={total[2]:9,d}  delta={delta:+8,d} ({pct:+6.2f}%)")
    print("NOTE: this is an experiment branch; no production codec settings were changed.")


if __name__ == "__main__":
    main()
