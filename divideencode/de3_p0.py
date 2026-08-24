from __future__ import annotations

import binascii
import heapq
import struct
from collections import Counter

MAGIC = b"DE3P"
VERSION = 1
MAX_DISTANCE = 65535
MIN_MATCH = 3
MAX_MATCH = 258

# Deflate-like length and distance buckets, used only as a compact symbol model.
LEN_BASE = [3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258]
LEN_EXTRA = [0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0]
DIST_BASE = [1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577]
DIST_EXTRA = [0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13]


def _bucket(value, bases, extras):
    for i in range(len(bases)-1, -1, -1):
        if value >= bases[i]:
            return i, value - bases[i], extras[i]
    raise ValueError(value)


def _value(sym, bases, extras, extra):
    if not 0 <= sym < len(bases):
        raise ValueError("bad symbol")
    return bases[sym] + extra


def _huffman_lengths(freq, max_symbols):
    heap = [(n, s, None, None) for s, n in enumerate(freq) if n]
    if not heap:
        return [0] * max_symbols
    if len(heap) == 1:
        out = [0] * max_symbols
        out[heap[0][1]] = 1
        return out
    heapq.heapify(heap)
    serial = max_symbols
    while len(heap) > 1:
        a = heapq.heappop(heap)
        b = heapq.heappop(heap)
        node = (a[0] + b[0], serial, a, b)
        serial += 1
        heapq.heappush(heap, node)
    root = heap[0]
    lengths = [0] * max_symbols
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if node[2] is None and node[3] is None:
            lengths[node[1]] = max(1, depth)
        else:
            stack.append((node[2], depth + 1))
            stack.append((node[3], depth + 1))
    return lengths


def _canonical(lengths):
    pairs = sorted((n, s) for s, n in enumerate(lengths) if n)
    codes = {}
    code = 0
    prev = 0
    for n, s in pairs:
        code <<= n - prev
        codes[s] = (code, n)
        code += 1
        prev = n
    return codes


class _Writer:
    def __init__(self):
        self.buf = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value, bits):
        self.acc = (self.acc << bits) | value
        self.n += bits
        while self.n >= 8:
            self.n -= 8
            self.buf.append((self.acc >> self.n) & 255)
            self.acc &= (1 << self.n) - 1 if self.n else 0

    def finish(self):
        if self.n:
            self.buf.append((self.acc << (8 - self.n)) & 255)
        return bytes(self.buf), self.n


class _Reader:
    def __init__(self, data, valid_last_bits=0):
        self.data = data
        self.i = 0
        self.acc = 0
        self.n = 0
        self.valid_last_bits = valid_last_bits

    def get(self, bits):
        while self.n < bits:
            if self.i >= len(self.data):
                raise ValueError("truncated bitstream")
            self.acc = (self.acc << 8) | self.data[self.i]
            self.i += 1
            self.n += 8
        self.n -= bits
        value = self.acc >> self.n
        self.acc &= (1 << self.n) - 1 if self.n else 0
        return value


def _encode_huffman(symbols, lengths, writer):
    codes = _canonical(lengths)
    for s in symbols:
        code, n = codes[s]
        writer.put(code, n)


def _decode_symbol(reader, lengths, table):
    code = 0
    for n in range(1, max(lengths) + 1):
        code = (code << 1) | reader.get(1)
        s = table.get((code, n))
        if s is not None:
            return s
    raise ValueError("invalid Huffman code")


def _table(lengths):
    codes = _canonical(lengths)
    return {(c, n): s for s, (c, n) in codes.items()}


def _tokens(data):
    # Hash-chain LZ parser. Bounded chain keeps Python runtime predictable.
    n = len(data)
    head = {}
    prev = [-1] * n
    out = []
    i = 0
    while i < n:
        best_len = 0
        best_dist = 0
        if i + MIN_MATCH <= n:
            key = data[i:i+3]
            p = head.get(key, -1)
            steps = 0
            while p >= 0 and i - p <= MAX_DISTANCE and steps < 48:
                max_len = min(MAX_MATCH, n - i)
                if data[p:p+max_len] == data[i:i+max_len]:
                    l = MIN_MATCH
                    while l < max_len and data[p+l] == data[i+l]:
                        l += 1
                    if l > best_len:
                        best_len, best_dist = l, i - p
                        if l == MAX_MATCH:
                            break
                p = prev[p]
                steps += 1
        if best_len >= MIN_MATCH:
            out.append((1, best_len, best_dist))
            for j in range(i, min(i + best_len, n)):
                if j + 3 <= n:
                    k = data[j:j+3]
                    prev[j] = head.get(k, -1)
                    head[k] = j
            i += best_len
        else:
            out.append((0, data[i], 0))
            if i + 3 <= n:
                k = data[i:i+3]
                prev[i] = head.get(k, -1)
                head[k] = i
            i += 1
    return out


