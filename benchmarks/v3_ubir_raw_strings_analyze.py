from pathlib import Path
import sys,json,math
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from divideencode.v3 import universal_binary_ir as v1
CORPUS=Path(__file__).resolve().parent/'corpus'

def entropy(b):
 c=Counter(b);n=len(b)
 return -sum((x/n)*math.log2(x/n) for x in c.values()) if n else 0

def analyze(name):
 data=(CORPUS/name).read_bytes(); toks=v1._json_tokens(data)
 strings=[];raw=[]
 for t in toks:
  if t.startswith(b'"') and t.endswith(b'"'):
   try:s=json.loads(t.decode())
   except:continue
   strings.append(s.encode('utf-8'))
  elif t not in (b'true',b'false',b'null') and not v1._JSON_INT.fullmatch(t.decode('ascii')) and t[:1] not in b'{}[],:':raw.append(t)
 lengths=Counter(map(len,strings)); vals=Counter(strings)
 print('\n'+'='*80+'\n'+name)
 print(f'strings={len(strings):,} payload={sum(map(len,strings)):,} unique={len(vals):,} repeated_values={sum(n>1 for n in vals.values()):,}')
 print(f'raw_nonstring={sum(map(len,raw)):,} count={len(raw):,}')
 print('lengths:',[(k,v) for k,v in lengths.most_common(20)])
 print('top_values:',[(x.decode('utf-8','replace')[:60],n,len(x)) for x,n in vals.most_common(20)])
 for lim in (1,4,8,16,32,64,128):
  print(f'len<={lim}: {sum(1 for x in strings if len(x)<=lim):,} strings / {sum(len(x) for x in strings if len(x)<=lim):,} B')
 print(f'entropy={entropy(b"".join(strings)):.3f} bits/byte')
for n in ('json_small.json','json_large.json'):analyze(n)
