"""ABR6 — semantic JSON + exact CSV columnar transforms."""
from __future__ import annotations
from collections import Counter
import re
MAGIC=b"ABR6"; VER=1; J_JSON=1; J_CSV=2

def _u(n):
    if n<0: raise ValueError('negative varint')
    o=bytearray()
    while n>=128:o.append((n&127)|128);n>>=7
    o.append(n);return bytes(o)

def _r(b,p):
    n=s=0
    while p<len(b):
        x=b[p];p+=1;n|=(x&127)<<s
        if not x&128:return n,p
        s+=7
        if s>63:break
    raise ValueError('bad varint')

def _s(x): return _u(len(x))+x

def _g(b,p):
    n,p=_r(b,p);e=p+n
    if e>len(b):raise ValueError('truncated field')
    return b[p:e],e

def _zig(n):return (n<<1)^(n>>63)
def _unzig(n):return (n>>1)^-(n&1)

def _dict_pack(vals,min_len=1):
    c=Counter(vals); es=[x for x,n in c.items() if n>=2 and len(x)>=min_len]
    es.sort(key=lambda x:(-c[x]*len(x),x)); ids={x:i for i,x in enumerate(es)};o=bytearray(_u(len(es)))
    for x in es:o+=_s(x)
    for x in vals:
        i=ids.get(x)
        if i is None:o.append(0);o+=_s(x)
        else:o.append(1);o+=_u(i)
    return bytes(o)

def _dict_unpack(b,p,count):
    n,p=_r(b,p);es=[]
    for _ in range(n):x,p=_g(b,p);es.append(x)
    out=[]
    for _ in range(count):
        if p>=len(b):raise ValueError('truncated dictionary')
        tag=b[p];p+=1
        if tag==0:x,p=_g(b,p);out.append(x)
        elif tag==1:
            i,p=_r(b,p)
            if i>=len(es):raise ValueError('bad dictionary ref')
            out.append(es[i])
        else:raise ValueError('bad dictionary tag')
    return out,p

