from pathlib import Path
import sys,re
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from divideencode.v3 import universal_binary_ir as v1
CORPUS=Path(__file__).resolve().parent/'corpus'
NUM=re.compile(rb'^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$')
WS=set(b' \t\r\n')

def classify(t):
 if all(c in WS for c in t): return 'whitespace'
 if NUM.fullmatch(t): return 'numeric_nonint'
 if t in (b'true',b'false',b'null'): return 'literal'
 if all(32<=c<127 for c in t): return 'ascii_other'
 return 'binary_other'
for name in ('json_large.json','json_small.json'):
 data=(CORPUS/name).read_bytes();tokens=v1._json_tokens(data); c=Counter(); bytes_=Counter(); lens=Counter()
 for t in tokens:
  if t[:1] in b'{}[],:"' or v1._JSON_INT.fullmatch(t.decode('ascii')) or t in (b'true',b'false',b'null'): continue
  k=classify(t);c[k]+=1;bytes_[k]+=len(t);lens[k]+=len(v1._s(t))
 print('\n'+'='*80+'\n'+name)
 for k,n in c.most_common(): print(f'{k:16s} count={n:9,d} payload={bytes_[k]:9,d} framed={lens[k]:9,d} avg={bytes_[k]/n:.2f}')
