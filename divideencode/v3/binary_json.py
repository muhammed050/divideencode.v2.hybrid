"""Typed Binary JSON V2 experiment.

The format stores JSON structure as typed binary nodes instead of preserving
JSON punctuation as lexical payload. Exact reconstruction is retained by
storing whitespace runs at grammar boundaries and original lexical spellings
for strings/numbers that cannot safely be normalized.
"""
from __future__ import annotations

import re
from collections import Counter

MAGIC = b"BJSON"
VERSION = 1

T_OBJECT = 1
T_ARRAY = 2
T_STRING = 3
T_INT = 4
T_FLOAT = 5
T_TRUE = 6
T_FALSE = 7
T_NULL = 8
T_KEY_REF = 9

_WS = re.compile(rb"[ \t\r\n]*")
_STR = re.compile(rb'"(?:\\.|[^"\\])*"')
_NUM = re.compile(rb'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')


def u(n: int) -> bytes:
    out = bytearray()
    while n >= 128:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def r(data: bytes, p: int):
    n = 0; shift = 0
    while p < len(data):
        b = data[p]; p += 1
        n |= (b & 127) << shift
        if not b & 128:
            return n, p
        shift += 7
    raise ValueError("truncated varint")


def s(x: bytes) -> bytes:
    return u(len(x)) + x


def g(data: bytes, p: int):
    n, p = r(data, p)
    e = p + n
    if e > len(data): raise ValueError("truncated bytes")
    return data[p:e], e


def zz(n: int) -> int:
    return n << 1 if n >= 0 else ((-n << 1) - 1)


def uzz(n: int) -> int:
    return n >> 1 if not n & 1 else -((n >> 1) + 1)


def _lex(data: bytes):
    """Return significant JSON tokens and the whitespace before each token."""
    p = 0; out = []
    while p < len(data):
        m = _WS.match(data, p); ws = m.group(0); p = m.end()
        if p >= len(data):
            return out, ws
        c = data[p:p+1]
        if c in b"{}[]:,":
            tok = c; p += 1
        elif c == b'"':
            m = _STR.match(data, p)
            if not m: raise ValueError("invalid JSON string")
            tok = m.group(0); p = m.end()
        elif data.startswith(b"true", p): tok = b"true"; p += 4
        elif data.startswith(b"false", p): tok = b"false"; p += 5
        elif data.startswith(b"null", p): tok = b"null"; p += 4
        else:
            m = _NUM.match(data, p)
            if not m: raise ValueError("invalid JSON token")
            tok = m.group(0); p = m.end()
        out.append((ws, tok))
    return out, b""


class _Parser:
    def __init__(self, toks):
        self.t = toks; self.i = 0; self.keys = Counter()

    def peek(self):
        return self.t[self.i][1] if self.i < len(self.t) else None

    def take(self):
        if self.i >= len(self.t): raise ValueError("unexpected EOF")
        x = self.t[self.i]; self.i += 1; return x

    def value(self):
        ws, tok = self.take()
        if tok == b'{':
            fields = []
            if self.peek() == b'}':
                close = self.take(); return ("obj", ws, fields, close[0])
            while True:
                kws, key = self.take()
                if not key.startswith(b'"') or self.peek() != b':': raise ValueError("invalid object")
                self.keys[key] += 1
                cws, _colon = self.take()
                val = self.value()
                fields.append((kws, key, cws, val))
                if self.peek() == b'}':
                    close = self.take(); return ("obj", ws, fields, close[0])
                if self.peek() != b',': raise ValueError("missing object comma")
                comma = self.take()
                # Store the comma whitespace as part of the next field's key ws
                # by inserting it into the next token's whitespace during encode.
                if self.i < len(self.t):
                    n_ws, n_tok = self.t[self.i]
                    self.t[self.i] = (comma[0] + n_ws, n_tok)
        elif tok == b'[':
            vals = []
            if self.peek() == b']':
                close = self.take(); return ("arr", ws, vals, close[0])
            while True:
                vals.append(self.value())
                if self.peek() == b']':
                    close = self.take(); return ("arr", ws, vals, close[0])
                if self.peek() != b',': raise ValueError("missing array comma")
                comma = self.take()
                if self.i < len(self.t):
                    n_ws, n_tok = self.t[self.i]
                    self.t[self.i] = (comma[0] + n_ws, n_tok)
        elif tok.startswith(b'"'): return ("str", ws, tok)
        elif tok == b"true": return ("true", ws)
        elif tok == b"false": return ("false", ws)
        elif tok == b"null": return ("null", ws)
        elif b'.' in tok or b'e' in tok.lower(): return ("float", ws, tok)
        return ("int", ws, int(tok), tok)


