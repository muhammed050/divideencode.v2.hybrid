"""Measure the DE3 merged token coder against the current V3 frame.

This benchmark deliberately does not change the production codec. It reuses
V3's existing tokenizer, reconstructs its token sequence from the separated
literal/length/distance streams, and then serializes the same tokens with the
DE3-derived merged canonical-Huffman coder. That isolates the representation
change before we wire a new frame into the codec.
"""
from pathlib import Path
import time

from divideencode.bitstream import decode_varint
from divideencode.de2 import lz
from divideencode.v3.coder import encode_tokens

CORPUS = Path(__file__).parent / "corpus"


def _tokens_from_v3(data, level="BALANCED"):
    nm, literals, ll, ml, dist = lz._tokenize(data, level=level)
    tokens = []
    p_lit = 0
    p_ll = 0
    p_ml = 0
    p_ds = 0
    for _ in range(nm):
        lit_len, p_ll = decode_varint(ll, p_ll, len(ll))
        if p_lit + lit_len > len(literals):
            raise ValueError("literal stream accounting mismatch")
        tokens.extend((0, b) for b in literals[p_lit:p_lit + lit_len])
        p_lit += lit_len

        match_len, p_ml = decode_varint(ml, p_ml, len(ml))
        d, p_ds = decode_varint(dist, p_ds, len(dist))
        if d <= 3:
            tokens.append((2, match_len + lz.MIN_MATCH, d))
        else:
            tokens.append((1, match_len + lz.MIN_MATCH, d - 3))

    if p_lit < len(literals):
        tokens.extend((0, b) for b in literals[p_lit:])
    if p_ll != len(ll) or p_ml != len(ml) or p_ds != len(dist):
        raise ValueError("token stream accounting mismatch")
    return tokens


def main():
    files = sorted(p for p in CORPUS.iterdir() if p.is_file())
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")

    print("=" * 108)
    print("V3 EXISTING FRAME vs DE3-DERIVED MERGED TOKEN CODER")
    print("same matcher, same token sequence; only the entropy representation changes")
    print("=" * 108)
    total_old = total_new = 0

    for path in files:
        data = path.read_bytes()
        t0 = time.perf_counter()
        old = lz.encode_v2(data, level="BALANCED")
        t1 = time.perf_counter()
        tokens = _tokens_from_v3(data, level="BALANCED")
        new = encode_tokens(tokens)
        t2 = time.perf_counter()
        if lz.decode_v2(old, 0, len(old), len(data), lz.entropy.DecodeTables())[0] != data:
            raise AssertionError(f"V3 roundtrip failed: {path.name}")

        total_old += len(old)
        total_new += len(new)
        delta = len(new) - len(old)
        pct = delta / len(old) * 100 if old else 0.0
        print(f"{path.name:28s} old={len(old):9,d} B  merged={len(new):9,d} B  "
              f"delta={delta:+8,d} B ({pct:+6.2f}%)  "
              f"lz={t1-t0:7.3f}s coder={t2-t1:7.3f}s")

    delta = total_new - total_old
    pct = delta / total_old * 100 if total_old else 0.0
    print("-" * 108)
    print(f"TOTAL{'':23s} old={total_old:9,d} B  merged={total_new:9,d} B  "
          f"delta={delta:+8,d} B ({pct:+6.2f}%)")
    print("NOTE: this is a representation experiment; the production V3 frame is unchanged.")


if __name__ == "__main__":
    main()
