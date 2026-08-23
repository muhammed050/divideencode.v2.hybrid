# DivideEncode

Experimental lossless data-compression library, built to test whether mathematical transforms (repeated division, delta/quotient-remainder encoding, pattern detection) can beat or complement conventional compressors on specific data classes — while never regressing on general-purpose data.

This package contains three independent, coexisting codecs:

- **`divideencode`** (V1 / DE1) — the original adaptive tree search: RAW / RLE / Huffman / LZ leaves with DELTA / DIVIDE / DICT transform children, picking whichever produces the smallest total size.
- **`divideencode.v2`** (V2 / DE2) — a from-scratch redesign: modern hash-chain LZ77 with lazy matching, separated literal/length/distance streams, canonical Huffman, and lightweight numeric pre-transforms.
- **`divideencode.v2.hybrid`** (HYBRID / DEH) — the general adaptive codec. It measures LZMA, DELTA+LZMA and DE2 and keeps the smallest complete result, with STORED fallback.

## New research lane: Adaptive Representation Search

The `feature/adaptive-representations` branch adds a fourth experimental lane: **representation before DE2**.

The key idea is not to turn JPEG/MP4/ZIP/EXE into literal CSV or JSON. Instead, DE2 receives a reversible representation of the same bytes that preserves information and normally preserves byte length. The intermediate representation is allowed to be useless or even visually/semantically larger; it is selected only when the **final DE2 container** is smaller than every other candidate.

Current reversible representations:

- `BITPLANE` — transpose bits inside 8-byte groups.
- `DELTA16` — unsigned little-endian 16-bit word delta.
- `DELTA32` — unsigned little-endian 32-bit word delta.
- `XOR16` — 16-bit prefix XOR representation.

Selection is therefore:

```text
original
  ├─ LZMA
  ├─ DELTA + LZMA
  ├─ DE2
  └─ representation → DE2
                     ↓
             choose smallest
```

A representation byte is stored inside the DEH1 payload, so decoding is fully lossless. CRC-32 and original length are still checked after inversion.

This is deliberately an experiment, not a claim that already-compressed formats can always be compressed further. JPEG/MP4/ZIP and encrypted/random data should still be expected to reject these representations and fall back to a normal candidate. The benchmark must decide that from measured final sizes.

## Status

The existing baseline claims remain unchanged: 135/135 tests and 25/25 corpus files were passing on the parent `hybrid-v3` build. The adaptive-representation branch adds a new representation module and dedicated round-trip tests; run the full suite locally before merging because this environment cannot execute the repository's Windows/Python benchmark directly.

## Which codec should I use?

On the parent baseline, use `divideencode.v2.hybrid` for general use. The new representation lane is experimental and should be enabled only when benchmarking/researching binary structure.

## Usage

```python
from divideencode.v2.hybrid import compress, decompress

data = open("myfile.bin", "rb").read()
blob, method = compress(data)
restored = decompress(blob)
assert restored == data
```

For the research experiment, force the new lane:

```python
blob, method = compress(
    data,
    try_de2=True,
    try_representations=True,
)
```

The diagnostic method can be `STORED`, `LZMA`, `DELTA+LZMA`, `DE2`, or `REP+DE2`.

## Verification

```bash
python3 -m pytest tests/ -q
python3 dehybrid.py bench samples/
```

The benchmark result, not the size of the intermediate representation, is the criterion for success.