# JSON token classes: whitespace/string/number/literal/punctuation.
def _json_tokens(data):
    s=data.decode('utf-8');out=[];i=0;n=len(s)
    while i<n:
        c=s[i]
        if c.isspace():
            j=i+1
            while j<n and s[j].isspace():j+=1
            out.append((0,s[i:j].encode()));i=j;continue
        if c=='"':
            j=i+1
            while j<n:
                if s[j]=='\\':j+=2;continue
                if s[j]=='"':j+=1;break
                j+=1
            if j>n or s[j-1]!='"':raise ValueError('unterminated JSON string')
            out.append((1,s[i:j].encode()));i=j;continue
        if c=='-' or c.isdigit():
            m=re.match(r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?',s[i:])
            if not m:raise ValueError('bad JSON number')
            z=m.group(0);out.append((2,z.encode()));i+=len(z);continue
        for lit in ('true','false','null'):
            if s.startswith(lit,i):out.append((3,lit.encode()));i+=len(lit);break
        else:
            if c in '{}[]:,':out.append((4,c.encode()));i+=1;continue
            raise ValueError('invalid JSON')
            continue
    return out

def _json_encode(data):
    toks=_json_tokens(data);streams={k:[] for k in range(5)}
    for k,v in toks:streams[k].append(v)
    o=bytearray(MAGIC+bytes([VER,J_JSON])+_u(len(data))+_u(len(toks)))
    acc=bits=0
    for k,_ in toks:
        acc|=k<<bits;bits+=3
        while bits>=8:o.append(acc&255);acc>>=8;bits-=8
    if bits:o.append(acc)
    for k in range(5):
        vals=streams[k];o+=_u(len(vals))
        if k==2:
            prev=0
            for x in vals:
                if re.fullmatch(rb'-?\d+',x):o.append(1);v=int(x);o+=_u(_zig(v-prev));prev=v
                else:o.append(0);o+=_s(x)
        else:o+=_dict_pack(vals,1)
    return bytes(o)

def _json_decode(blob,p,raw_len):
    tok_count,p=_r(blob,p);need=(tok_count*3+7)//8;end=p+need
    if end>len(blob):raise ValueError('truncated shape')
    shape=[];acc=bits=0
    for x in blob[p:end]:
        acc|=x<<bits;bits+=8
        while bits>=3 and len(shape)<tok_count:shape.append(acc&7);acc>>=3;bits-=3
    p=end;streams={}
    for k in range(5):
        count,p=_r(blob,p)
        if k==2:
            vals=[];prev=0
            for _ in range(count):
                tag=blob[p];p+=1
                if tag==1:z,p=_r(blob,p);v=prev+_unzig(z);prev=v;vals.append(str(v).encode())
                elif tag==0:x,p=_g(blob,p);vals.append(x)
                else:raise ValueError('bad number tag')
        else:vals,p=_dict_unpack(blob,p,count)
        streams[k]=vals
    pos=[0]*5;out=bytearray()
    for k in shape:
        if k>=5 or pos[k]>=len(streams[k]):raise ValueError('shape mismatch')
        out+=streams[k][pos[k]];pos[k]+=1
    if len(out)!=raw_len:raise ValueError('JSON length mismatch')
    return bytes(out),p

# CSV scanner preserves each raw field and each exact row ending. Multiline
# quoted fields are rejected so the selector safely falls back.
def _csv_rows(data):
    s=data.decode('utf-8');rows=[];ends=[];fields=[];start=0;i=0;quoted=False
    while i<len(s):
        c=s[i]
        if c=='"':
            if not quoted and (i==start or s[start]=='"'):quoted=True
            elif quoted and i+1<len(s) and s[i+1]=='"':i+=2;continue
            elif quoted:quoted=False
        if not quoted and c==',':fields.append(s[start:i].encode());start=i+1
        elif not quoted and c in '\r\n':
            fields.append(s[start:i].encode())
            if c=='\r' and i+1<len(s) and s[i+1]=='\n':ends.append(b'\r\n');i+=1
            else:ends.append(c.encode())
            rows.append(fields);fields=[];start=i+1
        i+=1
    if quoted:raise ValueError('multiline/unterminated CSV quote')
    if start<len(s) or fields:rows.append(fields);ends.append(b'')
    if not rows or any(len(r)!=len(rows[0]) for r in rows):raise ValueError('irregular CSV')
    return rows,ends

def _csv_encode(data):
    rows,ends=_csv_rows(data);width=len(rows[0]);o=bytearray(MAGIC+bytes([VER,J_CSV])+_u(len(data))+_u(len(rows))+_u(width))
    for c in range(width):
        vals=[r[c] for r in rows];numeric=all(re.fullmatch(rb'-?\d+',v or b'') for v in vals)
        o.append(1 if numeric else 0);o+=_u(len(vals))
        if numeric:
            prev=0
            for v in vals:n=int(v);o+=_u(_zig(n-prev));prev=n
        else:o+=_dict_pack(vals,1)
    o+=_u(len(ends))
    for e in ends:o+=_s(e)
    return bytes(o)

def _csv_decode(blob,p,raw_len):
    rows,p=_r(blob,p);width,p=_r(blob,p);cols=[]
    for _ in range(width):
        typ=blob[p];p+=1;n,p=_r(blob,p)
        if typ==1:
            vals=[];prev=0
            for _ in range(n):z,p=_r(blob,p);v=prev+_unzig(z);vals.append(str(v).encode());prev=v
        elif typ==0:vals,p=_dict_unpack(blob,p,n)
        else:raise ValueError('bad CSV column type')
        if n!=rows:raise ValueError('row count mismatch')
        cols.append(vals)
    ne,p=_r(blob,p);ends=[]
    for _ in range(ne):x,p=_g(blob,p);ends.append(x)
    if ne!=rows:raise ValueError('ending count mismatch')
    out=bytearray()
    for i in range(rows):out+=b','.join(cols[c][i] for c in range(width))+ends[i]
    if len(out)!=raw_len:raise ValueError('CSV length mismatch')
    return bytes(out),p

def candidates(data,suffix):
    s=suffix.lower();out=[]
    if s in {'.json','.jsonl'}:
        try:
            x=_json_encode(data);raw,p=_r(x,6);y,q=_json_decode(x,p,raw)
            if y==data and q==len(x):out.append(('abr6:json',x))
        except (ValueError,UnicodeDecodeError):pass
    if s=='.csv':
        try:
            x=_csv_encode(data);raw,p=_r(x,6);y,q=_csv_decode(x,p,raw)
            if y==data and q==len(x):out.append(('abr6:csv',x))
        except (ValueError,UnicodeDecodeError):pass
    return out
