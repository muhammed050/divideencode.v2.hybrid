# V3 UBIR — Research Notes & Results

## Status

Experimental branch: `experiment/v3-universal-binary-ir-final`

UBIR (Universal Binary IR) is a reversible intermediate representation for structured JSON and canonical CSV. It is not intended to win by making the IR bytes smaller than the source; the selection criterion is the **final DE2 packed size**.

Pipeline:

```text
structured source -> UBIR -> DE2
```

The system keeps a direct DE2 path and selects UBIR only when the final packed result is smaller.

## FROZEN RESEARCH BASELINE — UBIR V1.1

UBIR V1.1 is now the **frozen research baseline** for subsequent V3 JSON experiments. It is not automatically promoted to production; future candidates must beat it while preserving byte-exact roundtrip and acceptable runtime.

### Frozen final-DE2 targets

| File | Direct DE2 | UBIR V1.1 | Improvement vs direct | Improvement vs V1 |
|---|---:|---:|---:|---:|
| `json_small.json` | 5,451 B | **5,292 B** | -159 B (-2.92%) | -57 B (-1.07%) |
| `json_large.json` | 195,944 B | **148,990 B** | -46,954 B (-23.96%) | -1,555 B (-1.03%) |

The primary benchmark target is therefore:

```text
json_large.json: 148,990 B
```

A candidate that reaches 148,990 B but does not beat it is **not considered a new winner**. The next target is `< 148,990 B`, with an initial research goal of `< 145,000 B`.

### Frozen baseline verification

`benchmarks/v3_ubir_baseline_v11.py` verifies both frozen final-DE2 sizes and performs byte-exact roundtrip before accepting the baseline.

## Design implemented

### JSON -> UBIR V1

- Lexical tokenization while preserving the original byte stream.
- Dictionary for repeated JSON strings.
- Integer Delta coding.
- ZigZag mapping for signed integer deltas.
- Varint encoding.
- Exact byte reconstruction is required.

### CSV -> UBIR V1

- Column-oriented representation.
- Numeric columns use Delta + ZigZag + Varint.
- Text columns use dictionaries for repeated values.
- Transform is gated by canonical byte-exact reconstruction.
- If UBIR does not produce a smaller final DE2 stream, direct DE2 remains selected.

## Test status

Latest UBIR test result:

```text
5 passed in 0.04s
```

The test suite covers JSON roundtrip, final-DE2 selection criterion, CSV roundtrip, canonical CSV gating, and rejection of unsupported non-structured candidates.

## Main UBIR benchmark result

Corpus benchmark on the V3 UBIR experiment:

```text
TOTAL direct=1,203,967 B
UBIR  =1,158,466 B
delta = -45,501 B (-3.78%)
wins  = 2
```

Only two corpus files selected UBIR:

- `json_large.json`
- `json_small.json`

`data.csv` did not improve and correctly stayed on direct DE2.

### json_large.json — UBIR V1

```text
source        = 1,206,806 B
direct DE2    =   195,944 B
UBIR + DE2    =   150,545 B
improvement   =   -45,399 B (-23.17%)
```

### json_small.json — UBIR V1

```text
direct DE2    = 5,451 B
UBIR + DE2    = 5,349 B
improvement   = -102 B (-1.87%)
```

### data.csv — UBIR V1

```text
direct DE2 = 242,500 B
UBIR       = 242,500 B
```

No gain, so direct DE2 is selected.

## JSON ablation result

Controlled ablation on `json_large.json`:

| Representation | IR size | Final DE2 | Change vs direct |
|---|---:|---:|---:|
| Direct JSON | 1,206,806 B source | 195,944 B | baseline |
| Dictionary only | 1,388,060 B | 181,947 B | -13,997 B (-7.14%) |
| Delta only | 2,045,929 B | 182,104 B | -13,840 B (-7.06%) |
| Dictionary + Delta | 1,372,316 B | **150,545 B** | **-45,399 B (-23.17%)** |

### Interpretation

Dictionary and Delta each provide about a 7% improvement independently, but their combination provides a much larger 23.17% improvement. This indicates a strong interaction effect between repeated-string dictionary references and integer Delta coding.