def _collect_keys(node, out):
    if node[0] == "obj":
        for f in node[2]:
            out.append(f[1])
            _collect_keys(f[3], out)
    elif node[0] == "arr":
        for v in node[2]: _collect_keys(v, out)


def _enc_node(node, key_ids):
    k = node[0]; out = bytearray()
    if k == "obj":
        out += bytes([T_OBJECT]) + s(node[1]) + u(len(node[2]))
        for kws, key, cws, val in node[2]:
            out += bytes([T_KEY_REF]) + s(kws) + u(key_ids[key]) + s(cws) + _enc_node(val, key_ids)
        out += s(node[3])
    elif k == "arr":
        out += bytes([T_ARRAY]) + s(node[1]) + u(len(node[2]))
        for v in node[2]: out += _enc_node(v, key_ids)
        out += s(node[3])
    elif k == "str": out += bytes([T_STRING]) + s(node[1]) + s(node[2])
    elif k == "int":
        out += bytes([T_INT]) + s(node[1]) + u(zz(node[2]))
    elif k == "float": out += bytes([T_FLOAT]) + s(node[1]) + s(node[2])
    elif k == "true": out += bytes([T_TRUE]) + s(node[1])
    elif k == "false": out += bytes([T_FALSE]) + s(node[1])
    elif k == "null": out += bytes([T_NULL]) + s(node[1])
    return bytes(out)


def encode(data: bytes) -> bytes:
    toks, trailing = _lex(data)
    parser = _Parser(toks)
    root = parser.value()
    if parser.i != len(toks): raise ValueError("trailing JSON tokens")
    keys = []
    _collect_keys(root, keys)
    counts = Counter(keys)
    dictionary = sorted((k for k, n in counts.items() if n >= 2), key=lambda x: (-counts[x] * len(x), x))
    key_ids = {k: i for i, k in enumerate(dictionary)}
    payload = bytearray(u(len(dictionary)))
    for k in dictionary: payload += s(k)
    payload += _enc_node(root, key_ids)
    payload += s(trailing)
    return MAGIC + bytes([VERSION]) + u(len(data)) + bytes(payload)


def _dec_node(data: bytes, p: int, dictionary):
    tag = data[p]; p += 1
    ws, p = g(data, p)
    out = bytearray(ws)
    if tag == T_OBJECT:
        n, p = r(data, p); out += b'{'
        for i in range(n):
            kt, p = data[p], p + 1
            if kt != T_KEY_REF: raise ValueError("bad key tag")
            kws, p = g(data, p); kid, p = r(data, p); cws, p = g(data, p)
            if kid >= len(dictionary): raise ValueError("bad key reference")
            if i: out += b','
            out += kws + dictionary[kid] + cws + b':'
            v, p = _dec_node(data, p, dictionary); out += v
        close, p = g(data, p); out += close + b'}'
    elif tag == T_ARRAY:
        n, p = r(data, p); out += b'['
        for i in range(n):
            v, p = _dec_node(data, p, dictionary)
            if i: out += b','
            out += v
        close, p = g(data, p); out += close + b']'
    elif tag == T_STRING:
        x, p = g(data, p); out += x
    elif tag == T_INT:
        z, p = r(data, p); out += str(uzz(z)).encode()
    elif tag == T_FLOAT:
        x, p = g(data, p); out += x
    elif tag == T_TRUE: out += b'true'
    elif tag == T_FALSE: out += b'false'
    elif tag == T_NULL: out += b'null'
    else: raise ValueError("unknown binary JSON tag")
    return bytes(out), p


def decode(blob: bytes) -> bytes:
    if len(blob) < 6 or blob[:5] != MAGIC or blob[5] != VERSION: raise ValueError("invalid BJSON")
    raw, p = r(blob, 6)
    nd, p = r(blob, p); dictionary = []
    for _ in range(nd):
        x, p = g(blob, p); dictionary.append(x)
    out, p = _dec_node(blob, p, dictionary)
    trailing, p = g(blob, p); out += trailing
    if p != len(blob) or len(out) != raw: raise ValueError("BJSON length mismatch")
    return out
