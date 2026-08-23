"""Byte-level cost analysis for frozen UBIR V1.1 JSON.

Accounting-only: it does not reconstruct the payload, so parser assumptions
cannot be confused with codec correctness.
"""
from pathlib import Path
from collections import Counter
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from divideencode.de2 import compress
from divideencode.v3 import ubir_v11 as v11
from divideencode.v3 import universal_binary_ir as v1
CORPUS = Path(__file__).resolve().parent / "corpus"

def analyze(data: bytes):
    tokens=v1._json_tokens(data)
    strings=Counter(t for t in tokens if t[:1]==b'"')
    dictionary=sorted((x for x,n in strings.items() if n>=2), key=lambda x:(-strings[x]*len(x),x))
    ids={x:i for i,x in enumerate(dictionary)}
    b=Counter(); c=Counter()
    db=sum(len(v1._s(s)) for s in dictionary)+len(v1._u(len(dictionary)))
    b['dictionary_entries']=db; c['dictionary_entries']=len(dictionary)
    for t in tokens:
        if t[:1] in b'{}[],:': b['punctuation']+=2; c['punctuation']+=1
        elif t[:1]==b'"':
            i=ids.get(t)
            if i is None: b['literal_strings']+=1+len(v1._s(t)); c['literal_strings']+=1
            else: b['dictionary_refs']+=1+len(v1._u(i)); c['dictionary_refs']+=1
        elif v1._JSON_INT.fullmatch(t.decode('ascii')):
            b['integers']+=1+len(v1._u(v1._zz(int(t)))); c['integers']+=1
        else: b['raw_literals']+=1+len(v1._s(t)); c['raw_literals']+=1
    b['token_count_varint']=len(v1._u(len(tokens)))
    ir=v11.encode(data,'json'); packed=compress(ir,block_size=1<<20,level='BALANCED')
    accounted=sum(b.values())+6
    print(f'file={len(data):,} B tokens={len(tokens):,} strings={sum(strings.values()):,} dict_entries={len(dictionary):,}')
    print(f'IR={len(ir):,} B final_DE2={len(packed):,} B accounted={accounted:,} B residual={len(ir)-accounted:+,} B')
    print('\nRAW IR COST:')
    for k,v in b.most_common(): print(f'  {k:22s} {v:9,d} B  {100*v/len(ir):6.2f}%  count={c.get(k,"-")}')

for name in ('json_large.json','json_small.json'):
    print('\n'+'='*80); print(name); analyze((CORPUS/name).read_bytes())