The important architectural conclusion is:

> UBIR is valuable primarily as a **representation transform before entropy coding**, not necessarily as a standalone compression format.

## Binary JSON V2 experiment

A typed-tree Binary JSON V2 prototype was evaluated as a separate research candidate.

| File | Direct DE2 | Binary JSON V2 | Change vs direct |
|---|---:|---:|---:|
| `json_small.json` | 5,451 B | 6,241 B | +790 B (+14.49%) |
| `json_large.json` | 195,944 B | 206,678 B | +10,734 B (+5.48%) |

Conclusion: **Binary JSON V2 was rejected as a production candidate.**

## Compact Statistical JSON IR experiment

| File | Source | Direct DE2 | Compact IR | Final DE2 | Change vs direct |
|---|---:|---:|---:|---:|---:|
| `json_small.json` | 29,780 B | 5,451 B | 27,095 B | 6,267 B | +816 B (+14.97%) |
| `json_large.json` | 1,206,806 B | 195,944 B | 958,081 B | **172,801 B** | **-23,143 B (-11.81%)** |

Conclusion: **Compact Statistical JSON IR is a partial success but does not beat UBIR V1.1.**

## Hybrid Statistical JSON IR experiment

A separated structure/text + integer-stream prototype was also tested:

| File | Direct DE2 | UBIR V1 | Hybrid IR | Change vs direct |
|---|---:|---:|---:|---:|
| `json_small.json` | 5,451 B | 5,349 B | 6,731 B | +1,280 B (+23.48%) |
| `json_large.json` | 195,944 B | 150,545 B | **190,971 B** | -4,973 B (-2.54%) |

Conclusion: the separated-stream design was rejected. It introduced too much intermediate/structural overhead and did not approach UBIR V1.

## UBIR V1.1 result

UBIR V1.1 keeps the successful Dictionary + Delta architecture while reducing representation overhead.

Observed benchmark:

```text
json_small.json
Direct   = 5,451 B
UBIR V1  = 5,349 B
UBIR V1.1= 5,292 B

json_large.json
Direct   = 195,944 B
UBIR V1  = 150,545 B
UBIR V1.1= 148,990 B
```

For `json_large.json`, V1.1 improves over V1 by **1,555 B (1.03%)** and over Direct DE2 by **46,954 B (23.96%)**.

The V1.1 intermediate representation is also smaller than V1 on the large file:

```text
V1 IR   = 1,372,316 B
V1.1 IR = 1,192,315 B
```

## Current ranking on json_large.json

```text
Direct DE2              195,944 B
Hybrid Statistical IR   190,971 B
Compact Statistical IR  172,801 B
UBIR V1                 150,545 B
UBIR V1.1               148,990 B  <-- FROZEN WINNER
```

## Research rules from this point

1. UBIR V1.1 is the frozen baseline.
2. Every new candidate must pass `decode(encode(data)) == data`.
3. Final DE2 size, not intermediate IR size, decides compression quality.
4. A candidate must be **strictly smaller than 148,990 B** on `json_large.json` to become the new winner.
5. Candidates must also be evaluated on `json_small.json` and the wider corpus before any production promotion.
6. No experimental candidate may silently replace the direct DE2 fallback.
7. Encoding/decoding cost must be reported alongside size.

## Next research target

The next candidate is **UBIR V1.2**, focused on micro-optimizations to the V1.1 representation rather than another wholesale JSON format redesign.

Initial target:

```text
< 145,000 B on json_large.json
```

Longer-term target:

```text
< 140,000 B
```

## Exactness requirement

All structured transforms must preserve:

```text
decode(encode(data)) == data
```

Semantic equivalence alone is insufficient. Formatting whitespace, original string lexical forms, number lexical forms, and other bytes needed to reconstruct the original file must be preserved or represented by an exact-mode side channel.

## Research principle

Do not add transforms merely because they sound useful. Every new representation must be evaluated by:

1. byte-exact roundtrip,
2. final DE2 size,
3. encoding/decoding cost,
4. behavior across the full corpus,
5. fallback behavior when the transform is not beneficial.
