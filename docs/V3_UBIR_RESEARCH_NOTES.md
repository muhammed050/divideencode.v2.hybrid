# V3 UBIR — Research Notes & Results

## Status

Experimental branch: `experiment/v3-universal-binary-ir-final`

UBIR (Universal Binary IR) is a reversible intermediate representation for structured JSON and canonical CSV. It is not intended to win by making the IR bytes smaller than the source; the selection criterion is the **final DE2 packed size**.

Pipeline:

```text
structured source -> UBIR -> DE2
```

The system keeps a direct DE2 path and selects UBIR only when the final packed result is smaller.

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

This is the key experimental result. UBIR itself is not smaller than the source, but it produces a representation that DE2 compresses substantially better.

### json_small.json — UBIR V1

```text
direct DE2    = 5,451 B
UBIR + DE2    = 5,349 B
improvement   = -102 B (-1.87%)
```

The small gain confirms that UBIR must remain optional and final-size-selected.

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

A typed-tree Binary JSON V2 prototype was evaluated as a separate research candidate. It represented JSON as typed nodes such as OBJECT, ARRAY, STRING, INTEGER, FLOAT, TRUE/FALSE, NULL and dictionary references.

Results:

| File | Direct DE2 | Binary JSON V2 | Change vs direct |
|---|---:|---:|---:|
| `json_small.json` | 5,451 B | 6,241 B | +790 B (+14.49%) |
| `json_large.json` | 195,944 B | 206,678 B | +10,734 B (+5.48%) |

Conclusion: **Binary JSON V2 was rejected as a production candidate.** The typed-tree representation did not create a DE2-friendly statistical stream and was substantially worse than UBIR V1.

The experiment is useful because it shows that simply making JSON "binary" or semantically typed is not enough. The representation must be optimized for the downstream entropy coder.

## Compact Statistical JSON IR experiment

A second prototype was tested. It reduced lexical overhead and separated structural information, dictionaries and numeric data more aggressively.

Results:

| File | Source | Direct DE2 | Compact IR | Final DE2 | Change vs direct |
|---|---:|---:|---:|---:|---:|
| `json_small.json` | 29,780 B | 5,451 B | 27,095 B | 6,267 B | +816 B (+14.97%) |
| `json_large.json` | 1,206,806 B | 195,944 B | 958,081 B | **172,801 B** | **-23,143 B (-11.81%)** |

Conclusion: **Compact Statistical JSON IR is a partial success but does not beat UBIR V1.** On `json_large.json`, it improves Direct DE2 by 11.81%, but remains 22,256 B larger than the UBIR V1 result of 150,545 B.

An important observation is that the Compact IR is much smaller as an intermediate representation (958,081 B versus UBIR V1's 1,372,316 B), yet its final DE2 result is worse. Therefore intermediate IR size is not a valid optimization target; **final DE2 size remains the governing metric**.

## Current ranking on json_large.json

```text
Direct DE2              195,944 B
Compact Statistical IR  172,801 B   (-11.81%)
UBIR V1                 150,545 B   (-23.17%)  <-- current best
```

## Current limitations

1. JSON UBIR V1 is primarily a lexical token stream and has metadata/punctuation overhead.
2. The current UBIR intermediate representation can be larger than the original JSON, even when its final DE2 result is much smaller.
3. Typed-tree Binary JSON V2 did not improve compression and is not selected.
4. Compact Statistical JSON IR improved Direct DE2 but did not beat UBIR V1.
5. CSV transforms have not yet demonstrated a gain on the current benchmark corpus.
6. No claim is made that this design is free of patent coverage; it is an independent research implementation.

## Next research direction: Hybrid Statistical JSON IR

The next candidate should not be another generic binary tree. The evidence points toward a **hybrid statistical representation** that preserves the successful properties of UBIR V1 while reducing its overhead.

Target architecture:

```text
JSON
  -> key dictionary
  -> string dictionary
  -> structural stream
  -> independent integer streams
  -> adaptive absolute/Delta coding per stream
  -> ZigZag + Varint
  -> DE2
```

The key research questions are:

1. Can integer Delta be applied independently to related numeric streams rather than one global sequence?
2. Can key references and repeated string references be encoded as compact symbol streams?
3. Can structural punctuation be represented implicitly without losing byte-exact reconstruction?
4. Can the exact whitespace and lexical spelling side information remain compressible?
5. Can the hybrid representation beat **150,545 B** on `json_large.json` without harming fallback behavior?

## Exactness requirement

All structured transforms must preserve the project's byte-exact requirement:

```text
 decode(encode(data)) == data
```

Semantic equivalence alone is insufficient. Formatting whitespace, original string lexical forms, number lexical forms, and other bytes needed to reconstruct the original file must be preserved or represented by an exact-mode side channel.

## Selector architecture

No experimental transform should replace the direct path automatically. The intended architecture is:

```text
Direct DE2
      |
      +-- UBIR V1 lexical
      |
      +-- Binary JSON V2 (research / rejected)
      |
      +-- Compact Statistical JSON IR (research)
      |
      +-- Hybrid Statistical JSON IR (next)
      |
      +--> DE2 each candidate
               |
               +--> select smallest final stream
```

A candidate is production-worthy only when it is byte-exact, produces a smaller final DE2 result on relevant data, has acceptable encoding/decoding cost, and safely falls back when it is not beneficial.

## Research principle

Do not add transforms merely because they sound useful. Every new representation must be evaluated by:

1. byte-exact roundtrip,
2. final DE2 size,
3. encoding/decoding cost,
4. behavior across the full corpus,
5. fallback behavior when the transform is not beneficial.
