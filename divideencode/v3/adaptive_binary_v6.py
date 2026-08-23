"""ABR6 — unified structured preconditioner experiment.

ABR6 keeps DE2 as the entropy backend and contributes only reversible
representations. It targets the two places where ABR5 left compression on the
table: JSON lexical semantics and CSV column regularity.

The outer selector must compare the *final DE2 size*, never the intermediate
representation size.
"""
from __future__ import annotations

from collections import Counter
import re

MAGIC = b"ABR6"
VER = 1
J_JSON = 1
J_CSV = 2


def _u(n: int) -> bytes:
    if n < 0: raise ValueError("negative varint")
    o = bytearray()
    while n >= 128:
        o.append((n & 127) | 128); n >>= 7
    o.append(n); return bytes(o)


def _r(b: bytes, p: int) -> tuple[int, int]:
    n = s = 0
    while p < len(b):
        x = b[p]; p += 1; n |= (x & 127) << s
        if not x & 128: return n, p
        s += 7
        if s > 63: break
    raise ValueError("bad varint")


def _s(x: bytes) -> bytes: return _u(len(x)) + x


def _g(b: bytes, p: int) -> tuple[bytes, int]:
    n, p = _r(b, p); e = p + n
    if e > len(b): raise ValueError("truncated field")
    return b[p:e], e


def _zig(n: int) -> int: return (n << 1) ^ (n >> 63)
def _unzig(n: int) -> int: return (n >> 1) ^ -(n & 1)


def _dict_pack(values: list[bytes], min_len: int = 2) -> bytes:
    c = Counter(values)
    entries = [x for x, n in c.items() if n >= 2 and len(x) >= min_len]
    entries.sort(key=lambda x: (-c[x] * len(x), x))
    ids = {x: i for i, x in enumerate(entries)}
    o = bytearray(_u(len(entries)))
    for x in entries: o += _s(x)
    for x in values:
        i = ids.get(x)
        if i is None: o.append(0); o += _s(x)
        else: o.append(1); o += _u(i)
    return bytes(o)


def _dict_unpack(b: bytes, p: int, count: int) -> tuple[list[bytes], int]:
    n, p = _r(b, p); entries = []
    for _ in range(n): x, p = _g(b, p); entries.append(x)
    out = []
    for _ in range(count):
        if p >= len(b): raise ValueError("truncated dictionary stream")
        tag = b[p]; p += 1
        if tag == 0: x, p = _g(b, p); out.append(x)
        elif tag == 1:
            i, p = _r(b, p)
            if i >= len(entries): raise ValueError("bad dictionary ref")
            out.append(entries[i])
        else: raise ValueError("bad dictionary tag")
    return out, p


# ---------------- JSON: semantic token streams ----------------

