# Universal Binary IR

Universal Binary IR (UBIR2) is a representation compiler for DE2.

## Contract

The input is arbitrary bytes. UBIR2 may make the intermediate representation
larger; that is intentional. The only compression objective is the size of the
final DE2 stream produced from the representation.

`DIRECT` is always available as a fallback.

## Pipeline

```text
any file
  -> bytes
  -> Universal IR planner
  -> reversible IR program
  -> DE2
  -> choose smallest verified DE2 stream
```

A program is a sequence of reversible instructions. Current instruction families
include byte delta/XOR, word delta/XOR/swap, nibble and bit planes, transposes,
strides, run-length records, and byte-lane separation.

Programs may be composed, for example:

```text
DELTA32 -> BYTE_LANES4 -> DE2
XOR8    -> STRIDE4     -> DE2
NIBBLE  -> DELTA8      -> DE2
```

The planner only limits the search space. It never declares a winner using the
IR size or a heuristic score. Every selected program is compiled and passed to
DE2; the final DE2 byte count decides the winner.

## Reversibility

Every instruction is invertible. The test suite verifies individual operations,
composed pipelines, arbitrary bytes, and the complete UBIR2 container.

The UBIR2 container stores the selected pipeline descriptor outside the DE2
payload. On decode, the DE2 payload is decoded first and the pipeline is then
reversed to reconstruct the exact original bytes.

## Extending the language

To add an instruction:

1. Add an opcode to `divideencode/universal_compiler.py`.
2. Implement its forward and inverse operation.
3. Add it to candidate generation if it should be searched automatically.
4. Add a single-op roundtrip test and at least one composed-pipeline test.
5. Measure final DE2 size; never accept a transform because its IR is smaller.
