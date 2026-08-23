"""DE3-derived merged token coder used by the V3 representation experiment."""
from heapq import heapify, heappop, heappush
import zlib

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
        out.append((n & 0x7f) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _read_varint(data, p):
    value = 0
    shift = 0
    while p < len(data):
        b = data[p]
        p += 1
        value |= (b & 0x7f) << shift
        if not b & 0x80:
            return value, p
        shift += 7
        if shift > 63:
            raise DivideEncodeError("varint too long")
    raise DivideEncodeError("truncated varint")


def _codes(freq):
    """Build deterministic canonical Huffman encoder and decoder maps."""
    if not freq:
        return {}, {}
    if len(freq) == 1:
        sym = next(iter(freq))
        return {sym: (0, 1)}, {(1, 0): sym}

    heap = [[weight, 0, sym, None, None] for sym, weight in sorted(freq.items())]
    heapify(heap)
    serial = 1
    while len(heap) > 1:
        a = heappop(heap)
        b = heappop(heap)
        heappush(heap, [a[0] + b[0], serial, None, a, b])
        serial += 1

    lengths = {}
    stack = [(heap[0], 0)]
    while stack:
        node, depth = stack.pop()
        if node[2] is not None:
            lengths[node[2]] = depth
        else:
            stack.append((node[4], depth + 1))
            stack.append((node[3], depth + 1))

    if max(lengths.values()) > 255:
        raise DivideEncodeError("Huffman tree too deep")

    enc = {}
    dec = {}
    code = 0
    prev = 0
    for sym, length in sorted(lengths.items(), key=lambda x: (x[1], x[0])):
        code <<= length - prev
        enc[sym] = (code, length)
        dec[(length, code)] = sym
        code += 1
        prev = length
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
            self.buf.append((self.acc >> self.n) & 0xff)
            self.acc &= (1 << self.n) - 1 if self.n else 0

    def finish(self):
        pad = (8 - self.n) & 7
        if self.n:
            self.buf.append((self.acc << pad) & 0xff)
        return bytes(self.buf), pad


def _read_bits(data, bitpos, width, end):
    value = 0
    for _ in range(width):
        if bitpos >= end:
            raise DivideEncodeError("truncated bitstream")
        byte = data[bitpos >> 3]
        value = (value << 1) | ((byte >> (7 - (bitpos & 7))) & 1)
        bitpos += 1
    return value, bitpos


def _eg_put(bits, value):
    if value < 0:
        raise ValueError("Exp-Golomb expects unsigned integer")
    x = value + 1
    k = x.bit_length() - 1
    bits.put(0, k)
    bits.put(x, k + 1)


def _eg_get(data, bitpos, end):
    zeros = 0
    while True:
        b, bitpos = _read_bits(data, bitpos, 1, end)
        if b:
            break
        zeros += 1
        if zeros > 63:
            raise DivideEncodeError("invalid Exp-Golomb code")
    tail, bitpos = _read_bits(data, bitpos, zeros, end)
    return ((1 << zeros) | tail) - 1, bitpos


def _freq(tokens):
    freq = {}
    for token in tokens:
        if not token:
            raise DivideEncodeError("empty token")
        kind = token[0]
        if kind == LIT:
            if len(token) != 2 or not 0 <= token[1] <= 255:
                raise DivideEncodeError("invalid literal token")
            sym = token[1]
        elif kind == MATCH:
            if len(token) != 3 or token[1] < MIN_MATCH or token[2] < 1:
                raise DivideEncodeError("invalid match token")
            sym = 256
        elif kind == REP:
            if len(token) != 3 or token[1] < MIN_MATCH or not 0 <= token[2] <= 3:
                raise DivideEncodeError("invalid repeat token")
            sym = 257
        else:
            raise DivideEncodeError("unknown token kind %r" % (kind,))
        freq[sym] = freq.get(sym, 0) + 1
    return freq


def encode_tokens(tokens):
    """Encode a token sequence using one merged canonical-Huffman alphabet."""
    tokens = list(tokens)
    freq = _freq(tokens)
    if not tokens:
        return MAGIC + bytes([VERSION]) + _varint(0) + _varint(0) + _varint(0) + b"\x00" + b"\x00\x00\x00\x00"

    codes, _ = _codes(freq)
    bits = _Bits()
    for token in tokens:
        kind = token[0]
        sym = token[1] if kind == LIT else (256 if kind == MATCH else 257)
        code, width = codes[sym]
        bits.put(code, width)
        if kind == LIT:
            continue
        _eg_put(bits, token[1] - MIN_MATCH)
        _eg_put(bits, token[2] - 1 if kind == MATCH else token[2])

    payload, pad = bits.finish()
    crc = zlib.crc32(payload) & 0xffffffff
    header = bytearray(MAGIC)
    header.append(VERSION)
    header += _varint(len(tokens))
    header += _varint(len(codes))
    for sym, (_, length) in sorted(codes.items()):
        header += _varint(sym)
        header.append(length)
    header += _varint(len(payload))
    header.append(pad)
    header += crc.to_bytes(4, "little")
    return bytes(header) + payload


def decode_tokens(blob):
    """Decode a DE3C stream and rebuild the original token tuples."""
    data = memoryview(blob)
    if len(data) < 5 or bytes(data[:4]) != MAGIC or data[4] != VERSION:
        raise DivideEncodeError("invalid DE3 coder header")

    p = 5
    count, p = _read_varint(data, p)
    nsym, p = _read_varint(data, p)

    if count == 0:
        if nsym != 0:
            raise DivideEncodeError("invalid empty DE3 alphabet")
        payload_len, p = _read_varint(data, p)
        if p + 5 != len(data):
            raise DivideEncodeError("invalid empty DE3 payload")
        pad = data[p]
        p += 1
        if payload_len != 0 or pad != 0 or bytes(data[p:p + 4]) != b"\x00\x00\x00\x00":
            raise DivideEncodeError("invalid empty DE3 payload")
        return []

    if not 1 <= nsym <= 258:
        raise DivideEncodeError("invalid DE3 alphabet size")

    lengths = {}
    for _ in range(nsym):
        sym, p = _read_varint(data, p)
        if sym > 257 or sym in lengths or p >= len(data):
            raise DivideEncodeError("invalid DE3 symbol table")
        length = data[p]
        p += 1
        if length == 0:
            raise DivideEncodeError("invalid DE3 code length")
        lengths[sym] = length

    payload_len, p = _read_varint(data, p)
    if p + 5 > len(data):
        raise DivideEncodeError("truncated DE3 header")
    pad = data[p]
    p += 1
    stored_crc = int.from_bytes(bytes(data[p:p + 4]), "little")
    p += 4
    if pad > 7 or payload_len != len(data) - p or payload_len == 0:
        raise DivideEncodeError("invalid DE3 payload")
    payload = bytes(data[p:p + payload_len])
    if (zlib.crc32(payload) & 0xffffffff) != stored_crc:
        raise DivideEncodeError("DE3 payload checksum mismatch")

    ordered = sorted(lengths.items(), key=lambda x: (x[1], x[0]))
    dec = {}
    code = 0
    prev = 0
    for sym, length in ordered:
        if length < prev:
            raise DivideEncodeError("invalid DE3 code lengths")
        code <<= length - prev
        dec[(length, code)] = sym
        code += 1
        prev = length
    if code > (1 << prev):
        raise DivideEncodeError("oversubscribed DE3 Huffman table")

    bitpos = p * 8
    end = (p + payload_len) * 8 - pad
    out = []
    while len(out) < count:
        code = 0
        found = None
        for length in range(1, 256):
            if bitpos >= end:
                raise DivideEncodeError("truncated DE3 tokens")
            bit, bitpos = _read_bits(data, bitpos, 1, end)
            code = (code << 1) | bit
            found = dec.get((length, code))
            if found is not None:
                break
        if found is None:
            raise DivideEncodeError("invalid DE3 Huffman code")

        if found < 256:
            out.append((LIT, found))
        elif found == 256:
            length, bitpos = _eg_get(data, bitpos, end)
            distance, bitpos = _eg_get(data, bitpos, end)
            out.append((MATCH, length + MIN_MATCH, distance + 1))
        elif found == 257:
            length, bitpos = _eg_get(data, bitpos, end)
            index, bitpos = _eg_get(data, bitpos, end)
            if index > 3:
                raise DivideEncodeError("invalid DE3 repeat index")
            out.append((REP, length + MIN_MATCH, index))
        else:
            raise DivideEncodeError("invalid DE3 symbol")

    if bitpos < end:
        tail, _ = _read_bits(data, bitpos, end - bitpos, end)
        if tail:
            raise DivideEncodeError("non-zero trailing DE3 bits")
    elif bitpos > end:
        raise DivideEncodeError("DE3 payload overrun")

    return out


def encoded_size(tokens):
    return len(encode_tokens(tokens))


__all__ = ["LIT", "MATCH", "REP", "encode_tokens", "decode_tokens", "encoded_size"]