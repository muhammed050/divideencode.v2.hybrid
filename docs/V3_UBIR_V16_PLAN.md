# UBIR V1.6 — DE2-Oriented Typed Lanes

## Hypothesis
V1.3AB is the current winner because its representation is more favorable to DE2, not merely because its raw IR is smaller. V1.6 therefore changes the physical layout without changing the successful semantic transform.

## Layout
- 3-bit packed token-class stream instead of one tag byte per token.
- Six homogeneous payload lanes: punctuation, dictionary references, literal strings, integers, raw tokens, constants.
- The packed class stream reconstructs the original token order exactly.
- Constants `true/false/null` use a 2-bit side stream.

## Why this experiment
The goal is to make DE2 see longer homogeneous regions and simpler local alphabets. We explicitly do **not** add another dictionary or try to compress raw content ourselves.

## Decision rule
Only final `DE2.compress(UBIR)` size decides whether V1.6 is a win. IR size is diagnostic only.

## Baseline
V1.3AB:
- `json_small.json`: 5,184 B
- `json_large.json`: 144,581 B

V1.1 remains frozen at 5,292 B / 148,990 B.

## Required validation
1. `decode(encode(data)) == data` for both corpus files.
2. Compare final DE2 size against V1.3AB.
3. Record IR size and encode/DE2 time.
4. Reject V1.6 if either corpus regresses materially; do not replace the V1.3AB winner automatically.