def _build_symbols(tokens):
    ll = []
    dd = []
    for kind, a, b in tokens:
        if kind == 0:
            ll.append(a)
        else:
            ls, _, _ = _bucket(a, LEN_BASE, LEN_EXTRA)
            ds, _, _ = _bucket(b, DIST_BASE, DIST_EXTRA)
            ll.append(256 + ls)
            dd.append(ds)
    return ll, dd


def compress(data: bytes) -> bytes:
    data = bytes(data)
    if not data:
        return MAGIC + struct.pack(">BBQIIB", VERSION, 0, 0, 0, 0, 0)
    tokens = _tokens(data)
    ll, dd = _build_symbols(tokens)
    lf = Counter(ll)
    df = Counter(dd)
    ll_lengths = _huffman_lengths([lf.get(i, 0) for i in range(286)], 286)
    d_lengths = _huffman_lengths([df.get(i, 0) for i in range(30)], 30)
    ll_codes = _canonical(ll_lengths)
    d_codes = _canonical(d_lengths)
    w = _Writer()
    di = 0
    for kind, a, b in tokens:
        if kind == 0:
            c, n = ll_codes[a]
            w.put(c, n)
        else:
            ls, extra, ebits = _bucket(a, LEN_BASE, LEN_EXTRA)
            c, n = ll_codes[256 + ls]
            w.put(c, n)
            if ebits:
                w.put(extra, ebits)
            ds, extra, ebits = _bucket(b, DIST_BASE, DIST_EXTRA)
            c, n = d_codes[ds]
            w.put(c, n)
            if ebits:
                w.put(extra, ebits)
            di += 1
    bitstream, tail = w.finish()
    header = MAGIC + struct.pack(">BBQIIBHH", VERSION, 0, len(data), binascii.crc32(data) & 0xffffffff, len(tokens), tail, 286, 30)
    return header + bytes(ll_lengths) + bytes(d_lengths) + bitstream


def decompress(blob: bytes) -> bytes:
    blob = bytes(blob)
    fixed = struct.calcsize(">BBQIIBHH")
    if len(blob) < 4 + fixed or blob[:4] != MAGIC:
        raise ValueError("bad DE3-P0 header")
    off = 4
    version, flags, size, crc, token_count, tail, nll, nd = struct.unpack_from(">BBQIIBHH", blob, off)
    off += fixed
    if version != VERSION or nll != 286 or nd != 30 or tail > 7:
        raise ValueError("unsupported DE3-P0 stream")
    if len(blob) < off + nll + nd:
        raise ValueError("truncated DE3-P0 header")
    ll_lengths = list(blob[off:off+nll]); off += nll
    d_lengths = list(blob[off:off+nd]); off += nd
    if any(x == 0 for x in ll_lengths) and not any(ll_lengths):
        raise ValueError("empty literal/length tree")
    if not any(d_lengths) and token_count:
        raise ValueError("missing distance tree")
    ll_table = _table(ll_lengths)
    d_table = _table(d_lengths) if any(d_lengths) else {}
    r = _Reader(blob[off:], tail)
    out = bytearray()
    for _ in range(token_count):
        sym = _decode_symbol(r, ll_lengths, ll_table)
        if sym < 256:
            out.append(sym)
        elif sym < 286:
            ls = sym - 256
            eb = LEN_EXTRA[ls]
            extra = r.get(eb) if eb else 0
            length = _value(ls, LEN_BASE, LEN_EXTRA, extra)
            ds = _decode_symbol(r, d_lengths, d_table)
            deb = DIST_EXTRA[ds]
            de = r.get(deb) if deb else 0
            dist = _value(ds, DIST_BASE, DIST_EXTRA, de)
            if dist > len(out) or len(out) + length > size:
                raise ValueError("invalid match")
            start = len(out) - dist
            for j in range(length):
                out.append(out[start + j])
        else:
            raise ValueError("invalid literal/length symbol")
    if len(out) != size or (binascii.crc32(out) & 0xffffffff) != crc:
        raise ValueError("DE3-P0 checksum/size mismatch")
    return bytes(out)
