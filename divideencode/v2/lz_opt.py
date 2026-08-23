"""Fast single-pass bounded DE2 parser laboratory.

Production DE2 remains in lz.py. This module deliberately favors bounded,
predictable work over exhaustive optimal parsing.
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from .lz import LIT, MATCH, REP, MIN_MATCH, DEFAULT_MAX_MATCH, DEFAULT_WINDOW


def _match_length(data, a, b, limit):
    limit = min(limit, len(data) - a, len(data) - b)
    l = 0
    while l < limit and data[a + l] == data[b + l]:
        l += 1
    return l


def _build_index(data):
    index = defaultdict(list)
    for p in range(max(0, len(data) - MIN_MATCH + 1)):
        index[data[p:p + MIN_MATCH]].append(p)
    return index


def _candidates(data, i, window, max_match, max_chain, reps, index):
    n = len(data)
    limit = min(max_match, n - i)
    out = []

    # REP candidates are always cheap: at most two.
    for ri, d in enumerate(reps[:2]):
        if 0 < d <= i and d <= window:
            l = _match_length(data, i - d, i, limit)
            if l >= MIN_MATCH:
                out.append((l, d, ri))

    # Explicit matches: only walk the newest hash-chain entries.
    if i + MIN_MATCH <= n:
        positions = index.get(data[i:i + MIN_MATCH], ())
        lower = max(0, i - window)
        tried = 0
        for p in reversed(positions):
            if p >= i:
                continue
            if p < lower or tried >= max_chain:
                break
            tried += 1
            l = _match_length(data, p, i, limit)
            if l >= MIN_MATCH:
                out.append((l, i - p, -1))

    # Deduplicate and retain only a small useful frontier.
    best = {}
    for l, d, ri in out:
        key = (d, ri)
        if l > best.get(key, 0):
            best[key] = l
    result = [(l, d, ri) for (d, ri), l in best.items()]
    result.sort(key=lambda x: (-x[0], x[1], x[2]))
    return result[:max_chain + 2]


def _score(length, distance, rep_index):
    """Fast proxy cost, intentionally separate from real entropy coding."""
    if rep_index >= 0:
        return 3 + max(1, length.bit_length())
    return 8 + max(1, length.bit_length()) + max(1, distance.bit_length())


def _live_line(msg):
    sys.stdout.write("\r" + msg[:200].ljust(200))
    sys.stdout.flush()


def _choose(data, i, lookahead, window_size, max_chain, max_match,
            reps, index, stats):
    """Single bounded lookahead.

    We do not build a DP tree. Instead, inspect the current position, score
    its candidates, then perform a cheap one-step lookahead at i+1. This keeps
    work approximately O(input * chain * lookahead) with small constants.
    """
    n = len(data)
    current = _candidates(data, i, window_size, max_match, max_chain, reps, index)
    stats["candidates"] += len(current)
    stats["last_candidates"] = len(current)

    best = (8, (LIT, data[i]))
    for length, distance, ri in current:
        length = min(length, lookahead, n - i)
        if length < MIN_MATCH:
            continue
        score = _score(length, distance, ri)
        if score < best[0] or (score == best[0] and length > best[1][1]):
            best = (score, (REP, length, ri) if ri >= 0 else (MATCH, length, distance))

    # One-step lazy decision: only abandon a current match if the next byte
    # has a substantially better match. This is intentionally cheap.
    tok = best[1]
    if tok[0] != LIT and i + 1 + MIN_MATCH <= n:
        nxt = _candidates(data, i + 1, window_size, max_match, max_chain, reps, index)
        stats["candidates"] += len(nxt)
        stats["lookahead_candidates"] = len(nxt)
        if nxt:
            nl, nd, nri = nxt[0]
            if nl >= tok[1] + 2:
                return (LIT, data[i]), 8

    stats["last_cost"] = best[0]
    return tok, best[0]


def tokenize_bounded(data, lookahead=32, window_size=DEFAULT_WINDOW,
                     max_chain=16, max_match=DEFAULT_MAX_MATCH,
                     progress=False, progress_every=4096,
                     beam_width=1):
    """Fast bounded parser with deterministic single-pass selection.

    ``beam_width`` is accepted for API compatibility but intentionally ignored:
    this version is single-path by design and therefore has predictable cost.
    """
    if not isinstance(data, bytes):
        data = bytes(data)
    if lookahead < 1 or max_chain < 1:
        raise ValueError("lookahead and max_chain must be >= 1")
    n = len(data)
    if not n:
        if progress:
            print("[DE2-OPT] empty input")
        return []

    started = time.perf_counter()
    index = _build_index(data)
    stats = {"candidates": 0, "last_candidates": 0,
             "lookahead_candidates": 0, "last_cost": 8}
    selected = {LIT: 0, MATCH: 0, REP: 0}
    tokens = []
    reps = []
    i = 0
    last_report = -progress_every

    if progress:
        print(f"[DE2-OPT] start bytes={n:,} lookahead={lookahead} chain={max_chain} indexed={len(index):,} keys")

    while i < n:
        tok, cost = _choose(data, i, lookahead, window_size, max_chain,
                            max_match, reps, index, stats)
        tokens.append(tok)
        selected[tok[0]] += 1

        if tok[0] == LIT:
            i += 1
        elif tok[0] == MATCH:
            dist = tok[2]
            if dist in reps:
                reps.remove(dist)
            reps.insert(0, dist)
            del reps[2:]
            i += tok[1]
        else:
            # REP0 keeps the current newest distance; REP1 swaps the two.
            if tok[2] == 1 and len(reps) > 1:
                reps[0], reps[1] = reps[1], reps[0]
            i += tok[1]

        if progress and (i - last_report >= progress_every or i >= n):
            elapsed = time.perf_counter() - started
            speed = i / 1024 / elapsed if elapsed else 0.0
            pct = 100.0 * i / n
            name = {LIT: "LIT", MATCH: "MATCH", REP: "REP0" if tok[2] == 0 else "REP1"}[tok[0]] if tok[0] != LIT else "LIT"
            if tok[0] == LIT:
                detail = f"byte=0x{tok[1]:02x}"
            elif tok[0] == MATCH:
                detail = f"len={tok[1]} distance={tok[2]}"
            else:
                detail = f"len={tok[1]} rep_index={tok[2]}"
            _live_line(f"[DE2-OPT] {pct:6.2f}% pos={i:,}/{n:,} candidates={stats['last_candidates']} lookahead_candidates={stats['lookahead_candidates']} total={stats['candidates']:,} selected={name}({detail}) tokens={len(tokens):,} score={cost} speed={speed:,.1f}KiB/s elapsed={elapsed:.2f}s")
            last_report = i

    if progress:
        elapsed = time.perf_counter() - started
        covered = sum(t[1] for t in tokens if t[0] != LIT)
        print()
        print(f"[DE2-OPT] done tokens={len(tokens):,} LIT={selected[LIT]:,} MATCH={selected[MATCH]:,} REP={selected[REP]:,} match_coverage={covered:,} bytes ({100.0 * covered / n:.2f}%) candidates={stats['candidates']:,} elapsed={elapsed:.3f}s speed={n / 1024 / elapsed:,.1f}KiB/s")
    return tokens


__all__ = ["tokenize_bounded"]
