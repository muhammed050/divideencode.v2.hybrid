"""Pattern/dictionary preconditioner experiment for DE2.

The transform replaces repeated fixed-width byte sequences with compact IDs and
stores the dictionary as part of the reversible representation. It is deliberately
conservative: candidates are scored by the *final* DE2 payload plus dictionary
metadata, and only exact round trips are accepted.
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
    data: bytes
    restore: object
    metadata: int


def run_de2(data: bytes):
    t0 = time.perf_counter()
    blob = de2_compress(data, block_size=1 << 20, level="BALANCED")
    enc = time.perf_counter() - t0
    t0 = time.perf_counter()
    out = de2_decompress(blob)
    dec = time.perf_counter() - t0
    if out != data:
        raise AssertionError("DE2 roundtrip mismatch")
    return blob, enc, dec


def dictionary_encode(src: bytes, width: int, min_count: int = 3):
    """Replace repeated non-overlapping fixed-width chunks by dictionary IDs.

    ID 0 is an escape followed by a literal chunk; IDs 1..K reference dictionary
    entries. A small dictionary is preferred so metadata does not dominate.
    """
    if len(src) < width * min_count:
        return None

    counts: dict[bytes, int] = {}
    # Count chunks at every aligned position. Alignment is deterministic and
    # cheap; the literal escape preserves bytes that do not belong to a pattern.
    for i in range(0, len(src) - width + 1, width):
        chunk = src[i:i + width]
        counts[chunk] = counts.get(chunk, 0) + 1

    patterns = [c for c, n in counts.items() if n >= min_count]
    patterns.sort(key=lambda c: (-counts[c], c))
    patterns = patterns[:255]
    if not patterns:
        return None

    ids = {p: i + 1 for i, p in enumerate(patterns)}
    out = bytearray()
    i = 0
    while i < len(src):
        chunk = src[i:i + width]
        code = ids.get(chunk)
        if code is not None and len(chunk) == width:
            out.append(code)
            i += width
        else:
            out.append(0)
            out += chunk
            i += len(chunk)

    # Header: magic, width, number of patterns, original size, then dictionary.
    header = b"PD1" + bytes([width, len(patterns)]) + struct.pack(">I", len(src))
    table = b"".join(patterns)
    packed = header + table + bytes(out)
    metadata = len(header) + len(table)
    return packed, metadata


def dictionary_decode(blob: bytes):
    if len(blob) < 9 or blob[:3] != b"PD1":
        raise ValueError("bad PD1")
    width = blob[3]
    count = blob[4]
    original_size = struct.unpack(">I", blob[5:9])[0]
    pos = 9
    table_size = count * width
    if pos + table_size > len(blob):
        raise ValueError("truncated dictionary")
    table = [blob[pos + i * width:pos + (i + 1) * width] for i in range(count)]
    pos += table_size
    body = blob[pos:]
    out = bytearray()
    i = 0
    while i < len(body):
        code = body[i]
        i += 1
        if code == 0:
            if i + width > len(body):
                raise ValueError("truncated literal")
            out += body[i:i + width]
            i += width
        else:
            idx = code - 1
            if idx >= len(table):
                raise ValueError("bad dictionary id")
            out += table[idx]
    # The encoder operates in width-sized units, so the original length must be
    # exact. This also catches malformed trailing literals.
    if len(out) != original_size:
        raise ValueError("size mismatch")
    return bytes(out)


def candidates(src: bytes):
    for width in (2, 3, 4, 8, 16):
        result = dictionary_encode(src, width)
        if result is None:
            continue
        packed, metadata = result
        yield Candidate(
            f"dict{width}",
            packed,
            lambda x, _n: dictionary_decode(x),
            metadata,
        )


def main():
    files = sorted(p for p in CORPUS.iterdir() if p.is_file()) if CORPUS.exists() else []
    if not files:
        raise SystemExit(f"No corpus files found in {CORPUS}")

    print("DE2 PATTERN/DICTIONARY PRECONDITIONER")
    print("Repeated fixed-width chunks -> dictionary IDs -> DE2")

    for path in files:
        src = path.read_bytes()
        original = len(src)
        direct, de, dd = run_de2(src)
        print("\n" + "=" * 100)
        print(f"{path.name} original={original:,} B")
        print(f"  direct-DE2 final={len(direct):,} B ratio={len(direct)/original:.4f} enc={de:.3f}s dec={dd:.3f}s")
        best = (len(direct), "direct-DE2")
        for cand in candidates(src):
            blob, enc, dec = run_de2(cand.data)
            restored = cand.restore(de2_decompress(blob), original)
            if restored != src:
                raise AssertionError(f"{cand.name} roundtrip mismatch")
            final = len(blob)  # dictionary/header are already inside cand.data and compressed by DE2
            print(
                f"  {cand.name:<8} repr={len(cand.data):>9,} B "
                f"DE2={len(blob):>9,} B FINAL={final:>9,} B "
                f"ratio={final/original:.4f} enc={enc:.3f}s dec={dec:.3f}s ok"
            )
            if final < best[0]:
                best = (final, cand.name)
        if best[1] == "direct-DE2":
            print(f"  WINNER direct-DE2; candidate_delta={best[0]-len(direct):+,} B")
        else:
            print(f"  WINNER {best[1]}; gain_vs_direct={len(direct)-best[0]:+,} B")


if __name__ == "__main__":
    main()
