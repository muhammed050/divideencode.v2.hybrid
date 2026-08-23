"""Profile DE2 encode/decode hotspots. Usage: python benchmarks/profile.py"""
import cProfile
import io
import os
import pstats
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from divideencode import de2


def load(name):
    with open(os.path.join(os.path.dirname(__file__), "corpus", name),
              "rb") as fh:
        return fh.read()


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "natural.txt"
    data = load(which)
    print("== %s (%d bytes) ==" % (which, len(data)))

    pr = cProfile.Profile()
    pr.enable()
    blob = de2.compress(data)
    pr.disable()
    print("\n--- ENCODE ---")
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(14)
    print(s.getvalue())

    pr = cProfile.Profile()
    pr.enable()
    out = de2.decompress(blob)
    pr.disable()
    assert out == data
    print("--- DECODE ---")
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(14)
    print(s.getvalue())


if __name__ == "__main__":
    main()
