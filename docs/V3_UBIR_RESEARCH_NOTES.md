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

### JSON -> UBIR

- Lexical tokenization while preserving the original byte stream.
- Dictionary for repeated JSON strings.
- Integer Delta coding.
- ZigZag mapping for signed integer deltas.
- Varint encoding.
- Exact byte reconstruction is required.

### CSV -> UBIR

- Column-oriented representation.
- Numeric columns use Delta + ZigZag + Varint.
- Text columns use dictionaries for repeated values.
- Transform is gated by canonical byte-exact reconstruction.
- If UBIR does not produce a smaller final DE2 stream, direct DE2 remains selected.

## Test status

Latest local test result:

```text
5 passed in 0.04s
```

The test suite covers JSON roundtrip, final-DE2 selection criterion, CSV roundtrip, canonical CSV gating, and rejection of unsupported non-structured candidates.

## Main benchmark result

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

### json_large.json

```text
source        = 1,206,806 B
direct DE2    =   195,944 B
UBIR + DE2    =   150,545 B
improvement   =   -45,399 B (-23.17%)
```

This is the key experimental result. UBIR itself is not smaller than the source, but it produces a representation that DE2 compresses substantially better.

### json_small.json

```text
direct DE2    = 5,451 B
UBIR + DE2    = 5,349 B
improvement   = -102 B (-1.87%)
```

The small gain confirms that UBIR must remain optional and final-size-selected.

### data.csv

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

## Current limitations

1. JSON is currently represented primarily as a lexical token stream. Punctuation and token metadata still have overhead.
2. The current UBIR intermediate representation can be larger than the original JSON, even when its final DE2 result is much smaller.
3. CSV transforms have not yet demonstrated a gain on the current benchmark corpus.
4. No claim is made that this design is free of patent coverage; it is an independent research implementation.

## Next research direction: Binary JSON

The next major step is to evolve JSON from a lexical token IR into a **typed binary JSON representation**.

Target structure:

```text
JSON
  -> typed binary tree / binary records
  -> DE2
```

Potential primitive tags:

- OBJECT
- ARRAY
- KEY_REF
- STRING
- INTEGER
- FLOAT
- TRUE
- FALSE
- NULL

Repeated object keys should use a dedicated key dictionary. Integers should support adaptive absolute/Delta coding followed by ZigZag + Varint where beneficial.

### Exactness requirement

Binary JSON must remain byte-exact for the current project requirement. Therefore semantic equivalence alone is insufficient: formatting whitespace, original string lexical forms, and number lexical forms must be preserved or represented by an exact-mode side channel.

The intended architecture is:

```text
Direct DE2
      |
      +-- UBIR V1 lexical
      |
      +-- Binary JSON V2
      |
      +-- (future structured transforms)
      |
      +--> DE2 each candidate
               |
               +--> select smallest final stream
```

No transform should be forced when it makes the final DE2 result worse.

## Research principle

Do not add transforms merely because they sound useful. Every new representation must be evaluated by:

1. byte-exact roundtrip,
2. final DE2 size,
3. encoding/decoding cost,
4. behavior across the full corpus,
5. fallback behavior when the transform is not beneficial.
