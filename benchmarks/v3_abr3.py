from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from divideencode import de2
from divideencode.v3 import adaptive_binary_v3 as abr3

CORPUS=Path(__file__).parent/'corpus'; BS=1<<20

def run():
    td_total=ta_total=0
    print('='*120)
    print('V3 ABR3 — END-TO-END SELECTOR: DIRECT vs ABR1 vs ABR2 -> DE2')
    print('1 MiB blocks; selection is based only on final packed size')
    print('='*120)
    for p in sorted(CORPUS.iterdir()):
        if not p.is_file(): continue
        data=p.read_bytes()
        t=time.perf_counter(); direct=de2.compress(data,block_size=BS,level='BALANCED'); td=time.perf_counter()-t
        assert de2.decompress(direct)==data
        kind,best,mid,ta=abr3.choose(data,p.suffix,lambda x:de2.compress(x,block_size=BS,level='BALANCED'))
        assert de2.decompress(best) is not None
        if kind=='direct':
            assert de2.decompress(best)==data
        else:
            assert abr3.decode(kind,de2.decompress(best))==data
        delta=len(best)-len(direct)
        print(f'{p.name:24s} direct={len(direct):9,d} best={len(best):9,d} delta={delta:+9,d} choice={kind:11s} mid={mid:9,d} enc={ta:5.2f}s')
        td_total+=len(direct); ta_total+=len(best)
    print('-'*120)
    print(f'TOTAL direct={td_total:,} B  ABR3={ta_total:,} B  delta={ta_total-td_total:+,} B ({(ta_total/td_total-1)*100:+.2f}%)')
    print('RESULT: ABR3 is a selector experiment; direct remains the fallback.')

if __name__=='__main__': run()
