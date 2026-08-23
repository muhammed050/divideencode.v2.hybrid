"""Typed Binary JSON V2 experiment.

JSON structure is encoded as typed binary nodes. Punctuation is reconstructed
from the tree; whitespace at grammar boundaries and original lexical spellings
are retained so decode(encode(x)) is byte-exact.
"""
from __future__ import annotations

import re
from collections import Counter

MAGIC = b"BJSON"
VERSION = 1
T_OBJECT, T_ARRAY, T_STRING, T_INT, T_FLOAT, T_TRUE, T_FALSE, T_NULL, T_KEY_REF = range(1, 10)
_WS = re.compile(rb"[ \t\r\n]*")
_STR = re.compile(rb'"(?:\\.|[^"\\])*"')
_NUM = re.compile(rb'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')


def u(n: int) -> bytes:
    if n < 0: raise ValueError("negative varint")
    out = bytearray()
    while n >= 128:
        out.append((n & 127) | 128); n >>= 7
    out.append(n); return bytes(out)


def r(data: bytes, p: int):
    n = 0; shift = 0
    while p < len(data):
        b = data[p]; p += 1; n |= (b & 127) << shift
        if not b & 128: return n, p
        shift += 7
    raise ValueError("truncated varint")


def s(x: bytes) -> bytes: return u(len(x)) + x


def g(data: bytes, p: int):
    n, p = r(data, p); e = p + n
    if e > len(data): raise ValueError("truncated bytes")
    return data[p:e], e


def zz(n: int) -> int: return n << 1 if n >= 0 else ((-n << 1) - 1)


def uzz(n: int) -> int: return n >> 1 if not n & 1 else -((n >> 1) + 1)


def _lex(data: bytes):
    p = 0; out = []
    while p < len(data):
        m = _WS.match(data, p); ws = m.group(0); p = m.end()
        if p >= len(data): return out, ws
        c = data[p:p+1]
        if c in b"{}[]:,": tok = c; p += 1
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
    def __init__(self, toks): self.t = toks; self.i = 0
    def peek(self): return self.t[self.i][1] if self.i < len(self.t) else None
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
                cws, _ = self.take()
                val = self.value()
                comma_ws = None
                if self.peek() == b',':
                    comma_ws, _ = self.take()
                    if self.peek() == b'}': raise ValueError("trailing object comma")
                fields.append((kws, key, cws, val, comma_ws))
                if comma_ws is None:
                    if self.peek() != b'}': raise ValueError("missing object comma")
                    close = self.take(); return ("obj", ws, fields, close[0])
        if tok == b'[':
            vals = []
            if self.peek() == b']':
                close = self.take(); return ("arr", ws, vals, close[0])
            while True:
                val = self.value(); comma_ws = None
                if self.peek() == b',':
                    comma_ws, _ = self.take()
                    if self.peek() == b']': raise ValueError("trailing array comma")
                vals.append((val, comma_ws))
                if comma_ws is None:
                    if self.peek() != b']': raise ValueError("missing array comma")
                    close = self.take(); return ("arr", ws, vals, close[0])
        if tok.startswith(b'"'): return ("str", ws, tok)
        if tok == b"true": return ("true", ws)
        if tok == b"false": return ("false", ws)
        if tok == b"null": return ("null", ws)
        if b'.' in tok or b'e' in tok.lower(): return ("float", ws, tok)
        return ("int", ws, int(tok), tok)


def _collect_keys(node, out):
    if node[0] == "obj":
        for f in node[2]: out.append(f[1]); _collect_keys(f[3], out)
    elif node[0] == "arr":
        for v, _ in node[2]: _collect_keys(v, out)


