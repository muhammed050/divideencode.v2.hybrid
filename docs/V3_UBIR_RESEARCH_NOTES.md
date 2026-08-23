# V3 UBIR — Research Notes & Results

## Status

Experimental branch: `experiment/v3-universal-binary-ir-final`

UBIR is a reversible intermediate representation for structured JSON and canonical CSV. The selection criterion is the **final DE2 packed size**.

## Frozen research baseline — UBIR V1.1

UBIR V1.1 remains frozen for comparison. `json_large.json`: **148,990 B** final DE2. `json_small.json`: **5,292 B**.

## V1.3AB result

V1.3AB combines compact JSON punctuation opcodes with compact `true`/`false`/`null` opcodes.

| File | V1.1 | V1.3AB | Improvement |
|---|---:|---:|---:|
| `json_small.json` | 5,292 B | **5,184 B** | -108 B (-2.04%) |
| `json_large.json` | 148,990 B | **144,581 B** | **-4,409 B (-2.96%)** |

For `json_large.json`, V1.3AB reduced the IR from **1,192,315 B** to **946,246 B** while also reducing final DE2 to 144,581 B. V1.3AB is therefore the current experimental winner, while V1.1 remains the frozen research baseline.

## RAW analysis after V1.3AB

`json_large.json` V1.3AB IR accounting:

- raw_literals: **490,734 B (51.86%)**, 143,999 tokens
- dictionary_refs: **203,020 B (21.46%)**, 95,930 refs
- punctuation: **180,001 B (19.02%)**, 180,001 tokens
- integers: **39,744 B (4.20%)**, 12,000 tokens
- dictionary_entries: **35,354 B (3.74%)**, 2,371 entries
- compact_literals: **12,000 B (1.27%)**, 12,000 tokens
- literal_strings: **1,125 B (0.12%)**, 70 tokens

Further RAW classification found the remaining non-structural RAW to be:

- whitespace: **131,999 tokens**, 131,999 payload bytes, 263,998 framed bytes
- non-integer numbers: **12,000 tokens**, 70,737 payload bytes, 82,737 framed bytes

This identifies whitespace and non-integer numeric representation as the next research targets.

## V1.3CW — whitespace-run candidate

V1.3CW is an isolated experiment layered on V1.3AB. It encodes consecutive whitespace tokens of length >= 2 using a run opcode, run length, and either a repeated-byte pattern or an explicit byte pattern. It preserves byte-exact reconstruction and is judged only by final DE2 size.

Files added:

```text
 divideencode/v3/ubir_v13cw.py
 benchmarks/v3_ubir_v13cw.py
```

The candidate is **not promoted or frozen** until benchmark results confirm a final-DE2 win on the corpus. If whitespace runs do not improve final DE2, the candidate should be rejected and research should move to the 12,000 non-integer numeric tokens.

## Research rules

1. Every candidate must pass `decode(encode(data)) == data`.
2. Final DE2 size, not IR size, decides compression quality.
3. V1.1 remains the frozen baseline; V1.3AB is the current experimental winner.
4. New candidates must be tested on both JSON files and then the wider corpus before promotion.
5. Never remove the direct DE2 fallback merely because an IR is smaller.
