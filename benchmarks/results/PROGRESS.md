# PHASE 12 (interim) — Competitive position after v3 core work

Branch `v3-strong-core` · corpus: benchmarks/corpus (13 files, 10.3 MB)

## Corpus totals

| impl | total comp | avg saved | geo-mean ratio |
|---|---:|---:|---:|
| de2 (BALANCED) | 1,465,222 | 87.56% | 7.72% |
| de2 (MAX)      | 1,401,426 | — | — |
| zlib_9         | 2,014,820 | 82.90% | 9.45% |
| zstd_19        | 1,369,170 | 88.38% | 5.30% |
| brotli_q11     | 1,597,915 | 86.44% | 4.70% |
| lzma_p6e       | 1,182,780 | 89.96% | 5.65% |

## Merged-token experiment — REJECTED

The DE3-derived merged token coder was tested against the exact same V3
matcher/token sequence. Full corpus result:

- existing V3 frame: **3,542,758 B**
- merged coder: **3,938,955 B**
- regression: **+396,197 B / +11.18%**
- 87/87 repository tests remain green.

The experiment remains research-only. Production V3 frame is unchanged.

## Next optimization matrix

`benchmarks/v3_next.py` measures three low-risk levers before any format
change:

1. larger independent block sizes (256 KiB → 512 KiB → 1 MiB → 4 MiB);
2. BALANCED vs MAX matcher at the full DE2 container level;
3. shared entropy table potential for LL+ML streams without changing the
   production frame.

No production defaults are changed until the measured result is positive.

## Known gaps

- The main remaining ratio gap is text: lzma_p6e remains ~19% ahead on total
  corpus bytes, while MAX DE2 is within ~2.4% of zstd_19.
- Small text still benefits from the static dictionaries used by brotli/zstd.
- Encode throughput remains far behind native compressors; optimization is
  gated behind ratio/correctness wins.
