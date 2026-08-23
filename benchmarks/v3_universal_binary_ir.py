from pathlib import Path
import sys, time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from divideencode import de2
from divideencode.v3 import universal_binary_ir as ubir

CORPUS = Path(__file__).parent / "corpus"
BS = 1 << 20


def run():
    print("=" * 120)
    print("V3 UBIR — UNIVERSAL BINARY IR: JSON/CSV -> TYPED IR -> DE2")
    print("byte-exact; 1 MiB DE2 blocks; selection uses final packed size only")
    print("=" * 120)
    direct_total = 0
    ubir_total = 0
    wins = 0
    for p in sorted(CORPUS.iterdir()):
        if not p.is_file():
            continue
        data = p.read_bytes()
        t = time.perf_counter()
        direct = de2.compress(data, block_size=BS, level="BALANCED")
        direct_t = time.perf_counter() - t
        assert de2.decompress(direct) == data
        best = (len(direct), "direct", len(data), direct_t)
        for kind, mid in ubir.candidates(data, p.suffix):
            assert ubir.decode(mid) == data
            t = time.perf_counter()
            packed = de2.compress(mid, block_size=BS, level="BALANCED")
            enc_t = time.perf_counter() - t
            assert de2.decompress(packed) == mid
            if len(packed) < best[0]:
                best = (len(packed), f"ubir:{kind}", len(mid), enc_t)
        direct_total += len(direct)
        ubir_total += best[0]
        if best[1] != "direct":
            wins += 1
        print(f"{p.name:24s} direct={len(direct):9,d} best={best[0]:9,d} "
              f"delta={best[0]-len(direct):+9,d} choice={best[1]:14s} "
              f"mid={best[2]:9,d} enc={best[3]:5.2f}s")
    delta = ubir_total - direct_total
    print("-" * 120)
    print(f"TOTAL direct={direct_total:,} B UBIR={ubir_total:,} B "
          f"delta={delta:+,} B ({(delta/direct_total)*100:+.2f}%) wins={wins}")


if __name__ == "__main__":
    run()
