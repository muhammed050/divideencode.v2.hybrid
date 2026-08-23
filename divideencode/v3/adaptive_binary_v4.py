"""ABR4 experimental lossless preconditioner.

Adds numeric delta coding and CSV column transforms to the ABR family.
The representation is deliberately reversible and self-describing; DE2 is
still the entropy backend and the outer selector must compare final sizes.
"""
from __future__ import annotations
import re
from collections import Counter

MAGIC=b"ABR4"
TEXT=1; CSV=2; JSON=3; DELTA_TEXT=4; CSV_COL=5
_TOKEN_RE=re.compile(r"\w+|\s+|[^\w\s]+",re.UNICODE)

def _u(n:int)->bytes:
    if n<0: raise ValueError("negative varint")
    o=bytearray()
    while n>=128:o.append((n&127)|128);n>>=7
    o.append(n);return bytes(o)

def _r(b:bytes,p:int):
    n=0;s=0
    while p<len(b):
        x=b[p];p+=1;n|=(x&127)<<s
        if not x&128:return n,p
        s+=7
        if s>63:break
    raise ValueError("invalid varint")

def _s(b:bytes)->bytes:
    return _u(len(b))+b

def _g(b,p):
    n,p=_r(b,p);e=p+n
    if e>len(b):raise ValueError("truncated")
    return b[p:e],e

def _zig(n): return (n<<1)^(n>>63)
def _unzig(n): return (n>>1)^-(n&1)

def _dict_encode(text:str)->bytes:
    ts=_TOKEN_RE.findall(text); c=Counter(ts)
    entries=sorted((x for x,n in c.items() if n>=2),key=lambda x:(-c[x]*len(x),x))
    ids={x:i for i,x in enumerate(entries)};o=bytearray(_u(len(entries)))
    for x in entries:o+=_s(x.encode())
    for x in ts:
        i=ids.get(x)
        if i is None:o.append(0);o+=_s(x.encode())
        else:o.append(1);o+=_u(i)
    return bytes(o)

def _dict_decode(b,p):
    n,p=_r(b,p);e=[]
    for _ in range(n):x,p=_g(b,p);e.append(x.decode())
    out=[]
    while p<len(b):
        t=b[p];p+=1
        if t==0:x,p=_g(b,p);out.append(x.decode())
        elif t==1:i,p=_r(b,p);out.append(e[i]) if i<len(e) else (_ for _ in()).throw(ValueError("bad dict ref"))
        else:raise ValueError("bad token tag")
    return ''.join(out),p

def _numeric_runs(text:str):
    return re.split(r'(\d+(?:\.\d+)?)',text)

def _delta_text(data:bytes)->bytes:
    text=data.decode('utf-8'); parts=_numeric_runs(text); o=bytearray(); nums=[]; prev=0
    for part in parts:
        if part and re.fullmatch(r'\d+(?:\.\d+)?',part):
            if '.' in part:
                # Keep decimals literal; integer delta is the safe high-value path.
                o.append(0);o+=_s(part.encode())
            else:
                n=int(part);o.append(1);o+=_u(_zig(n-prev));prev=n
        else:o.append(0);o+=_s(part.encode())
    return bytes(o)

def _delta_decode(b:bytes):
    p=0;prev=0;out=[]
    while p<len(b):
        t=b[p];p+=1
        if t==0:x,p=_g(b,p);out.append(x.decode())
        elif t==1:n,p=_r(b,p);v=prev+_unzig(n);out.append(str(v));prev=v
        else:raise ValueError('bad delta tag')
    return ''.join(out).encode()

def _csv_columns(data:bytes)->bytes:
    text=data.decode('utf-8'); lines=text.splitlines(keepends=True)
    if len(lines)<2:return b''
    rows=[]; seps=[]
    for line in lines:
        nl='\r\n' if line.endswith('\r\n') else ('\n' if line.endswith('\n') else '')
        body=line[:-len(nl)] if nl else line
        cols=body.split(',')
        if len(cols)<2:return b''
        rows.append(cols);seps.append(nl)
    width=len(rows[0])
    if any(len(r)!=width for r in rows):return b''
    o=bytearray(_u(width));
    for col in zip(*rows):
        vals=list(col); o+=_u(len(vals))
        numeric=all(re.fullmatch(r'-?\d+',v or '') for v in vals)
        o.append(1 if numeric else 0)
        if numeric:
            prev=0
            for v in vals:n=int(v);o+=_u(_zig(n-prev));prev=n
        else:
            for v in vals:o+=_s(v.encode())
    # Preserve line endings exactly when reconstructed.
    o+=_s(''.join(seps).encode())
    return bytes(o)

def _csv_columns_decode(b:bytes):
    p=0;width,p=_r(b,p);cols=[]
    for _ in range(width):
        n,p=_r(b,p);t=b[p];p+=1;vals=[]
        if t==1:
            prev=0
            for _ in range(n):z,p=_r(b,p);v=prev+_unzig(z);vals.append(str(v));prev=v
        else:
            for _ in range(n):x,p=_g(b,p);vals.append(x.decode())
        cols.append(vals)
    sepb,p=_g(b,p);seps=sepb.decode().splitlines(True)
    rows=[]
    for i in range(len(cols[0])):
        rows.append(','.join(c[i] for c in cols)+(seps[i] if i<len(seps) else ''))
    return ''.join(rows).encode()

def encode(data:bytes,kind:str)->bytes:
    if kind in ('text','json','csv'):
        code={'text':TEXT,'json':JSON,'csv':CSV}[kind]; payload=_dict_encode(data.decode())
    elif kind=='delta':code=DELTA_TEXT;payload=_delta_text(data)
    elif kind=='csvcol':code=CSV_COL;payload=_csv_columns(data)
    else:raise ValueError('unknown kind')
    return MAGIC+bytes([code])+_u(len(data))+payload

def decode(blob:bytes)->bytes:
    if len(blob)<5 or blob[:4]!=MAGIC:raise ValueError('bad ABR4 header')
    code=blob[4];raw,p=_r(blob,5);payload=blob[p:]
    if code in (TEXT,JSON,CSV):out=_dict_decode(payload,0)[0].encode()
    elif code==DELTA_TEXT:out=_delta_decode(payload)
    elif code==CSV_COL:out=_csv_columns_decode(payload)
    else:raise ValueError('unknown ABR4 kind')
    if len(out)!=raw:raise ValueError('ABR4 length mismatch')
    return out

def candidates(data:bytes,suffix:str):
    s=suffix.lower(); out=[]
    kinds=[]
    if s in {'.json','.jsonl'}:kinds += ['json']
    if s=='.csv':kinds += ['csv','csvcol']
    if s in {'.txt','.log','.html','.css','.c','.h','.cpp','.py','.js','.ts'}:kinds += ['text','delta']
    for k in kinds:
        try:
            x=encode(data,k)
            if decode(x)==data:out.append((k,x))
        except (ValueError,UnicodeDecodeError,IndexError):pass
    return out
