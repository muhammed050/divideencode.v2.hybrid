from pathlib import Path
import sys,re,json
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from divideencode.v3 import universal_binary_ir as v1
CORPUS=Path(__file__).resolve().parent/'corpus'

def classify(t):
 if not (t.startswith(b'"') and t.endswith(b'"')): return 'raw_non_string'
 body=t[1:-1]
 try: s=json.loads(t.decode('utf-8')); raw=s.encode('utf-8')
 except Exception: raw=body
 if not body:return 'empty_string'
 if b'\\' in body:return 'escaped_string'
 if len(body)<=8:return 'short_string'
 if len(body)<=32:return 'medium_string'
 return 'long_string'

def analyze(name):
 data=(CORPUS/name).read_bytes();tokens=v1._json_tokens(data);c=Counter();sizes=Counter();prefix=Counter();suffix=Counter();chars=Counter()
 for t in tokens:
  # Candidate RAW literals are tokens not represented by punctuation/int/string dictionary.
  if t[:1] in b'{}[],:"' or v1._JSON_INT.fullmatch(t.decode('ascii')) or t in (b'true',b'false',b'null') or (t and all(x in b' \t\r\n' for x in t)):continue
  k=classify(t);c[k]+=1;sizes[k]+=len(t)
  if k.endswith('string'):
   body=t[1:-1]
   prefix[body[:4]]+=1;suffix[body[-4:]]+=1
   chars.update(body)
 print('\n'+'='*80+'\n'+name)
 total=sum(sizes.values());print(f'raw_candidate={total:,} B tokens={sum(c.values()):,}')
 for k,n in c.most_common():print(f'{k:18s} count={n:9,d} bytes={sizes[k]:9,d} avg={sizes[k]/n:.2f}')
 print('top_prefixes:',[(x.decode('utf-8','replace'),n) for x,n in prefix.most_common(15)])
 print('top_suffixes:',[(x.decode('utf-8','replace'),n) for x,n in suffix.most_common(15)])
 print('top_chars:',[(chr(x),n) for x,n in chars.most_common(20)])
for n in ('json_small.json','json_large.json'):analyze(n)