def _enc_node(node, key_ids):
    k = node[0]; out = bytearray()
    if k == "obj":
        out += bytes([T_OBJECT]) + s(node[1]) + u(len(node[2]))
        for kws, key, cws, val, comma_ws in node[2]:
            out += bytes([T_KEY_REF]) + s(kws) + u(key_ids.get(key, 0)) + s(cws)
            if key not in key_ids: out += s(key)
            out += _enc_node(val, key_ids) + s(comma_ws or b"")
        out += s(node[3])
    elif k == "arr":
        out += bytes([T_ARRAY]) + s(node[1]) + u(len(node[2]))
        for val, comma_ws in node[2]: out += _enc_node(val, key_ids) + s(comma_ws or b"")
        out += s(node[3])
    elif k == "str": out += bytes([T_STRING]) + s(node[1]) + s(node[2])
    elif k == "int": out += bytes([T_INT]) + s(node[1]) + u(zz(node[2]))
    elif k == "float": out += bytes([T_FLOAT]) + s(node[1]) + s(node[2])
    elif k == "true": out += bytes([T_TRUE]) + s(node[1])
    elif k == "false": out += bytes([T_FALSE]) + s(node[1])
    elif k == "null": out += bytes([T_NULL]) + s(node[1])
    return bytes(out)


def encode(data: bytes) -> bytes:
    toks, trailing = _lex(data); parser = _Parser(toks); root = parser.value()
    if parser.i != len(toks): raise ValueError("trailing JSON tokens")
    keys = []; _collect_keys(root, keys); counts = Counter(keys)
    dictionary = sorted((k for k, n in counts.items() if n >= 2), key=lambda x: (-counts[x] * len(x), x))
    key_ids = {k: i for i, k in enumerate(dictionary)}
    payload = bytearray(u(len(dictionary)))
    for k in dictionary: payload += s(k)
    payload += _enc_node(root, key_ids) + s(trailing)
    return MAGIC + bytes([VERSION]) + u(len(data)) + bytes(payload)


def _dec_node(data: bytes, p: int, dictionary):
    tag = data[p]; p += 1; ws, p = g(data, p); out = bytearray(ws)
    if tag == T_OBJECT:
        n, p = r(data, p); out += b'{'
        for i in range(n):
            kt, p = data[p], p + 1
            if kt != T_KEY_REF: raise ValueError("bad key tag")
            kws, p = g(data, p); kid, p = r(data, p); cws, p = g(data, p)
            if kid >= len(dictionary):
                key, p = g(data, p)
            else:
                key = dictionary[kid]
            v, p = _dec_node(data, p, dictionary); comma_ws, p = g(data, p)
            out += kws + key + cws + b':' + v
            if comma_ws or i + 1 < n: out += comma_ws + (b',' if i + 1 < n else b'')
        close, p = g(data, p); out += close + b'}'
    elif tag == T_ARRAY:
        n, p = r(data, p); out += b'['
        for i in range(n):
            v, p = _dec_node(data, p, dictionary); comma_ws, p = g(data, p); out += v
            if comma_ws or i + 1 < n: out += comma_ws + (b',' if i + 1 < n else b'')
        close, p = g(data, p); out += close + b']'
    elif tag == T_STRING: x, p = g(data, p); out += x
    elif tag == T_INT: z, p = r(data, p); out += str(uzz(z)).encode()
    elif tag == T_FLOAT: x, p = g(data, p); out += x
    elif tag == T_TRUE: out += b'true'
    elif tag == T_FALSE: out += b'false'
    elif tag == T_NULL: out += b'null'
    else: raise ValueError("unknown binary JSON tag")
    return bytes(out), p


def decode(blob: bytes) -> bytes:
    if len(blob) < 6 or blob[:5] != MAGIC or blob[5] != VERSION: raise ValueError("invalid BJSON")
    raw, p = r(blob, 6); nd, p = r(blob, p); dictionary = []
    for _ in range(nd):
        x, p = g(blob, p); dictionary.append(x)
    out, p = _dec_node(blob, p, dictionary); trailing, p = g(blob, p); out += trailing
    if p != len(blob) or len(out) != raw: raise ValueError("BJSON length mismatch")
    return out
