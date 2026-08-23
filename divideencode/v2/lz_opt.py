"""Fast bounded DE2 parser laboratory.

Production DE2 remains in lz.py. This parser deliberately bounds matcher work:
cheap prefix filters first, full match measurement only for a tiny frontier.
"""
from __future__ import annotations
import sys, time
from collections import defaultdict
from .lz import LIT, MATCH, REP, MIN_MATCH, DEFAULT_MAX_MATCH, DEFAULT_WINDOW

def _match_length(data, a, b, limit):
    end = min(limit, len(data) - a, len(data) - b); l = 0
    while l < end and data[a + l] == data[b + l]: l += 1
    return l

def _build_index(data):
    index = defaultdict(list)
    for p in range(max(0, len(data) - MIN_MATCH + 1)):
        index[data[p:p + MIN_MATCH]].append(p)
    return index

def _candidates(data, i, window, max_match, max_chain, reps, index, stats, full_limit=4):
    n = len(data); limit = min(max_match, n - i); out = []
    for ri, d in enumerate(reps[:2]):
        if 0 < d <= i and d <= window:
            stats["full_match_checks"] += 1
            l = _match_length(data, i-d, i, min(limit, max(8, MIN_MATCH)))
            if l >= MIN_MATCH:
                if l == min(limit, max(8, MIN_MATCH)) and l < limit:
                    l = _match_length(data, i-d, i, limit)
                out.append((l, d, ri))
    if i + MIN_MATCH > n: return out
    positions = index.get(data[i:i+MIN_MATCH], ()); lower = max(0, i-window)
    prefix_len = min(8, limit); prefix = data[i:i+prefix_len]; survivors=[]
    for p in reversed(positions):
        if p >= i: continue
        if p < lower or len(survivors) >= max_chain: break
        stats["prefix_checks"] += 1
        if data[p:p+prefix_len] == prefix:
            stats["prefix_hits"] += 1; survivors.append(p)
    for p in survivors[:full_limit]:
        stats["full_match_checks"] += 1
        l = _match_length(data, p, i, limit)
        if l >= MIN_MATCH: out.append((l, i-p, -1))
    stats["matches_found"] += len(out)
    if out: stats["max_match"] = max(stats["max_match"], max(x[0] for x in out))
    best={}
    for l,d,ri in out:
        if l > best.get((d,ri),0): best[(d,ri)] = l
    result=[(l,d,ri) for (d,ri),l in best.items()]
    result.sort(key=lambda x:(-x[0],x[1],x[2]))
    return result[:full_limit+2]

def _score(length, distance, rep_index):
    return 3 + max(1,length.bit_length()) if rep_index >= 0 else 8 + max(1,length.bit_length()) + max(1,distance.bit_length())

def _live_line(msg):
    sys.stdout.write("\r" + msg[:210].ljust(210)); sys.stdout.flush()

def _choose(data,i,lookahead,window_size,max_chain,max_match,reps,index,stats):
    n=len(data); current=_candidates(data,i,window_size,max_match,max_chain,reps,index,stats)
    stats["last_candidates"]=len(current); stats["candidates"] += len(current)
    best_score=8; best_tok=(LIT,data[i])
    for length,distance,ri in current:
        length=min(length,lookahead,n-i)
        if length<MIN_MATCH: continue
        score=_score(length,distance,ri)
        if score<best_score or (score==best_score and length>(best_tok[1] if best_tok[0]!=LIT else 0)):
            best_score=score; best_tok=(REP,length,ri) if ri>=0 else (MATCH,length,distance)
    stats["last_cost"]=best_score; return best_tok,best_score

def tokenize_bounded(data,lookahead=32,window_size=DEFAULT_WINDOW,max_chain=16,max_match=DEFAULT_MAX_MATCH,progress=False,progress_every=4096,beam_width=1):
    """Deterministic bounded parser with aggressively bounded match work."""
    if not isinstance(data,bytes): data=bytes(data)
    if lookahead<1 or max_chain<1: raise ValueError("lookahead and max_chain must be >= 1")
    n=len(data)
    if not n:
        if progress: print("[DE2-OPT] empty input")
        return []
    started=time.perf_counter(); index=_build_index(data)
    stats={"candidates":0,"last_candidates":0,"prefix_checks":0,"prefix_hits":0,"full_match_checks":0,"matches_found":0,"max_match":0,"last_cost":8}
    selected={LIT:0,MATCH:0,REP:0}; tokens=[]; reps=[]; i=0; last_report=-progress_every
    if progress: print(f"[DE2-OPT] start bytes={n:,} lookahead={lookahead} chain={max_chain} indexed={len(index):,} keys")
    while i<n:
        tok,cost=_choose(data,i,lookahead,window_size,max_chain,max_match,reps,index,stats); tokens.append(tok); selected[tok[0]]+=1
        if tok[0]==LIT: i+=1
        elif tok[0]==MATCH:
            d=tok[2]
            if d in reps: reps.remove(d)
            reps.insert(0,d); del reps[2:]; i+=tok[1]
        else:
            if tok[2]==1 and len(reps)>1: reps[0],reps[1]=reps[1],reps[0]
            i+=tok[1]
        if progress and (i-last_report>=progress_every or i>=n):
            elapsed=time.perf_counter()-started; speed=i/1024/elapsed if elapsed else 0.; pct=100*i/n
            if tok[0]==LIT: name,detail="LIT",f"byte=0x{tok[1]:02x}"
            elif tok[0]==MATCH: name,detail="MATCH",f"len={tok[1]} distance={tok[2]}"
            else: name,detail=f"REP{tok[2]}",f"len={tok[1]} rep_index={tok[2]}"
            _live_line(f"[DE2-OPT] {pct:6.2f}% pos={i:,}/{n:,} prefix={stats['prefix_checks']:,}/{stats['prefix_hits']:,} full={stats['full_match_checks']:,} matches={stats['matches_found']:,} max_match={stats['max_match']} selected={name}({detail}) tokens={len(tokens):,} score={cost} speed={speed:,.1f}KiB/s elapsed={elapsed:.2f}s"); last_report=i
    if progress:
        elapsed=time.perf_counter()-started; covered=sum(t[1] for t in tokens if t[0]!=LIT)
        print(); print(f"[DE2-OPT] done tokens={len(tokens):,} LIT={selected[LIT]:,} MATCH={selected[MATCH]:,} REP={selected[REP]:,} match_coverage={covered:,} bytes ({100*covered/n:.2f}%) prefix_checks={stats['prefix_checks']:,} prefix_hits={stats['prefix_hits']:,} full_match_checks={stats['full_match_checks']:,} matches_found={stats['matches_found']:,} max_match={stats['max_match']} elapsed={elapsed:.3f}s speed={n/1024/elapsed:,.1f}KiB/s")
    return tokens

__all__=["tokenize_bounded"]
