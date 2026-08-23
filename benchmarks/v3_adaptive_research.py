"""Benchmark the research-only adaptive representation selector."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from divideencode.v3.adaptive import analyze


def main():
    corpus = ROOT / "benchmarks" / "corpus"
    print("=" * 100)
    print("DE3 ADAPTIVE REPRESENTATION SEARCH — RESEARCH BRANCH")
    print("bounded per-block search; exact metadata cost included")
    print("=" * 100)
    total_raw = 0
    total_cost = 0
    for path in sorted(corpus.iterdir()):
        if not path.is_file():
            continue
        data = path.read_bytes()
        winners = analyze(data, block_size=1 << 20, depth=2, beam=8)
        cost = sum(w.cost for w in winners)
        total_raw += len(data)
        total_cost += cost
        chains = ", ".join(w.name or "raw" for w in winners)
        print(f"{path.name:24} raw={len(data):9,d} estimated={cost:9,d} delta={cost-len(data):+9,d}  {chains}")
    print("-" * 100)
    print(f"TOTAL                    raw={total_raw:9,d} estimated={total_cost:9,d} delta={total_cost-total_raw:+9,d}")
    print("NOTE: this is a representation-search oracle, not production compression yet.")


if __name__ == "__main__":
    main()