def _json_tokens(data: bytes) -> list[tuple[int, bytes]]:
    """Return exact JSON lexical tokens; no byte is normalized."""
    s = data.decode("utf-8"); out = []; i = 0; n = len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            j = i + 1
            while j < n and s[j].isspace(): j += 1
            out.append((0, s[i:j].encode())); i = j; continue
        if c == '"':
            j = i + 1
            while j < n:
                if s[j] == '\\': j += 2; continue
                if s[j] == '"': j += 1; break
                j += 1
            if j > n or not s[j-1:j] == '"': raise ValueError("unterminated JSON string")
            out.append((1, s[i:j].encode())); i = j; continue
        if c == '-' or c.isdigit():
            m = re.match(r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?', s[i:])
            if not m: raise ValueError("bad JSON number")
            raw = m.group(0).encode(); out.append((2, raw)); i += len(m.group(0)); continue
        if s.startswith('true', i): out.append((3, b'true')); i += 4; continue
        if s.startswith('false', i): out.append((3, b'false')); i += 5; continue
        if s.startswith('null', i): out.append((3, b'null')); i += 4; continue
        if c in '{}[]:,': out.append((4, c.encode())); i += 1; continue
        raise ValueError("invalid JSON byte")
    return out


def _json_encode(data: bytes) -> bytes:
    toks = _json_tokens(data); streams = {0: [], 1: [], 2: [], 3: [], 4: []}
    for k, v in toks: streams[k].append(v)
    o = bytearray(MAGIC + bytes([VER, J_JSON]) + _u(len(data)) + _u(len(toks)))
    # Shape uses 3 bits/token, packed LSB-first.
    acc = bits = 0
    for k, _ in toks:
        acc |= k << bits; bits += 3
        if bits >= 8: o.append(acc & 255); acc >>= 8; bits -= 8
    if bits: o.append(acc)
    for k in range(5):
        vals = streams[k]; o += _u(len(vals))
        if k == 2:
            # Numbers: integer values become delta-varints; floats/exponents stay literal.
            o += _u(sum(bool(re.fullmatch(rb'-?\d+', x)) for x in vals))
            prev = 0
            for x in vals:
                if re.fullmatch(rb'-?\d+', x):
                    o.append(1); v = int(x); o += _u(_zig(v-prev)); prev = v
                else:
                    o.append(0); o += _s(x)
        elif k == 4:
            o += _dict_pack(vals, 1)
        else:
            o += _dict_pack(vals, 1 if k in (0,3) else 2)
    return bytes(o)


def _json_decode(blob: bytes, raw_len: int, p: int) -> bytes:
    tok_count, p = _r(blob, p); shape = []; acc = bits = 0; need = (tok_count * 3 + 7)//8
    end = p + need
    if end > len(blob): raise ValueError("truncated JSON shape")
    for x in blob[p:end]:
        acc |= x << bits; bits += 8
        while bits >= 3 and len(shape) < tok_count:
            shape.append(acc & 7); acc >>= 3; bits -= 3
    p = end; streams = {}
    for k in range(5):
        count, p = _r(blob, p)
        if k == 2:
            int_count, p = _r(blob, p); vals = []; prev = 0
            for _ in range(count):
                tag = blob[p]; p += 1
                if tag == 1:
                    z, p = _r(blob, p); v = prev + _unzig(z); prev = v; vals.append(str(v).encode())
                elif tag == 0: x, p = _g(blob, p); vals.append(x)
                else: raise ValueError("bad JSON number tag")
            if int_count > count: raise ValueError("bad integer count")
        else:
            vals, p = _dict_unpack(blob, p, count)
        streams[k] = vals
    pos = [0]*5; out = bytearray()
    for k in shape:
        if k >= 5 or pos[k] >= len(streams[k]): raise ValueError("JSON shape mismatch")
        out += streams[k][pos[k]]; pos[k] += 1
    if len(out) != raw_len: raise ValueError("JSON length mismatch")
    return bytes(out)


# ---------------- CSV: exact raw-cell columnar transform ----------------

def _csv_rows(data: bytes) -> tuple[list[list[bytes]], list[bytes]]:
    """Parse simple comma CSV while preserving raw cell spelling and row endings.

    Multiline quoted fields are deliberately rejected for this candidate; the
    outer selector then falls back to another representation. Quoted commas and
    escaped quotes inside a row are supported.
    """
    s = data.decode('utf-8'); rows=[]; ends=[]; fields=[]; start=0; i=0; quoted=False
    while i < len(s):
        c=s[i]
        if c=='"':
            if not quoted and (i==start or s[start]=='"'): quoted=True
            elif quoted and i+1<len(s) and s[i+1]=='"': i += 2; continue
            elif quoted: quoted=False
        if not quoted and c==',': fields.append(s[start:i].encode()); start=i+1
        elif not quoted and c in '\r\n':
            fields.append(s[start:i].encode())
            if c=='\r' and i+1<len(s) and s[i+1]=='\n': ends.append(b'\r\n'); i += 1
            else: ends.append(c.encode())
            rows.append(fields); fields=[]; start=i+1
        i += 1
    if quoted: raise ValueError('multiline/unterminated CSV quote')
    if start < len(s) or fields: rows.append(fields); ends.append(b'')
    if not rows or any(len(r)!=len(rows[0]) for r in rows): raise ValueError('irregular CSV')
    if len(ends)!=len(rows): raise ValueError('CSV row framing mismatch')
    return rows, ends


def _csv_encode(data: bytes) -> bytes:
    rows, ends = _csv_rows(data); width=len(rows[0]); count=len(rows)
    o=bytearray(MAGIC+bytes([VER,J_CSV])+_u(len(data))+_u(count)+_u(width))
    for col in range(width):
        vals=[r[col] for r in rows]
        numeric=all(re.fullmatch(rb'-?\d+',v or b'') for v in vals)
        o.append(1 if numeric else 0); o += _u(len(vals))
        if numeric:
            prev=0
            for v in vals: n=int(v); o += _u(_zig(n-prev)); prev=n
        else: o += _dict_pack(vals, 1)
    o += _u(len(ends))
    for e in ends: o += _s(e)
    return bytes(o)


def _csv_decode(blob: bytes, raw_len: int, p: int) -> bytes:
    rows,p=_r(blob,p); width,p=_r(blob,p); cols=[]
    for _ in range(width):
        typ=blob[p]; p+=1; n,p=_r(blob,p); vals=[]
        if typ==1:
            prev=0
            for _ in range(n): z,p=_r(blob,p); v=prev+_unzig(z); vals.append(str(v).encode()); prev=v
        elif typ==0: vals,p=_dict_unpack(blob,p,n)
        else: raise ValueError('bad CSV column type')
        if n!=rows: raise ValueError('CSV row count mismatch')
        cols.append(vals)
    ne,p=_r(blob,p); ends=[]
    for _ in range(ne): x,p=_g(blob,p); ends.append(x)
    if ne!=rows: raise ValueError('CSV endings mismatch')
    out=bytearray()
    for i in range(rows):
        out += b','.join(cols[c][i] for c in range(width)); out += ends[i]
    if len(out)!=raw_len: raise ValueError('CSV length mismatch')
    return bytes(out)


def candidates(data: bytes, suffix: str) -> list[tuple[str, bytes]]:
    s=suffix.lower(); out=[]
    if s in {'.json','.jsonl'}:
        try:
            x=_json_encode(data)
            if _json_decode(x,len(data),6)==data: out.append(('abr6:json',x))
        except (ValueError,UnicodeDecodeError): pass
    if s=='.csv':
        try:
            x=_csv_encode(data)
            # Header: magic(4)+ver(1)+kind(1)+raw_len varint+rows varint+width varint.
            p=6; raw,p=_r(x,p)
            if _csv_decode(x,raw,p)==data: out.append(('abr6:csv',x))
        except (ValueError,UnicodeDecodeError): pass
    return out
