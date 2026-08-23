"""Experimental bounded-lookahead DE2 parser with live diagnostics."""
from __future__ import annotations

import sys
import time
from .lz import LIT, MATCH, REP, MIN_MATCH, DEFAULT_MAX_MATCH, DEFAULT_WINDOW


def _match_length(data, a, b, limit):
    n = len(data)
    limit = min(limit, n - a, n - b)
    l = 0
    while l < limit and data[a + l] == data[b + l]:
        l += 1
    return l


def _candidates(data, i, window, max_match, max_chain, reps):
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
    start = max(0, i - window)
    tried = 0
    p = i - MIN_MATCH
    while p >= start and tried < max_chain:
        if data[p:p + MIN_MATCH] == key:
            d = i - p
            l = _match_length(data, p, i, limit)
            if l >= MIN_MATCH:
                out.append((l, d, -1))
        p -= 1
        tried += 1
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


def tokenize_bounded(data, lookahead=64, window_size=DEFAULT_WINDOW,
                     max_chain=32, max_match=DEFAULT_MAX_MATCH,
                     progress=False, progress_every=4096):
    """Bounded minimum-cost parser.

    ``progress=True`` displays current position, candidate count, selected
    token, token count, and elapsed time. Production code is unaffected.
    """
    if not isinstance(data, bytes):
        data = bytes(data)
    if lookahead < 1:
        raise ValueError("lookahead must be >= 1")
    n = len(data)
    if n == 0:
        if progress:
            print("[DE2-OPT] empty input")
        return []

    from functools import lru_cache
    started = time.perf_counter()
    total_candidates = 0
    selected = {LIT: 0, MATCH: 0, REP: 0}
    last_candidates = 0
    last_cost = 0

    def solve(start, reps0, reps1):
        nonlocal total_candidates, last_candidates, last_cost
        end = min(n, start + lookahead)

        @lru_cache(maxsize=None)
        def dp(i, r0, r1):
            nonlocal total_candidates, last_candidates, last_cost
            lit_tail = dp(i + 1, r0, r1)
            best_cost = 8 + lit_tail[0]
            best = ((LIT, data[i]),) + lit_tail[1]
            reps = tuple(x for x in (r0, r1) if x)
            candidates = _candidates(data, i, window_size, max_match, max_chain, reps)
            total_candidates += len(candidates)
            last_candidates = len(candidates)
            for length, dist, ri in candidates:
                stop = min(length, end - i)
                for l in range(MIN_MATCH, stop + 1):
                    ni = i + l
                    if ri >= 0:
                        if ri == 1:
                            nr0, nr1 = r1, r0
                        else:
                            nr0, nr1 = r0, r1
                        tail = dp(ni, nr0, nr1)
                        cost = _token_cost(l, dist, ri) + tail[0]
                        if cost < best_cost:
                            best_cost = cost
                            best = ((REP, l, ri),) + tail[1]
                    else:
                        nr0, nr1 = dist, r0
                        tail = dp(ni, nr0, nr1)
                        cost = _token_cost(l, dist, -1) + tail[0]
                        if cost < best_cost:
                            best_cost = cost
                            best = ((MATCH, l, dist),) + tail[1]
            last_cost = best_cost
            return best_cost, best

        return dp(start, reps0, reps1)[1]

    tokens = []
    i = 0
    reps = []
    last_report = -progress_every
    if progress:
        print(f"[DE2-OPT] start bytes={n:,} lookahead={lookahead} chain={max_chain}")

    while i < n:
        block = solve(i, reps[0] if reps else 0, reps[1] if len(reps) > 1 else 0)
        tok = block[0] if block else (LIT, data[i])
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
                f"candidates={last_candidates} total_candidates={total_candidates:,} "
                f"selected={name}({detail}) tokens={len(tokens):,} "
                f"cost={last_cost} elapsed={elapsed:.2f}s"
            )
            last_report = i

    if progress:
        elapsed = time.perf_counter() - started
        print()
        print(
            f"[DE2-OPT] done tokens={len(tokens):,} "
            f"LIT={selected.get(LIT, 0):,} MATCH={selected.get(MATCH, 0):,} "
            f"REP={selected.get(REP, 0):,} candidates={total_candidates:,} "
            f"elapsed={elapsed:.3f}s"
        )
    return tokens


__all__ = ["tokenize_bounded"]
