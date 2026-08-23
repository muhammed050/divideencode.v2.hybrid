"""Experimental bounded-lookahead DE2 parser with live diagnostics."""
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


def _candidates(data, i, window, max_match, max_chain, reps, index):
    """Generate up to max_chain actual same-hash history candidates."""
    n = len(data)
    limit = min(max_match, n - i)
    out = []

    for ri, d in enumerate(reps):
        if d <= 0 or d > i or d > window:
            continue
        l = _match_length(data, i - d, i, limit)
        if l >= MIN_MATCH:
            out.append((l, d, ri))

    if i + MIN_MATCH > n:
        return out

    key = data[i:i + MIN_MATCH]
    positions = index.get(key, ())
    lower = max(0, i - window)
    tried = 0
    # positions is increasing; walk backwards exactly like a hash chain.
    for p in reversed(positions):
        if p >= i:
            continue
        if p < lower:
            break
        d = i - p
        l = _match_length(data, p, i, limit)
        if l >= MIN_MATCH:
            out.append((l, d, -1))
        tried += 1
        if tried >= max_chain:
            break

    seen = set()
    unique = []
    for item in sorted(out, key=lambda x: (-x[0], x[1], x[2])):
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _token_cost(length, distance, rep_index):
    if rep_index >= 0:
        return 3 + max(1, length.bit_length())
    return 8 + max(1, length.bit_length()) + max(1, distance.bit_length())


def _live_line(msg):
    sys.stdout.write("\r" + msg[:180].ljust(180))
    sys.stdout.flush()


def _solve_window(data, start, lookahead, window_size, max_chain, max_match,
                  reps0, reps1, stats, index):
    """Iterative bounded DP for one window; no recursion."""
    end = min(len(data), start + lookahead)
    INF = 10**18
    costs = {}
    choices = {}

    # For this experimental parser we keep the two REP registers fixed for
    # the current window and evaluate all candidate transitions backwards.
    # This is a bounded cost comparison, not yet the final production parser.
    for i in range(end, start - 1, -1):
        if i == end:
            costs[(i, reps0, reps1)] = 0
            continue
        key = (i, reps0, reps1)
        best = 8 + costs.get((i + 1, reps0, reps1), INF)
        choice = (LIT, data[i])
        reps = tuple(x for x in (reps0, reps1) if x)
        candidates = _candidates(data, i, window_size, max_match, max_chain, reps, index)
        stats["candidates"] += len(candidates)
        stats["last_candidates"] = len(candidates)
        for length, dist, ri in candidates:
            stop = min(length, end - i)
            for l in range(MIN_MATCH, stop + 1):
                ni = i + l
                if ri >= 0:
                    nr0, nr1 = (reps1, reps0) if ri == 1 else (reps0, reps1)
                    tail = costs.get((ni, nr0, nr1), INF)
                    cost = _token_cost(l, dist, ri) + tail
                    if cost < best:
                        best, choice = cost, (REP, l, ri)
                else:
                    nr0, nr1 = dist, reps0
                    tail = costs.get((ni, nr0, nr1), INF)
                    cost = _token_cost(l, dist, -1) + tail
                    if cost < best:
                        best, choice = cost, (MATCH, l, dist)
        costs[key] = best
        choices[key] = choice

    key = (start, reps0, reps1)
    stats["last_cost"] = costs.get(key, 0)
    return choices.get(key, (LIT, data[start]))


def tokenize_bounded(data, lookahead=64, window_size=DEFAULT_WINDOW,
                     max_chain=32, max_match=DEFAULT_MAX_MATCH,
                     progress=False, progress_every=4096):
    """Bounded minimum-cost parser with optional live terminal diagnostics."""
    if not isinstance(data, bytes):
        data = bytes(data)
    if lookahead < 1:
        raise ValueError("lookahead must be >= 1")
    n = len(data)
    if n == 0:
        if progress:
            print("[DE2-OPT] empty input")
        return []

    started = time.perf_counter()
    stats = {"candidates": 0, "last_candidates": 0, "last_cost": 0}
    selected = {LIT: 0, MATCH: 0, REP: 0}
    tokens = []
    i = 0
    reps = []
    last_report = -progress_every

    # Real 4-byte hash index. This fixes the previous prototype bug where
    # max_chain meant "scan 32 bytes" instead of "inspect 32 hash matches".
    index = defaultdict(list)
    if n >= MIN_MATCH:
        for p in range(n - MIN_MATCH + 1):
            index[data[p:p + MIN_MATCH]].append(p)

    if progress:
        print(f"[DE2-OPT] start bytes={n:,} lookahead={lookahead} chain={max_chain} indexed={len(index):,} keys")

    while i < n:
        r0 = reps[0] if reps else 0
        r1 = reps[1] if len(reps) > 1 else 0
        tok = _solve_window(data, i, lookahead, window_size, max_chain,
                            max_match, r0, r1, stats, index)
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
            if tok[2] == 1 and len(reps) >= 2:
                reps[0], reps[1] = reps[1], reps[0]
            i += tok[1]

        if progress and (i - last_report >= progress_every or i >= n):
            elapsed = time.perf_counter() - started
            pct = 100.0 * i / n
            name = {LIT: "LIT", MATCH: "MATCH", REP: "REP"}.get(tok[0], str(tok[0]))
            detail = f"len={tok[1]} dist={tok[2]}" if tok[0] != LIT else f"byte=0x{tok[1]:02x}"
            _live_line(
                f"[DE2-OPT] {pct:6.2f}% pos={i:,}/{n:,} "
                f"candidates={stats['last_candidates']} total_candidates={stats['candidates']:,} "
                f"selected={name}({detail}) tokens={len(tokens):,} "
                f"cost={stats['last_cost']} elapsed={elapsed:.2f}s"
            )
            last_report = i

    if progress:
        elapsed = time.perf_counter() - started
        print()
        print(
            f"[DE2-OPT] done tokens={len(tokens):,} "
            f"LIT={selected.get(LIT, 0):,} MATCH={selected.get(MATCH, 0):,} "
            f"REP={selected.get(REP, 0):,} candidates={stats['candidates']:,} "
            f"elapsed={elapsed:.3f}s"
        )
    return tokens


__all__ = ["tokenize_bounded"]
