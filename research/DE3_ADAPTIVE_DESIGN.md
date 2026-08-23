# DE3 Adaptive Representation Research

## Goal

Explore a new DivideEncode representation-selection architecture without changing the production `v3-strong-core` branch.

The research idea is a bounded search over reversible data representations on independent blocks. The selector scores the transformed payload together with explicit representation metadata and chooses the lowest measured cost.

## Current search space

- raw
- delta from the previous byte
- XOR with the previous byte
- byte-oriented run encoding
- bit-plane transpose
- packed run/literal representation

These are implemented from scratch in `divideencode/v3/adaptive.py`.

## Composition

The search is a small deterministic beam search. It can discover chains such as:

`delta -> rle`

or

`bitplane -> rle`

without enumerating an unbounded number of transformations.

## Important boundary

This branch is research-only. It does not replace the existing V3 production frame or matcher.

The current scorer uses zlib level 1 only as a cheap search oracle. It is **not** part of the proposed production codec. The next implementation step is to replace that oracle with the DivideEncode entropy coder and make every selected transformation fully reversible in the DE3 container.

## IP / originality

The code in this branch is newly written for this project and does not copy implementation code from Zstd, Brotli, LZMA, bzip2, or DE3 research branches.

The individual mathematical ideas used here are general compression techniques. This repository does not make a legal guarantee that an entire compression product is free of every possible patent claim. Before commercial release, a proper patent/legal review is still required.
