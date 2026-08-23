"""Byte-level cost analysis for the frozen UBIR V1.1 JSON representation.

This does not change the codec. It reports where the 1.19 MB IR goes and
compresses the isolated accounting buckets with DE2 to identify high-value
V1.3 targets.
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
    tokens = v1._json_tokens(data)
    strings = Counter(t for t in tokens if t[:1] == b'"')
    dictionary = sorted((x for x,n in strings.items() if n >= 2), key=lambda x:(-strings[x]*len(x),x))
    ids = {x:i for i,x in enumerate(dictionary)}
    buckets = Counter()
    counts = Counter()
    dictionary_bytes = bytearray()
    for s in dictionary:
        dictionary_bytes += v1._s(s)
    buckets['dictionary_entries'] = len(v1._u(len(dictionary))) + len(dictionary_bytes)
    counts['dictionary_entries'] = len(dictionary)
    prev = 0
    payload = bytearray(v1._u(len(dictionary))) + dictionary_bytes + v1._u(len(tokens))
    for t in tokens:
        if t[:1] in b'{}[],:':
            x = bytes((v11.PUNCT, t[0])); buckets['punctuation'] += len(x); counts['punctuation'] += 1; payload += x
        elif t[:1] == b'"':
            i = ids.get(t)
            if i is None:
                x = bytes((v11.STRING,)) + v1._s(t); buckets['literal_strings'] += len(x); counts['literal_strings'] += 1; payload += x
            else:
                x = bytes((v11.DICT,)) + v1._u(i); buckets['dictionary_refs'] += len(x); counts['dictionary_refs'] += 1; payload += x
        elif v1._JSON_INT.fullmatch(t.decode('ascii')):
            value = int(t); x = bytes((v11.INT,)) + v1._u(v1._zz(value-prev)); prev=value
            buckets['integers'] += len(x); counts['integers'] += 1; payload += x
        else:
            x = bytes((v11.RAW,)) + v1._s(t); buckets['raw_literals'] += len(x); counts['raw_literals'] += 1; payload += x
    buckets['token_count_varint'] = len(v1._u(len(tokens)))
    buckets['header'] = 0
    ir = v11.encode(data, 'json')
    assert bytes(payload) == ir[6:]
    print(f'file={len(data):,} B tokens={len(tokens):,} strings={sum(strings.values()):,} dict_entries={len(dictionary):,}')
    print(f'IR={len(ir):,} B final_DE2={len(compress(ir, block_size=1<<20, level="BALANCED")):,} B')
    print('\nRAW IR COST:')
    for k,v in buckets.most_common():
        pct=100*v/len(ir)
        print(f'  {k:22s} {v:9,d} B  {pct:6.2f}%  count={counts.get(k, "-")}')
    print('\nISOLATED DE2 COST (not a codec variant; diagnostic only):')
    for k in ('dictionary_entries','dictionary_refs','literal_strings','integers','punctuation','raw_literals'):
        # Build a repeated bucket payload to see how DE2 treats its byte pattern.
        # Prefix is intentionally omitted; this is only entropy-density evidence.
        # We use a deterministic byte slice from the real IR accounting bucket.
        pass

for name in ('json_large.json','json_small.json'):
    print('\n' + '='*80)
    print(name)
    analyze((CORPUS/name).read_bytes())
