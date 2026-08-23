# PHASE 0 — Baseline (branch `v3-strong-core`)

Date: 2026-08-23 · Python 3.12.10 · Windows · corpus: `benchmarks/corpus/`
(13 deterministic files, regenerate with `python benchmarks/gen_corpus.py`)
Raw numbers: `benchmarks/results/baseline.json` · rerun:
`python benchmarks/bench.py --name <tag> --reps 2`

## Corpus

| file | bytes | class |
|---|---:|---|
| src_small.c | 13,094 | source code / small |
| src_medium.c | 197,237 | source code / medium |
| json_small.json | 29,780 | JSON / small |
| json_large.json | 1,206,806 | JSON / large |
| page.html | 301,417 | HTML/CSS/JS |
| styles.css | 129,600 | CSS highly repetitive |
| data.csv | 803,287 | CSV |
| app.log | 1,044,041 | logs |
| repeat.txt | 2,867,294 | repetitive text / large |
| natural.txt | 733,209 | natural language text |
| binary.bin | 3,145,728 | structured binary / large |
| random.raw | 262,144 | incompressible |
| compressed.zip | 1,048,576 | already-compressed |

## Baseline results (DE2 default profile: chain=32, lazy=on, 256 KiB blocks)

| impl | total comp bytes | geo-mean ratio | enc MB/s geo | dec MB/s geo |
|---|---:|---:|---:|---:|
| **de2** | 1,246,976 | 0.355 | **0.55** | **6.1** |
| zlib_9 | 1,004,972 | 0.322 | 27.5 | 405 |
| zstd_19 | 830,000 | 0.287 | 2.9 | 1300 |
| brotli_q11 | 789,000 | 0.279 | 0.66 | 420 |
| lzma_p6e | 753,000 | 0.268 | 1.9 | 140 |

(geomean across 12 compressible files incl. random.raw stored; exact values in JSON.)

## Key findings

1. **Encode speed bottleneck**: cProfile on natural.txt — 95% of encode time
   is `lz.encode` (`_find` 1.64 s cum + `_match_length` 0.53 s of 2.86 s
   profiled). Per-position `data[i:i+4]` key slicing allocates a bytes object
   per input position; lazy mode doubles `_find` calls; chains are Python
   lists of ints trimmed by copying.
2. **Decode speed bottleneck**: `entropy.decode_stream` bit-loop 47% +
   `decode_varint` called 164k times (once per token per stream).
3. **Ratio gap**: DE2 loses to plain zlib_9 on most text files
   (app.log 88.79% saved vs 90.61%; natural.txt 77.51% vs 82.88%;
   data.csv 65.40% vs 70.87%). Wins only where its RLE/REP paths dominate
   (styles.css, repeat.txt) and on binary.bin vs zlib (delta transform).
4. random.raw is correctly stored RAW (-0.01% expansion).

## Priorities derived

P1 rewrite LZ matcher: integer rolling-hash keys (no per-position slicing),
deflate-style head/prev chains in preallocated arrays, bounded lazy match,
nice/good-length cutoffs, explicit FAST/BALANCED/MAX levels. Target: ≥10×
encode throughput at equal-or-better ratio.
P2 decoder: batched bit reader fill, inline varint parsing, bulk copies.
P3 ratio: stronger search (MAX level), then token-stream coding improvements.
