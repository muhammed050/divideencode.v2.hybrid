from __future__ import annotations
import argparse, csv, pathlib, statistics, sys, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from divideencode.v2.codec import compress as de2_compress, decompress as de2_decompress
from divideencode.v2.patternized import compress as pattern_compress, decompress as pattern_decompress

def timed(fn,runs):
    vals=[]; result=None
    for _ in range(runs):
        t=time.perf_counter(); result=fn(); vals.append(time.perf_counter()-t)
    return result,statistics.median(vals)

def run_one(path,runs):
    raw=path.read_bytes()
    d2,te=timed(lambda:de2_compress(raw),runs)
    _,td=timed(lambda:de2_decompress(d2),runs)
    dp,pe=timed(lambda:pattern_compress(raw),runs)
    restored,pd=timed(lambda:pattern_decompress(dp),runs)
    if restored!=raw: raise AssertionError(f"DE2-P roundtrip failed: {path}")
    return {"file":path.name,"orig":len(raw),"de2_size":len(d2),"pattern_size":len(dp),
            "de2_ratio":len(d2)/len(raw) if raw else 0,"pattern_ratio":len(dp)/len(raw) if raw else 0,
            "de2_enc":te,"pattern_enc":pe,"de2_dec":td,"pattern_dec":pd,"lossless":True}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("samples",type=pathlib.Path); ap.add_argument("--runs",type=int,default=3)
    ap.add_argument("--csv",type=pathlib.Path,default=ROOT/"benchmarks/results/de2_pattern.csv"); a=ap.parse_args()
    files=sorted(p for p in a.samples.rglob("*") if p.is_file()); rows=[]
    for i,p in enumerate(files,1):
        r=run_one(p,a.runs); rows.append(r)
        print(f"[{i}/{len(files)}] {p} ({r['orig']:,} B)")
        print(f"    DE2      {r['de2_size']:>9,} B ratio={r['de2_ratio']:.4f} enc={r['de2_enc']:.4f}s")
        print(f"    DE2-P    {r['pattern_size']:>9,} B ratio={r['pattern_ratio']:.4f} enc={r['pattern_enc']:.4f}s")
    a.csv.parent.mkdir(parents=True,exist_ok=True)
    with a.csv.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    total=sum(r["orig"] for r in rows); s2=sum(r["de2_size"] for r in rows); sp=sum(r["pattern_size"] for r in rows)
    e2=sum(r["de2_enc"] for r in rows); ep=sum(r["pattern_enc"] for r in rows)
    print("\nFINAL DE2 PATTERNIZATION")
    print("="*92); print(f"{'Algorithm':<12}{'Orig':>14}{'Comp':>14}{'Ratio':>10}{'Saved':>10}{'Enc(s)':>12}")
    print("-"*92)
    for n,s,e in (("DE2",s2,e2),("DE2-P",sp,ep)):
        q=s/total; print(f"{n:<12}{total:>14,}{s:>14,}{q:>10.4f}{(1-q)*100:>9.2f}%{e:>12.3f}")
    print("="*92); print(f"CSV: {a.csv}")

if __name__=="__main__": main()
