from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from divideencode import de2
from divideencode.v3 import adaptive_binary_v2 as abr

CORPUS=Path(__file__).parent/'corpus'; BS=1<<20

def run():
    total_d=total_a=0
    print('='*116)
    print('V3 ABR2 — CLASS-AWARE DICTIONARY + RLE -> DE2 (1 MiB)')
    print('='*116)
    for p in sorted(CORPUS.iterdir()):
        if not p.is_file(): continue
        data=p.read_bytes()
        t=time.perf_counter(); d=de2.compress(data,block_size=BS,level='BALANCED'); td=time.perf_counter()-t
        assert de2.decompress(d)==data
        best=(len(d),'direct',len(data),td)
        for kind,x in abr.candidates(data,p.suffix):
            t=time.perf_counter(); z=de2.compress(x,block_size=BS,level='BALANCED'); ta=time.perf_counter()-t
            assert abr.decode(x)==data and de2.decompress(z)==x
            if len(z)<best[0]: best=(len(z),kind,len(x),ta)
        total_d+=len(d); total_a+=best[0]
        print(f'{p.name:24s} direct={len(d):9,d} best={best[0]:9,d} delta={best[0]-len(d):+9,d} choice={best[1]:6s} mid={best[2]:9,d} enc={best[3]:5.2f}s')
    print('-'*116)
    print(f'TOTAL direct={total_d:,} B adaptive={total_a:,} B delta={total_a-total_d:+,} B ({(total_a/total_d-1)*100:+.2f}%)')

if __name__=='__main__': run()
