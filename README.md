# DivideEncode

Experimental lossless data-compression library, built to test whether
mathematical transforms (repeated division, delta/quotient-remainder
encoding, pattern detection) can beat or complement conventional
compressors on specific data classes — while never regressing on
general-purpose data.

This package contains **three independent, coexisting codecs**:

- **`divideencode`** (V1 / DE1) — the original adaptive tree search:
  RAW / RLE / Huffman / LZ leaves with DELTA / DIVIDE / DICT transform
  children, picking whichever produces the smallest total size.
- **`divideencode.v2`** (V2 / DE2) — a from-scratch redesign: modern
  hash-chain LZ77 (lazy matching, rep-offsets) with **separated
  literal/length/distance streams**, each entropy-coded with canonical
  Huffman, plus lightweight numeric pre-transforms (delta, byte-plane
  split, struct pack) chosen by cheap upfront classification instead of
  exhaustive search.

- **`divideencode.v2.hybrid`** (HYBRID / DEH) — **the recommended
  codec for general use.** A practical adaptive system that measures
  `lzma` (stdlib, C-backed, fast and strong on general data),
  DELTA+`lzma`, and DE2 per file, and keeps whichever is smallest —
  always falling back to STORED so output never balloons on
  incompressible input. See rationale in `divideencode/v2/hybrid.py`
  and measured numbers in `benchmarks/results/hybrid_bench.md`.

V2/Hybrid are faster and smaller than V1 on essentially the whole
benchmark corpus. **Hybrid is the recommended entry point** — it beats
both LZMA-alone and DE2-alone on the corpus total (see table below).
V1 is kept intact and independently importable for comparison/
regression purposes.

## Status (this build)

- **135/135 unit tests passing** (round-trip, edge cases, corruption
  detection, fuzzing, tokenizer/codec/pipeline tests for V2, plus a new
  dedicated suite for the hybrid codec).
- **25/25 benchmark corpus files verified byte-for-byte lossless**
  (`data == decompress(compress(data))`, cross-checked with SHA-256),
  measured directly on this build — see `benchmarks/results/` for the
  full numbers and `python3 verify.py` / `python3 dehybrid.py bench`
  below for a fresh run.
- Two real bugs were found and fixed while assembling this build:
  1. `v2/preproc.py:classify()` returned an incomplete dict for empty
     (`b""`) input, causing a `KeyError` in `plan_candidates()`. Fixed
     by returning full neutral defaults for the empty case.
  2. First hybrid draft gated the DE2 candidate behind a heuristic that
     missed `random_prng.bin` (DE2 alone: 384 B; gated hybrid picked
     LZMA at 1,200 B — a real regression). Fixed by always trying DE2
     within a size budget instead of pre-filtering by heuristic.
  Both are described in code comments at the point of the fix.

## Which codec should I use?

**Use `divideencode.v2.hybrid` unless you have a specific reason not
to.** It is strictly the strongest and most robust option measured in
this build:

| Codec | Corpus ratio | Speed | Notes |
|---|---|---|---|
| `divideencode` (V1) | 0.3639 | slow (pure Python search tree) | kept for comparison only |
| `divideencode.v2` (DE2) | 0.3335 | fast-ish, pure Python | wins on structured numeric binary |
| `lzma` alone (no DivideEncode logic) | 0.3150 | fast (C) | strong general baseline |
| **`divideencode.v2.hybrid`** | **0.3043** | **fast (C-backed + selective DE2)** | **best of all three, always** |

## Install

No external dependencies for the core library (`divideencode` and
`divideencode.v2` use only the Python standard library). Benchmarks
optionally compare against `zlib`/`gzip` (stdlib) and, if installed,
`brotli`, `zstandard`, and `lzma` (also stdlib on most platforms).

```bash
pip install -r requirements.txt   # only needed for benchmarks
```

## Usage

### Python API

```python
# HYBRID (recommended) -- strongest, fastest, works well on any file type
from divideencode.v2.hybrid import compress, decompress

data = open("myfile.bin", "rb").read()
blob, method = compress(data)   # method is diagnostic: "LZMA"/"DELTA+LZMA"/"DE2"/"STORED"
restored = decompress(blob)
assert restored == data

# V2 pure DivideEncode codec (no LZMA backend)
from divideencode.v2 import compress as de2_compress, decompress as de2_decompress

# V1 (original research baseline, for comparison)
from divideencode import compress as compress_v1, decompress as decompress_v1
```

### CLI

**Recommended — the hybrid CLI:**

```bash
python3 dehybrid.py compress   input.txt output.deh
python3 dehybrid.py decompress output.deh restored.txt
python3 dehybrid.py bench      samples/            # or any file/directory
```

**Original V1-only CLI** (kept for comparison/regression use):

```bash
python -m divideencode.cli compress input.txt output.de
python -m divideencode.cli decompress output.de restored.txt
```

### Verify this build yourself

```bash
python3 verify.py               # V2 pure codec, all samples, SHA-256 checked
python3 dehybrid.py bench samples/   # hybrid codec, all samples, with zlib/lzma comparison
python3 -m pytest tests/ -q     # full test suite (135 tests)
```

## What actually works well

Honest summary based on measured results (not marketing):

| Data class | Verdict |
|---|---|
| Regular numeric binary (counters, sensor arrays, u32/u16 sequences) | **V2 wins**, sometimes beating xz/Brotli |
| Synthetic/structured pseudo-random data | **V2 wins decisively** (delta exposes periodicity) |
| Source code, JSON, HTML, logs | V2 competitive with gzip/deflate, behind Brotli/Zstd/LZMA2 |
| Already-compressed media (PNG/JPG/WebP/ZIP) | No gain from any codec here — correctly falls back to STORED |
| True cryptographically random data | No gain (expected; this is the correct, honest result) |

## What's *not* included

To keep this build clean and reproducible, the following were
deliberately left out of the packaged deliverable (present in the
original research repo's `docs/reports/` if you need the paper trail):
detailed audit logs (`ARCHITECTURE_AUDIT.md`, `BENCHMARK_AUDIT.md`,
etc.), Windows-specific working-copy paths, and duplicate/legacy copies
of this same package that existed in the source repository.

## Roadmap (evidence-based, from internal design notes)

1. Optional `zstandard`/`brotli` backends in `hybrid.py` when installed
   (both already listed in `requirements.txt`) — likely a further ratio
   win on the general-text lane; not wired in yet because this build's
   numbers are only claimed for what was actually measured (stdlib
   `lzma` only, per dd.txt's "never invent numbers" rule).
2. Optimal/near-optimal LZ parsing in DE2's own LZ stage (current
   parser is lazy-greedy) — would help the DE2-wins lane specifically.
3. Context modeling beyond order-0 for DE2's entropy stage.
4. Revisit rANS/FSE only if the matcher-side gains plateau (currently
   gated out by evidence — literal stream is already Huffman-coded and
   projected gains were low-single-digit %).

## License

Not specified in the source repository — add one before distributing.
