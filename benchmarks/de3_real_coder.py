"""Quick DE3 end-to-end check: V2 tokenizer -> real DE3 coder -> decode."""
import argparse
import time

from divideencode.v2.lz import tokenize, apply_tokens, token_stats
from divideencode.v3.coder import encode_tokens, decode_tokens


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=450_000)
    ap.add_argument("--window", type=int, default=1 << 18)
    ap.add_argument("--chain", type=int, default=32)
    args = ap.parse_args()

    unit = b"The quick brown fox jumps over the lazy dog. "
    data = (unit * ((args.size + len(unit) - 1) // len(unit)))[:args.size]
    print("=" * 72)
    print("DE3 REAL CODER — END TO END")
    print(f"input     : {len(data):,} bytes")
    print(f"window    : {args.window:,}")
    print(f"chain     : {args.chain}")
    print("=" * 72)

    t0 = time.perf_counter()
    tokens = tokenize(data, window_size=args.window, max_chain=args.chain)
    t1 = time.perf_counter()
    blob = encode_tokens(tokens)
    t2 = time.perf_counter()
    restored = apply_tokens(decode_tokens(blob))
    t3 = time.perf_counter()
    st = token_stats(tokens)

    print(f"tokens    : {len(tokens):,}")
    print(f"literals  : {st['literals']:,}")
    print(f"matches   : {st['matches']:,}")
    print(f"reps      : {st['reps']:,}")
    print(f"DE3 size  : {len(blob):,} bytes")
    print(f"ratio     : {len(blob) / len(data):.6f}")
    print(f"saved     : {(1 - len(blob) / len(data)) * 100:.2f}%")
    print(f"tokenize  : {t1 - t0:.3f}s")
    print(f"encode    : {t2 - t1:.3f}s")
    print(f"decode    : {t3 - t2:.3f}s")
    print(f"roundtrip : {restored == data}")
    print("=" * 72)


if __name__ == "__main__":
    main()
