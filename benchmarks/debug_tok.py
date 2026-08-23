import sys
sys.path.insert(0, ".")
from divideencode.de2 import lz

data = open("benchmarks/corpus/src_small.c", "rb").read()[:8988]

orig_ml = lz._match_length
calls = []
def spy(a_data, a, b, limit):
    l = orig_ml(a_data, a, b, limit)
    if l >= 4:
        calls.append((a, b, l))
    return l
lz._match_length = spy

blob = lz.encode(data)

# replay tokens
from divideencode.bitstream import decode_varint as rv
from divideencode.de2 import entropy
pos = 0
end = len(blob)
nm, pos = rv(blob, pos, end)
litc, pos = rv(blob, pos, end)
tables = entropy.DecodeTables()
lits, pos = entropy.decode_stream(blob, pos, end, litc, tables)

def rdstream():
    global pos
    slen, pos = rv(blob, pos, end)
    sblob, pos = entropy.decode_stream(blob, pos, end, slen, tables)
    vals = []
    p = 0
    while p < slen:
        v, p = rv(sblob, p, slen)
        vals.append(v)
    return vals

lls, mls, ds = rdstream(), rdstream(), rdstream()

# expected emission positions per token
exp_p = []
o = 0
for t in range(nm):
    o += lls[t]
    exp_p.append(o)
    o += mls[t] + 4

print("first few _match_length(a,b,l):", calls[:5])
for t in range(min(6, nm)):
    print("token %d: emit_at=%d ll=%d ml=%d dist_raw=%d" %
          (t, exp_p[t], lls[t], mls[t]+4, ds[t]))

# find matching (b == emit position) candidates in calls for token 1
t = 1
cands = [(a, b, l) for a, b, l in calls if b == exp_p[t]]
print("candidates searched AT token1 emit pos:", cands[:10])
