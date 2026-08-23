"""Measure the DE3 merged token coder against the current V3 frame.

The benchmark is intentionally a representation experiment: it derives the
V3 token sequence directly from the matcher, validates that sequence against
the source bytes, and then compares entropy representations.  It does not
make the experiment depend on the legacy V3 frame decoder, whose correctness
is a separate concern.
"""
from pathlib import Path
import time

# Make direct execution from benchmarks/ work from a source checkout.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from divideencode.bitstream import decode_varint
from divideencode.de2 import lz
from divideencode.v3.coder import encode_tokens, decode_tokens

CORPUS = Path(__file__).parent / "corpus"


def _tokens_from_v3(data, level="BALANCED"):
    nm, literals, ll, ml, dist = lz._tokenize(data, level=level)
    tokens = []
    p_lit = p_ll = p_ml = p_ds = 0
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


def _reconstruct(tokens):
    """Rebuild source bytes from the merged token sequence.

    This is deliberately independent of the DE2 frame decoder so a frame-level
    regression cannot invalidate the representation experiment.
    """
    out = bytearray()
    reps = [1, 2, 4, 8]
    for token in tokens:
        kind = token[0]
        if kind == 0:
            out.append(token[1])
            continue

        length = token[1]
        if kind == 1:
            distance = token[2]
            if distance < 1 or distance > len(out):
                raise ValueError("invalid explicit distance in token stream")
            reps.insert(0, distance)
            del reps[4:]
        elif kind == 2:
            index = token[2]
            if not 0 <= index < 4:
                raise ValueError("invalid repeat index in token stream")
            distance = reps[index]
            if distance < 1 or distance > len(out):
                raise ValueError("invalid repeat distance in token stream")
            if index:
                distance = reps.pop(index)
                reps.insert(0, distance)
        else:
            raise ValueError("unknown token kind")

        if distance > len(out):
            raise ValueError("distance exceeds produced output")
        for _ in range(length):
            out.append(out[-distance])
    return bytes(out)


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
        if _reconstruct(tokens) != data:
            raise AssertionError(f"V3 matcher token roundtrip failed: {path.name}")
        new = encode_tokens(tokens)
        if decode_tokens(new) != tokens:
            raise AssertionError(f"DE3 merged coder roundtrip failed: {path.name}")
        t2 = time.perf_counter()

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
    print("NOTE: representation experiment only; production V3 frame remains unchanged.")


if __name__ == "__main__":
    main()
