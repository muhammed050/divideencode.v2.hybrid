"""Adaptive structural-to-binary representation experiment.

This is deliberately independent of the production DE2 container.  It turns
structured/text input into a compact typed token stream, then callers can feed
that stream to DE2.  The representation is lossless: decoding reproduces the
exact original bytes, including whitespace and punctuation.
"""
from __future__ import annotations

MAGIC = b"ABR1"
VERSION = 1
K_RAW = 0
K_WORD = 1
K_SPACE = 2
K_NUMBER = 3
K_QUOTED = 4
K_PUNCT = 5
K_OTHER = 6


def _v(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative varint")
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7f) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _rv(data: bytes, p: int) -> tuple[int, int]:
    n = 0; s = 0
    while True:
        if p >= len(data): raise ValueError("truncated varint")
        b = data[p]; p += 1
        n |= (b & 0x7f) << s
        if not b & 0x80: return n, p
        s += 7
        if s > 63: raise ValueError("varint overflow")


def _kind(buf: bytes, i: int, mode: str) -> tuple[int, int]:
    c = buf[i]
    if c in b" \t\r\n":
        j = i + 1
        while j < len(buf) and buf[j] in b" \t\r\n": j += 1
        return K_SPACE, j
    if mode == "json" and c == 34:
        j = i + 1; esc = False
        while j < len(buf):
            x = buf[j]
            if esc: esc = False
            elif x == 92: esc = True
            elif x == 34: return K_QUOTED, j + 1
            j += 1
        return K_RAW, len(buf)
    if 48 <= c <= 57 or (c == 45 and i + 1 < len(buf) and 48 <= buf[i+1] <= 57):
        j = i + 1
        while j < len(buf) and (48 <= buf[j] <= 57 or buf[j] in b".+-eE"): j += 1
        return K_NUMBER, j
    if (65 <= c <= 90) or (97 <= c <= 122) or c == 95:
        j = i + 1
        while j < len(buf) and ((65 <= buf[j] <= 90) or (97 <= buf[j] <= 122) or (48 <= buf[j] <= 57) or buf[j] == 95): j += 1
        return K_WORD, j
    if mode == "json" and c in b"{}[],:": return K_PUNCT, i + 1
    return K_OTHER, i + 1


def encode(data: bytes, mode: str = "auto", dictionary_limit: int = 4096) -> bytes:
    data = bytes(data)
    if mode == "auto":
        s = data[:65536]
        stripped = s.lstrip()
        if stripped[:1] in (b"{", b"["): mode = "json"
        elif b"," in s and b"\n" in s: mode = "csv"
        else: mode = "text"
    # Dictionary only stores repeated token payloads; first occurrence is raw.
    freq: dict[bytes, int] = {}
    tokens: list[tuple[int, bytes]] = []
    p = 0
    while p < len(data):
        k, q = _kind(data, p, "json" if mode == "json" else "text")
        payload = data[p:q]
        tokens.append((k, payload)); freq[payload] = freq.get(payload, 0) + 1; p = q
    candidates = [x for x, n in freq.items() if n > 1 and len(x) >= 2]
    candidates.sort(key=lambda x: (-(freq[x] * len(x)), x))
    dictionary = candidates[:dictionary_limit]
    did = {x: i for i, x in enumerate(dictionary)}
    out = bytearray(MAGIC); out.append(VERSION); out += _v(len(data)); out.append({"auto":0,"json":1,"csv":2,"text":3}.get(mode,3)); out += _v(len(dictionary))
    for x in dictionary: out += _v(len(x)); out += x
    out += _v(len(tokens))
    for k, x in tokens:
        out.append(k)
        if x in did:
            out.append(1); out += _v(did[x])
        else:
            out.append(0); out += _v(len(x)); out += x
    return bytes(out)


def decode(blob: bytes) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < 5 or blob[4] != VERSION:
        raise ValueError("invalid ABR1 stream")
    p = 5; original, p = _rv(blob, p); p += 1
    nd, p = _rv(blob, p); dictionary = []
    for _ in range(nd):
        n, p = _rv(blob, p); dictionary.append(blob[p:p+n]); p += n
    nt, p = _rv(blob, p); out = bytearray()
    for _ in range(nt):
        if p >= len(blob): raise ValueError("truncated token")
        p += 1; ref = blob[p]; p += 1
        if ref:
            i, p = _rv(blob, p); out += dictionary[i]
        else:
            n, p = _rv(blob, p); out += blob[p:p+n]; p += n
    if len(out) != original: raise ValueError("ABR1 size mismatch")
    return bytes(out)


def choose_mode(data: bytes) -> str:
    s = data[:65536].lstrip()
    if s[:1] in (b"{", b"["): return "json"
    if b"\n" in s and b"," in s: return "csv"
    return "text"
