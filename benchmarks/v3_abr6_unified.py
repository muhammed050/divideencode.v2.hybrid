from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from divideencode import de2
from divideencode.v3 import adaptive_binary_v6_unified as abr

CORPUS=Path(__file__).parent/'corpus'; BS=1<<20

def run():
    print('='*120)
    print('V3 ABR6 UNIFIED — DIRECT + ABR1/2/4/5 + NEW JSON/CSV TRANSFORMS -> DE2')
    print('1 MiB blocks; selection uses only final packed size; exact roundtrip required')
    print('='*120)
    td=ta=0
    for p in sorted(CORPUS.iterdir()):
        if not p.is_file():continue
        data=p.read_bytes()
        t=time.perf_counter(); direct=de2.compress(data,block_size=BS,level='BALANCED'); dt=time.perf_counter()-t
        assert de2.decompress(direct)==data
        best=(len(direct),'direct',len(data),dt)
        for kind,payload in abr.candidates(data,p.suffix):
            t=time.perf_counter(); packed=de2.compress(payload,block_size=BS,level='BALANCED'); et=time.perf_counter()-t
            assert de2.decompress(packed)==payload
            if kind.startswith('abr6:'):
                if kind=='abr6:json':
                    from divideencode.v3.adaptive_binary_v6 import _json_decode
                    raw,p0=__import__('divideencode.v3.adaptive_binary_v6',fromlist=['_r'])._r(payload,6)
                    assert _json_decode(payload,p0,raw)[0]==data
                else:
                    from divideencode.v3.adaptive_binary_v6 import _csv_decode,_r
                    raw,p0=_r(payload,6); assert _csv_decode(payload,p0,raw)[0]==data
            if len(packed)<best[0]:best=(len(packed),kind,len(payload),et)
        td+=len(direct);ta+=best[0]
        print(f'{p.name:24s} direct={len(direct):9,d} best={best[0]:9,d} delta={best[0]-len(direct):+9,d} choice={best[1]:18s} mid={best[2]:9,d} enc={best[3]:5.2f}s')
    print('-'*120)
    print(f'TOTAL direct={td:,} B ABR6U={ta:,} B delta={ta-td:+,} B ({(ta/td-1)*100:+.2f}%)')
    print('RESULT:', 'ABR6U wins' if ta<td else 'direct remains better')

if __name__=='__main__':run()
