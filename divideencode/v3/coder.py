"""DE3 real token coder.

The coder is deliberately self-contained and deterministic. It serializes the
V2 LZ token stream, entropy-coding the token/literal alphabet with canonical
Huffman codes and coding match parameters with bounded unsigned Exp-Golomb
codes.  No external compressor is used as an oracle.

This is a research coder, not a frozen container format yet.
"""
from heapq import heapify, heappop, heappush

from ..v2.lz import LIT, MATCH, REP
from ..errors import DivideEncodeError

MAGIC = b"DE3C"
VERSION = 1


def _varint(n):
    if n < 0:
        raise ValueError("varint expects unsigned integer")
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7f) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _read_varint(data, p):
    x = 0
    shift = 0
    while p < len(data):
        b = data[p]
        p += 1
        x |= (b & 0x7f) << shift
        if not b & 0x80:
            return x, p
        shift += 7
        if shift > 63:
            raise DivideEncodeError("varint too long")
    raise DivideEncodeError("truncated varint")


def _codes(freq):
    """Canonical Huffman codes for a {symbol: frequency} mapping."""
    heap = [[w, s, None, None] for s, w in freq.items()]
    if not heap:
        return {}, {}
    if len(heap) == 1:
        s = heap[0][1]
        return {s: (0, 1)}, {1: {0: s}}
    heapify(heap)
    serial = len(heap)
    while len(heap) > 1:
        a = heappop(heap)
        b = heappop(heap)
        node = [a[0] + b[0], serial, a, b]
        serial += 1
        heappush(heap, node)
    root = heap[0]
    lengths = {}

    def walk(node, depth):
        if node[2] is None:
            lengths[node[1]] = depth
        else:
            walk(node[2], depth + 1)
            walk(node[3], depth + 1)
    walk(root, 0)
    if max(lengths.values()) > 255:
        raise DivideEncodeError("Huffman tree too deep")
    ordered = sorted(lengths.items(), key=lambda x: (x[1], x[0]))
    code = 0
    prev = 0
    enc = {}
    dec = {}
    for sym, ln in ordered:
        code <<= ln - prev
        enc[sym] = (code, ln)
        dec.setdefault(ln, {})[code] = sym
        code += 1
        prev = ln
    return enc, dec


class _Bits:
    def __init__(self):
        self.buf = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value, width):
        self.acc = (self.acc << width) | value
        self.n += width
        while self.n >= 8:
            self.n -= 8
            self.buf.append((self.acc >> self.n) & 0xff)
            self.acc &= (1 << self.n) - 1 if self.n else 0

    def finish(self):
        pad = (8 - self.n) & 7
        if self.n:
            self.buf.append((self.acc << pad) & 0xff)
        return bytes(self.buf), pad


def _read_bits(data, bitpos, width):
    v = 0
    for _ in range(width):
        p = bitpos >> 3
        if p >= len(data):
            raise DivideEncodeError("truncated bitstream")
        v = (v << 1) | ((data[p] >> (7 - (bitpos & 7))) & 1)
        bitpos += 1
    return v, bitpos


def _eg_put(bits, value):
    x = value + 1
    k = x.bit_length() - 1
    bits.put(0, k)
    bits.put(x, k + 1)


def _eg_get(data, bitpos):
    z = 0
    while True:
        b, bitpos = _read_bits(data, bitpos, 1)
        if b:
            break
        z += 1
        if z > 63:
            raise DivideEncodeError("invalid Exp-Golomb code")
    tail, bitpos = _read_bits(data, bitpos, z)
    return ((1 << z) | tail) - 1, bitpos


def _freq(tokens):
    f = {}
    for t in tokens:
        if t[0] == LIT:
            s = t[1]
        elif t[0] == MATCH:
            s = 256
        elif t[0] == REP:
            s = 257
        else:
            raise DivideEncodeError("unknown token kind %r" % (t[0],))
        f[s] = f.get(s, 0) + 1
    return f


def encode_tokens(tokens):
    """Encode tokens to a self-contained DE3 bitstream."""
    tokens = list(tokens)
    freq = _freq(tokens)
    codes, _ = _codes(freq)
    bits = _Bits()
    for t in tokens:
        kind = t[0]
        if kind == LIT:
            sym = t[1]
        elif kind == MATCH:
            sym = 256
        else:
            sym = 257
        code, width = codes[sym]
        bits.put(code, width)
        if kind == LIT:
            continue
        if kind == MATCH:
            _eg_put(bits, t[1] - 4)
            _eg_put(bits, t[2] - 1)
        else:
            _eg_put(bits, t[1] - 4)
            _eg_put(bits, t[2])
    payload, pad = bits.finish()

    # Header: magic/version, token count, alphabet entries (symbol+length),
    # payload byte count and final padding count. Frequencies are unnecessary
    # because canonical lengths define the codebook.
    header = bytearray(MAGIC)
    header.append(VERSION)
    header += _varint(len(tokens))
    header += _varint(len(codes))
    for sym, (_, ln) in sorted(codes.items()):
        header += _varint(sym)
        header.append(ln)
    header += _varint(len(payload))
    header.append(pad)
    return bytes(header) + payload


def decode_tokens(blob):
    """Decode a DE3 token bitstream and rebuild the token list."""
    data = memoryview(blob)
    if len(data) < 5 or bytes(data[:4]) != MAGIC or data[4] != VERSION:
        raise DivideEncodeError("invalid DE3 coder header")
    p = 5
    count, p = _read_varint(data, p)
    nsym, p = _read_varint(data, p)
    lengths = {}
    for _ in range(nsym):
        sym, p = _read_varint(data, p)
        if p >= len(data):
            raise DivideEncodeError("truncated DE3 header")
        lengths[sym] = data[p]
        p += 1
    payload_len, p = _read_varint(data, p)
    if p >= len(data):
        raise DivideEncodeError("truncated DE3 header")
    pad = data[p]
    p += 1
    if payload_len != len(data) - p or pad > 7:
        raise DivideEncodeError("invalid DE3 payload")

    ordered = sorted(lengths.items(), key=lambda x: (x[1], x[0]))
    dec = {}
    code = 0
    prev = 0
    for sym, ln in ordered:
        code <<= ln - prev
        dec[(ln, code)] = sym
        code += 1
        prev = ln

    out = []
    bitpos = 0
    end = len(data) * 8 - pad
    while len(out) < count:
        code = 0
        found = None
        for ln in range(1, 256):
            if bitpos >= end:
                raise DivideEncodeError("truncated DE3 tokens")
            b, bitpos = _read_bits(data, bitpos, 1)
            code = (code << 1) | b
            sym = dec.get((ln, code))
            if sym is not None:
                found = sym
                break
        if found is None:
            raise DivideEncodeError("invalid DE3 Huffman code")
        if found < 256:
            out.append((LIT, found))
        elif found == 256:
            length, bitpos = _eg_get(data, bitpos)
            dist, bitpos = _eg_get(data, bitpos)
            out.append((MATCH, length + 4, dist + 1))
        elif found == 257:
            length, bitpos = _eg_get(data, bitpos)
            idx, bitpos = _eg_get(data, bitpos)
            out.append((REP, length + 4, idx))
        else:
            raise DivideEncodeError("invalid DE3 symbol")
    return out


def encoded_size(tokens):
    """Return the exact byte size of the DE3 bitstream."""
    return len(encode_tokens(tokens))


__all__ = ["encode_tokens", "decode_tokens", "encoded_size"]
