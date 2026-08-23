from pathlib import Path
import sys
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v13ab as c
from divideencode.v3 import universal_binary_ir as v1
CORPUS=Path(__file__).resolve().parent/'corpus'

def analyze(data):
 tokens=v1._json_tokens(data); strings=Counter(t for t in tokens if t[:1]==b'"')
 dictionary=sorted((x for x,n in strings.items() if n>=2),key=lambda x:(-strings[x]*len(x),x)); ids={x:i for i,x in enumerate(dictionary)}
 b=Counter(); cnt=Counter()
 b['dictionary_entries']=len(v1._u(len(dictionary)))+sum(len(v1._s(x)) for x in dictionary); cnt['dictionary_entries']=len(dictionary)
 for t in tokens:
  if t[:1] in b'{}[],:': b['punctuation']+=1;cnt['punctuation']+=1
  elif t[:1]==b'"':
   i=ids.get(t)
   if i is None:b['literal_strings']+=1+len(v1._s(t));cnt['literal_strings']+=1
   else:b['dictionary_refs']+=1+len(v1._u(i));cnt['dictionary_refs']+=1
  elif v1._JSON_INT.fullmatch(t.decode('ascii')):
   b['integers']+=1+len(v1._u(v1._zz(int(t))));cnt['integers']+=1
  elif t==b'true' or t==b'false' or t==b'null':b['compact_literals']+=1;cnt['compact_literals']+=1
  else:b['raw_literals']+=1+len(v1._s(t));cnt['raw_literals']+=1
 ir=c.encode(data,'json'); packed=compress(ir,block_size=1<<20,level='BALANCED'); accounted=sum(b.values())+6
 print(f'file={len(data):,} B tokens={len(tokens):,} dict={len(dictionary):,} IR={len(ir):,} B DE2={len(packed):,} B residual={len(ir)-accounted:+,} B')
 for k,x in b.most_common():print(f'  {k:20s} {x:9,d} B {100*x/len(ir):6.2f}% count={cnt[k]:,}')
for name in ('json_large.json','json_small.json'):
 print('\n'+'='*80+'\n'+name);analyze((CORPUS/name).read_bytes())
