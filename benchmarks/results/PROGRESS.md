# PHASE 12 (interim) — Competitive position after v3 core work

Branch `v3-strong-core` · corpus: benchmarks/corpus (13 files, 10.3 MB)
Raw data: benchmarks/results/{baseline,v3-lz-core,v3-decoder,v3-lzv2}.json

## Corpus totals (all 13 files, BALANCED unless noted)

| impl | total comp | avg saved | geo-mean ratio |
|---|---:|---:|---:|
| de2 (BALANCED) | 1,465,222 | 87.56% | 7.72% |
| de2 (MAX)      | 1,401,426 | —       | —       |
| zlib_9         | 2,014,820 | 82.90% | 9.45% |
| zstd_19        | 1,369,170 | 88.38% | 5.30% |
| brotli_q11     | 1,597,915 | 86.44% | 4.70% |
| lzma_p6e       | 1,182,780 | 89.96% | 5.65% |

Honest reading:
- DE2/BALANCED now beats zlib_9 on BOTH total size and geomean ratio, and
  beats brotli_q11 on total size (loses its geomean: brotli's static
  dictionary wins small text).
- MAX closes to within 2.4% of zstd_19 totals at ~0.37 MB/s encode
  (offline profile).
- lzma_p6e remains ahead by ~19% on totals; gap driven by text files.

## Per-stage measured gains (this branch)

| stage | corpus delta | speed delta | commit |
|---|---|---|---|
| v3 LZ matcher | -1.4..-4.7% per LZ file | encode par, decode +30-47% later | Phase 2 |
| decoder rewrite | 0 (format same) | decode +30-47% MB/s | decoder commit |
| LZ frame v2 distances | **-4.02%** total | par (dsym Huffman smaller) | LZv2 |
| cost-aware distance bias | -0.23% total | par | dist-bias |

Decode throughput now: natural.txt 5.2 MB/s, binary 11.4, repeat.txt 845,
vs baseline 3.6 / 7.7 / 300.

## Known gaps & next levers (priority order)

1. Merged literal/length token stream (deflate-style single alphabet):
   projected ~-6..-10% on text; removes the ll-stream waste (~87% zero
   symbols on natural.txt). Requires >255-symbol entropy tables ->
   table format v2 inside FLAG_LZ_V2 frames.
2. Small-file footprint: brotli/zstd static dictionaries dominate
   <32 KiB text; classical mitigation = optional built-in dictionary
   mined offline (deterministic, no ML).
3. Encode throughput beyond FAST: multiprocessing over independent
   blocks (Phase 9) or native accelerator (Phase 11, gated).
