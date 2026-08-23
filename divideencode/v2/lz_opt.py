"""Fast experimental bounded-lookahead DE2 parser.

This is a parser laboratory only; production DE2 remains in lz.py.
The implementation uses a cheap beam search rather than recursive DP so
large inputs cannot explode in Python runtime or recursion depth.
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
    for ri, d in enumerate(reps):
        if 0 < d <= i and d <= window:
            l = _match_length(data, i - d, i, limit)
            if l >= MIN_MATCH:
                out.append((l, d, ri))
    if i + MIN_MATCH <= n:
        positions = index.get(data[i:i + MIN_MATCH], ())
        lower = max(0, i - window)
        for p in reversed(positions):
            if p >= i:
                continue
            if p < lower:
                break
            l = _match_length(data, p, i, limit)
            if l >= MIN_MATCH:
                out.append((l, i - p, -1))
            if len(out) >= max_chain + len(reps):
                break
    seen = set()
    result = []
    for c in sorted(out, key=lambda x: (-x[0], x[1], x[2])):
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _token_cost(length, distance, rep_index):
    # Conservative proxy: literals cost 8 bits; matches pay length/distance
    # payload costs. The real codec's Huffman cost is measured separately.
    if rep_index >= 0:
        return 3 + max(1, length.bit_length())
    return 8 + max(1, length.bit_length()) + max(1, distance.bit_length())


def _live_line(msg):
    sys.stdout.write("\r" + msg[:180].ljust(180))
    sys.stdout.flush()


def _best_token(data, i, lookahead, window_size, max_chain, max_match,
                reps, index, beam_width, stats):
    """Fast bounded search: keep only the best few partial paths."""
    n = len(data)
    end = min(n, i + lookahead)
    # State: (estimated cost, position, reps_tuple, first_token)
    states = [(0, i, tuple(reps[:2]), None)]

    for depth in range(lookahead):
        next_states = []
        for cost, pos, rs, first in states:
            if pos >= end:
                next_states.append((cost, pos, rs, first))
                continue
            lit = (LIT, data[pos])
            next_states.append((cost + 8, pos + 1, rs, first or lit))
            candidates = _candidates(data, pos, window_size, max_match,
                                     max_chain, rs, index)
            stats["candidates"] += len(candidates)
            stats["last_candidates"] = len(candidates)
            # Only evaluate the most useful lengths; testing every prefix
            # length is where the old prototype became quadratic.
            lengths = set()
            for length, dist, ri in candidates:
                lengths.add(min(length, end - pos))
                if length > MIN_MATCH + 8:
                    lengths.add(MIN_MATCH + 8)
                if length > MIN_MATCH:
                    lengths.add(length // 2)
            for length, dist, ri in candidates:
                for l in sorted(lengths, reverse=True):
                    if l < MIN_MATCH or l > min(length, end - pos):
                        continue
                    ni = pos + l
                    if ri >= 0:
                        nr = list(rs)
                        if ri == 1 and len(nr) > 1:
                            nr[0], nr[1] = nr[1], nr[0]
                        next_states.append((cost + _token_cost(l, dist, ri), ni,
                                            tuple(nr[:2]), first or (REP, l, ri)))
                    else:
                        nr = (dist, rs[0] if rs else 0)
                        next_states.append((cost + _token_cost(l, dist, -1), ni,
                                            nr[:2], first or (MATCH, l, dist)))
        if not next_states:
            break
        # Deduplicate by future position + REP state, retain lowest cost.
        best = {}
        for state in next_states:
            key = (state[1], state[2])
            old = best.get(key)
            if old is None or state[0] < old[0]:
                best[key] = state
        states = sorted(best.values(), key=lambda x: x[0])[:beam_width]
        if states and states[0][1] >= end:
            break

    winner = min(states, key=lambda x: x[0])
    stats["last_cost"] = winner[0]
    return winner[3] or (LIT, data[i])


def tokenize_bounded(data, lookahead=32, window_size=DEFAULT_WINDOW,
                     max_chain=16, max_match=DEFAULT_MAX_MATCH,
                     progress=False, progress_every=4096,
                     beam_width=8):
    """Fast bounded parser with live diagnostics and hard bounded search."""
    if not isinstance(data, bytes):
        data = bytes(data)
    if lookahead < 1 or beam_width < 1 or max_chain < 1:
        raise ValueError("lookahead, beam_width and max_chain must be >= 1")
    n = len(data)
    if not n:
        if progress:
            print("[DE2-OPT] empty input")
        return []

    started = time.perf_counter()
    index = _build_index(data)
    stats = {"candidates": 0, "last_candidates": 0, "last_cost": 0}
    selected = {LIT: 0, MATCH: 0, REP: 0}
    tokens = []
    reps = []
    i = 0
    last_report = -progress_every

    if progress:
        print(f"[DE2-OPT] start bytes={n:,} lookahead={lookahead} chain={max_chain} beam={beam_width} indexed={len(index):,} keys")

    while i < n:
        tok = _best_token(data, i, lookahead, window_size, max_chain,
                          max_match, reps, index, beam_width, stats)
        tokens.append(tok)
        selected[tok[0]] = selected.get(tok[0], 0) + 1
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
            if tok[2] == 1 and len(reps) > 1:
                reps[0], reps[1] = reps[1], reps[0]
            i += tok[1]

        if progress and (i - last_report >= progress_every or i >= n):
            elapsed = time.perf_counter() - started
            speed = i / 1024 / elapsed if elapsed else 0
            pct = 100 * i / n
            name = {LIT: "LIT", MATCH: "MATCH", REP: "REP"}[tok[0]]
            detail = f"len={tok[1]} dist={tok[2]}" if tok[0] != LIT else f"byte=0x{tok[1]:02x}"
            _live_line(f"[DE2-OPT] {pct:6.2f}% pos={i:,}/{n:,} candidates={stats['last_candidates']} total={stats['candidates']:,} selected={name}({detail}) tokens={len(tokens):,} cost={stats['last_cost']} speed={speed:,.1f}KiB/s elapsed={elapsed:.2f}s")
            last_report = i

    if progress:
        elapsed = time.perf_counter() - started
        print()
        print(f"[DE2-OPT] done tokens={len(tokens):,} LIT={selected[LIT]:,} MATCH={selected[MATCH]:,} REP={selected[REP]:,} candidates={stats['candidates']:,} elapsed={elapsed:.3f}s")
    return tokens


__all__ = ["tokenize_bounded"]
