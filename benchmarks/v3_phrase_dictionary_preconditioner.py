"""DE2-aware phrase dictionary preconditioner experiment.

Unlike fixed-width dictionaries, this experiment discovers repeated byte phrases at
arbitrary offsets. Candidates are selected by the final DE2 size, so a larger
intermediate representation is allowed when it creates better LZ/Huffman structure.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from pathlib import Path

from divideencode.de2 import compress as de2_compress, decompress as de2_decompress

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "corpus"


@dataclass(frozen=True)
class Candidate:
    name: str
    packed: bytes
    dictionary: tuple[bytes, ...]


def run_de2(data: bytes):
    t = time.perf_counter()
    blob = de2_compress(data, block_size=1 << 20, level="BALANCED")
    enc = time.perf_counter() - t
    t = time.perf_counter()
    out = de2_decompress(blob)
    dec = time.perf_counter() - t
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return blob, enc, dec


def _pack(dictionary: list[bytes], stream: bytes, original_size: int) -> bytes:
    # PD3: magic, count, original size, then varint-ish fixed 2-byte phrase lengths.
    # Phrase lengths are <=255 in this experiment. Keeping the header simple makes
    # the benchmark deterministic and the representation independently decodable.
    if len(dictionary) > 255:
        raise ValueError("dictionary too large")
    out = bytearray(b"PD3")
    out.append(len(dictionary))
    out += struct.pack(">I", original_size)
    for phrase in dictionary:
        if not (3 <= len(phrase) <= 255):
            raise ValueError("invalid phrase length")
        out.append(len(phrase))
        out += phrase
    out += stream
    return bytes(out)


def _unpack(blob: bytes) -> tuple[tuple[bytes, ...], bytes, int]:
    if len(blob) < 8 or blob[:3] != b"PD3":
        raise ValueError("bad PD3")
    count = blob[3]
    original_size = struct.unpack(">I", blob[4:8])[0]
    pos = 8
    d: list[bytes] = []
    for _ in range(count):
        if pos >= len(blob):
            raise ValueError("truncated dictionary")
        n = blob[pos]
        pos += 1
        if n < 3 or pos + n > len(blob):
            raise ValueError("invalid dictionary entry")
        d.append(bytes(blob[pos:pos + n]))
        pos += n
    return tuple(d), bytes(blob[pos:]), original_size


def _decode(blob: bytes) -> bytes:
    dictionary, stream, original_size = _unpack(blob)
    out = bytearray()
    i = 0
    while i < len(stream):
        code = stream[i]
        i += 1
        if code == 0:
            if i >= len(stream):
                raise ValueError("truncated literal length")
            n = stream[i]
            i += 1
            if i + n > len(stream):
                raise ValueError("truncated literal")
            out += stream[i:i + n]
            i += n
        else:
            idx = code - 1
            if idx >= len(dictionary):
                raise ValueError("bad phrase id")
            out += dictionary[idx]
    if len(out) != original_size:
        raise ValueError(f"size mismatch: {len(out)} != {original_size}")
    return bytes(out)


def _discover(src: bytes, length: int, max_entries: int = 255, min_count: int = 4):
    """Find repeated phrases at arbitrary offsets using a bounded n-gram scan."""
    if len(src) < length * min_count:
        return []
    counts: dict[bytes, int] = {}
    step = max(1, length // 2)
    # Sampling every half-length gives arbitrary-ish offsets without making the
    # benchmark quadratic on multi-megabyte files.
    for i in range(0, len(src) - length + 1, step):
        p = src[i:i + length]
        counts[p] = counts.get(p, 0) + 1
    ranked = [(n, p) for p, n in counts.items() if n >= min_count]
    ranked.sort(key=lambda x: (-(x[0] * (length - 2)), -x[0], x[1]))
    return [p for _, p in ranked[:max_entries]]


def _encode(src: bytes, dictionary: list[bytes]) -> bytes:
    """Greedy longest phrase replacement with 0 + length + literal escapes."""
    by_first: dict[int, list[tuple[bytes, int]]] = {}
    for idx, p in enumerate(dictionary, 1):
        by_first.setdefault(p[0], []).append((p, idx))
    for k in by_first:
        by_first[k].sort(key=lambda x: len(x[0]), reverse=True)

    out = bytearray()
    i = 0
    literal = bytearray()
    while i < len(src):
        matches = by_first.get(src[i])
        found = None
        if matches:
            for p, idx in matches:
                if src.startswith(p, i):
                    found = (p, idx)
                    break
        if found:
            if literal:
                # Literal runs are chunked so each escape has a byte length.
                while literal:
                    n = min(255, len(literal))
                    out.append(0)
                    out.append(n)
                    out += literal[:n]
                    del literal[:n]
            p, idx = found
            out.append(idx)
            i += len(p)
        else:
            literal.append(src[i])
            i += 1
    while literal:
        n = min(255, len(literal))
        out.append(0)
        out.append(n)
        out += literal[:n]
        del literal[:n]
    return bytes(out)


def candidates(src: bytes):
    # Shorter phrases can expose local structure; longer phrases can turn repeated
    # records/HTML/JSON fragments into extremely low-entropy symbol streams.
    for length in (3, 4, 5, 6, 8, 12, 16, 24, 32, 48, 64):
        dictionary = _discover(src, length)
        if not dictionary:
            continue
        packed = _pack(dictionary, _encode(src, dictionary), len(src))
        yield Candidate(f"phrase{length}", packed, tuple(dictionary))


def main():
    files = sorted(p for p in CORPUS.iterdir() if p.is_file()) if CORPUS.exists() else []
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")
    print("DE2-AWARE PHRASE DICTIONARY")
    print("arbitrary-offset repeated phrases -> IDs -> DE2; winner = smallest verified final DE2")

    for path in files:
        src = path.read_bytes()
        direct, de, dd = run_de2(src)
        print("\n" + "=" * 100)
        print(f"{path.name} original={len(src):,} B")
        print(f"  direct-DE2 final={len(direct):,} B ratio={len(direct)/len(src):.4f} enc={de:.3f}s dec={dd:.3f}s")
        best_size = len(direct)
        best_name = "direct-DE2"
        for cand in candidates(src):
            blob, enc, dec = run_de2(cand.packed)
            restored = _decode(de2_decompress(blob))
            if restored != src:
                raise AssertionError(f"{cand.name} roundtrip mismatch")
            final = len(blob)
            print(f"  {cand.name:<10} dict={len(cand.dictionary):>3} repr={len(cand.packed):>9,} B DE2={final:>9,} B ratio={final/len(src):.4f} enc={enc:.3f}s dec={dec:.3f}s ok")
            if final < best_size:
                best_size = final
                best_name = cand.name
        if best_name == "direct-DE2":
            print(f"  WINNER direct-DE2; candidate_delta={best_size-len(direct):+,} B")
        else:
            print(f"  WINNER {best_name}; gain_vs_direct={len(direct)-best_size:+,} B")


if __name__ == "__main__":
    main()
