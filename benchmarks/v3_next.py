"""Next V3 optimization matrix.

No production code is changed here. Measure two low-risk levers before
changing the frozen frame: larger DE2 blocks and MAX matcher on LZ blocks.
Also reports the theoretical benefit of sharing one entropy table between
literal-length and match-length byte streams.
"""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from divideencode import de2
from divideencode.de2 import entropy, lz
from divideencode.bitstream import decode_varint

CORPUS = Path(__file__).parent / "corpus"


def corpus():
    return [(p.name, p.read_bytes()) for p in sorted(CORPUS.iterdir()) if p.is_file()]


def run_block_sizes(rows):
    print("\n=== BLOCK SIZE MATRIX ===")
    for bs in (262144, 524288, 1048576, 4194304):
        total = 0
        enc = 0.0
        for name, data in rows:
            t = time.perf_counter()
            blob = de2.compress(data, block_size=bs, level="BALANCED")
            enc += time.perf_counter() - t
            assert de2.decompress(blob) == data, name
            total += len(blob)
        print(f"block={bs:7d}  total={total:9d} B  enc={enc:7.2f}s")


def run_levels(rows):
    print("\n=== MATCHER LEVEL MATRIX ===")
    for level in ("BALANCED", "MAX"):
        total = 0
        enc = 0.0
        for name, data in rows:
            t = time.perf_counter()
            blob = de2.compress(data, level=level)
            enc += time.perf_counter() - t
            assert de2.decompress(blob) == data, name
            total += len(blob)
        print(f"level={level:8s}  total={total:9d} B  enc={enc:7.2f}s")


def joint_length_potential(rows):
    print("\n=== JOINT LL/ML ENTROPY POTENTIAL ===")
    total_old = total_joint = 0
    for name, data in rows:
        nm, literals, ll, ml, dist = lz._tokenize(data, level="BALANCED")
        old = len(entropy.encode_stream(bytes(ll))) + len(entropy.encode_stream(bytes(ml)))
        joint_raw = bytes(ll) + bytes(ml)
        joint = len(entropy.encode_stream(joint_raw))
        # framing overhead: old has two varint lengths; joint has one.
        old += len(encode_varint_len(len(ll))) + len(encode_varint_len(len(ml)))
        joint += len(encode_varint_len(len(joint_raw)))
        total_old += old
        total_joint += joint
        print(f"{name:24s} separate={old:8d} joint={joint:8d} delta={joint-old:+7d} B")
    print(f"TOTAL{'':19s} separate={total_old:8d} joint={total_joint:8d} delta={total_joint-total_old:+7d} B")


def encode_varint_len(n):
    return len(_wv(n))


def _wv(n):
    out = 1
    while n >= 128:
        n >>= 7
        out += 1
    return bytes(out)


if __name__ == "__main__":
    rows = corpus()
    run_block_sizes(rows)
    run_levels(rows)
    joint_length_potential(rows)
