# V3 UBIR — Research Notes & Results

## Status
Experimental branch: `experiment/v3-universal-binary-ir-final`

UBIR is a reversible intermediate representation for structured JSON and canonical CSV. Selection is based only on **final DE2 packed size**.

## Frozen baseline
UBIR V1.1 remains frozen: `json_small.json` = **5,292 B**, `json_large.json` = **148,990 B** final DE2.

## Current winner — V1.3AB
V1.3AB combines compact JSON punctuation and compact `true`/`false`/`null` opcodes.

| File | V1.1 | V1.3AB | Improvement |
|---|---:|---:|---:|
| json_small.json | 5,292 | **5,184** | -108 B (-2.04%) |
| json_large.json | 148,990 | **144,581** | **-4,409 B (-2.96%)** |

For `json_large.json`, V1.3AB reduced IR from **1,192,315 B** to **946,246 B**.

## RAW analysis after V1.3AB
`json_large.json` IR accounting:
- raw_literals: **490,734 B (51.86%)**, 143,999 tokens
- dictionary_refs: **203,020 B (21.46%)**, 95,930 refs
- punctuation: **180,001 B (19.02%)**, 180,001 tokens
- integers: **39,744 B (4.20%)**, 12,000 tokens
- dictionary_entries: **35,354 B (3.74%)**, 2,371 entries
- compact_literals: **12,000 B (1.27%)**, 12,000 tokens
- literal_strings: **1,125 B (0.12%)**, 70 tokens

Earlier classification of the remaining non-structural tokens found **131,999 whitespace tokens / 131,999 payload B** and **12,000 non-integer numbers / 70,737 payload B**.

## Rejected candidates
### V1.3CW — whitespace runs
No gain. `json_small.json`: **5,184 B**, `json_large.json`: **144,581 B**; both exactly equal V1.3AB. The candidate is rejected.

### V1.3CF — decimal/scientific numeric transform
The candidate was repaired for byte-exact lexical reconstruction and passed roundtrip, but final DE2 was unchanged: `json_small.json` **5,184 B**, `json_large.json` **144,581 B**. It is rejected because the lexical sidecar removes the expected compression benefit.

## Next research target — RAW content
The next experiment must analyze the **490,734 B raw_literals** rather than adding another small token opcode. We need to split raw content into:
- string lengths and length distribution
- escaped vs unescaped strings
- short/medium/long strings
- key-like vs value-like strings
- repeated prefixes/suffixes
- repeated substrings inside strings
- character/byte frequency and entropy

The purpose is to identify a transform that removes redundancy *inside* raw strings, where V1.3AB currently leaves the largest amount of data.

## Research rules
1. Every candidate must pass `decode(encode(data)) == data`.
2. Final DE2 size, not IR size, decides compression quality.
3. V1.1 remains frozen; V1.3AB remains the current experimental winner.
4. Test both JSON files before wider-corpus testing.
5. Never remove the direct DE2 fallback merely because an IR is smaller.
