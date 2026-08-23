"""DE3-derived real token coder for the V3 merged-token experiment.

This is the useful part of the DE3 real-coder work, transplanted without
changing the stable V3 production frame. It serializes a token stream using
one merged canonical-Huffman alphabet:

    literal symbols 0..255
    MATCH symbol 256
    REP symbol 257

Match parameters use bounded unsigned Exp-Golomb codes. The coder is
self-contained and deterministic and does not use zlib or another compressor
as an oracle. It is deliberately kept as a research component until the V3
matcher is wired to emit the merged token stream and the new frame is proven
against the full regression suite.

Token tuples are compatible with the historical DE3/V2 tokenizer contract:
    (0, byte_value)             literal
    (1, length, distance)       explicit match
    (2, length, rep_index)      repeat-distance match
"""

from heapq import heapify, heappop, heappush

from ..errors import DivideEncodeError

LIT = 0
MATCH = 1
REP = 2
MIN_MATCH = 4

MAGIC = b"DE3C"
VERSION = 1


def _varint(n):
    if n < 0:
        raise ValueError("varint expects unsigned integer")
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _read_varint(data, p):
    x = 0
    shift = 0
    while p < len(data):
        b = data[p]
        p += 1
        x |= (b & 0x7F) << shift
        if not b & 0x80:
            return x, p
        shift += 7
        if shift > 63:
            raise DivideEncodeError("varint too long")
    raise DivideEncodeError("truncated varint")


def _codes(freq):
    """Return canonical Huffman encoder/decoder maps."""
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

    lengths = {}

    def walk(node, depth):
        if node[2] is None:
            lengths[node[1]] = depth
        else:
            walk(node[2], depth + 1)
            walk(node[3], depth + 1)

    walk(heap[0], 0)
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
        if width < 0 or value < 0 or (width and value >= (1 << width)):
            raise ValueError("bit value does not fit width")
        self.acc = (self.acc << width) | value
        self.n += width
        while self.n >= 8:
            self.n -= 8
            self.buf.append((self.acc >> self.n) & 0xFF)
            self.acc &= (1 << self.n) - 1 if self.n else 0

    def finish(self):
        pad = (8 - self.n) & 7
        if self.n:
            self.buf.append((self.acc << pad) & 0xFF)
        return bytes(self.buf), pad


def _read_bits(data, bitpos, width, end):
    v = 0
    for _ in range(width):
        if bitpos >= end:
            raise DivideEncodeError("truncated bitstream")
        p = bitpos >> 3
        v = (v << 1) | ((data[p] >> (7 - (bitpos & 7))) & 1)
        bitpos += 1
    return v, bitpos


def _eg_put(bits, value):
    if value < 0:
        raise ValueError("Exp-Golomb expects unsigned integer")
    x = value + 1
    k = x.bit_length() - 1
    bits.put(0, k)
    bits.put(x, k + 1)


def _eg_get(data, bitpos, end):
    z = 0
    while True:
        b, bitpos = _read_bits(data, bitpos, 1, end)
        if b:
            break
        z += 1
        if z > 63:
            raise DivideEncodeError("invalid Exp-Golomb code")
    tail, bitpos = _read_bits(data, bitpos, z, end)
    return ((1 << z) | tail) - 1, bitpos


def _freq(tokens):
    f = {}
    for t in tokens:
        if not t:
            raise DivideEncodeError("empty token")
        kind = t[0]
        if kind == LIT:
            if len(t) != 2 or not 0 <= t[1] <= 255:
                raise DivideEncodeError("invalid literal token")
            sym = t[1]
        elif kind == MATCH:
            if len(t) != 3 or t[1] < MIN_MATCH or t[2] < 1:
                raise DivideEncodeError("invalid match token")
            sym = 256
        elif kind == REP:
            if len(t) != 3 or t[1] < MIN_MATCH or not 0 <= t[2] <= 3:
                raise DivideEncodeError("invalid rep token")
            sym = 257
        else:
            raise DivideEncodeError("unknown token kind %r" % (kind,))
        f[sym] = f.get(sym, 0) + 1
    return f


def encode_tokens(tokens):
    """Encode tokens to a self-contained deterministic DE3C bitstream."""
    tokens = list(tokens)
    freq = _freq(tokens)
    codes, _ = _codes(freq)
    bits = _Bits()

    for t in tokens:
        kind = t[0]
        sym = t[1] if kind == LIT else (256 if kind == MATCH else 257)
        code, width = codes[sym]
        bits.put(code, width)
        if kind == LIT:
            continue
        _eg_put(bits, t[1] - MIN_MATCH)
        _eg_put(bits, t[2] - 1 if kind == MATCH else t[2])

    payload, pad = bits.finish()
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
    """Decode a DE3C bitstream and rebuild the token list."""
    data = memoryview(blob)
    if len(data) < 5 or bytes(data[:4]) != MAGIC or data[4] != VERSION:
        raise DivideEncodeError("invalid DE3 coder header")

    p = 5
    count, p = _read_varint(data, p)
    nsym, p = _read_varint(data, p)
    if nsym == 0 or nsym > 258:
        raise DivideEncodeError("invalid DE3 alphabet size")

    lengths = {}
    for _ in range(nsym):
        sym, p = _read_varint(data, p)
        if sym > 257 or p >= len(data):
            raise DivideEncodeError("invalid DE3 symbol table")
        ln = data[p]
        p += 1
        if ln == 0 or sym in lengths:
            raise DivideEncodeError("invalid DE3 code length")
        lengths[sym] = ln

    payload_len, p = _read_varint(data, p)
    if p >= len(data):
        raise DivideEncodeError("truncated DE3 header")
    pad = data[p]
    p += 1
    if pad > 7 or payload_len != len(data) - p:
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
    if code > (1 << prev):
        raise DivideEncodeError("oversubscribed DE3 Huffman table")

    out = []
    bitpos = 0
    end = len(data) * 8 - pad
    while len(out) < count:
        code = 0
        found = None
        for ln in range(1, 256):
            if bitpos >= end:
                raise DivideEncodeError("truncated DE3 tokens")
            b, bitpos = _read_bits(data, bitpos, 1, end)
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
            length, bitpos = _eg_get(data, bitpos, end)
            dist, bitpos = _eg_get(data, bitpos, end)
            out.append((MATCH, length + MIN_MATCH, dist + 1))
        elif found == 257:
            length, bitpos = _eg_get(data, bitpos, end)
            idx, bitpos = _eg_get(data, bitpos, end)
            if idx > 3:
                raise DivideEncodeError("invalid DE3 repeat index")
            out.append((REP, length + MIN_MATCH, idx))
        else:
            raise DivideEncodeError("invalid DE3 symbol")

    if bitpos != end:
        # The encoder emits no data after the declared token sequence. Padding
        # is the only permitted tail; reject real trailing bits to avoid
        # accepting ambiguous/corrupted streams.
        remaining = end - bitpos
        if remaining > 0:
            tail, _ = _read_bits(data, bitpos, remaining, end)
            if tail:
                raise DivideEncodeError("non-zero trailing DE3 bits")

    return out


def encoded_size(tokens):
    """Return the exact serialized size of the DE3C token stream."""
    return len(encode_tokens(tokens))


__all__ = ["LIT", "MATCH", "REP", "encode_tokens", "decode_tokens", "encoded_size"]
