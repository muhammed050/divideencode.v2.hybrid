"""UBIR V1.6: DE2-oriented typed lanes.

Research candidate derived from V1.3AB. The semantic transform is unchanged:
dictionary strings, compact punctuation/constants, and integer delta+ZigZag.
The new experiment changes only the physical layout presented to DE2:

* token classes are packed at 3 bits/token instead of one tag byte/token;
* payloads are split into homogeneous lanes (punct/dict/string/int/raw/const);
* the class stream reconstructs the original token order exactly.
"""
from __future__ import annotations
from . import ubir_v13ab as base
from . import universal_binary_ir as v1

PUNCT, DICT, STRING, INT, RAW, CONST = range(6)
PUNCTS = base.PUNCTS
PMAP = base.PMAP
CONST_MAP = {b"true": 0, b"false": 1, b"null": 2}
CONST_REV = (b"true", b"false", b"null")


def _pack3(values: list[int]) -> bytes:
    out = bytearray((len(values) * 3 + 7) // 8)
    bit = 0
    for x in values:
        x &= 7
        byte = bit >> 3
        shift = bit & 7
        value = x << shift
        out[byte] |= value & 0xFF
        if shift > 5:
            out[byte + 1] |= (value >> 8) & 0xFF
        bit += 3
    return bytes(out)


def _unpack3(data: bytes, count: int) -> list[int]:
    out = []
    bit = 0
    for _ in range(count):
        byte = bit >> 3
        shift = bit & 7
        x = data[byte] >> shift
        if shift > 5:
            x |= data[byte + 1] << (8 - shift)
        out.append(x & 7)
        bit += 3
    return out


def _pack2(values: list[int]) -> bytes:
    out = bytearray((len(values) * 2 + 7) // 8)
    for i, x in enumerate(values):
        out[i >> 2] |= (x & 3) << ((i & 3) * 2)
    return bytes(out)


def _unpack2(data: bytes, count: int) -> list[int]:
    return [(data[i >> 2] >> ((i & 3) * 2)) & 3 for i in range(count)]


def encode_json(data: bytes) -> bytes:
    tokens = v1._json_tokens(data)
    from collections import Counter
    strings = Counter(t for t in tokens if t[:1] == b'"')
    dictionary = sorted((x for x, n in strings.items() if n >= 2), key=lambda x: (-strings[x] * len(x), x))
    ids = {x: i for i, x in enumerate(dictionary)}
    classes = []
    punct = bytearray(); dict_lane = bytearray(); string_lane = bytearray(); int_lane = bytearray(); raw_lane = bytearray(); const_codes = []
    prev_int = 0
    for t in tokens:
        if t[:1] in b"{}[],:":
            classes.append(PUNCT); punct.append(PMAP[t[0]])
        elif t[:1] == b'"':
            i = ids.get(t)
            if i is None: classes.append(STRING); string_lane += v1._s(t)
            else: classes.append(DICT); dict_lane += v1._u(i)
        elif v1._JSON_INT.fullmatch(t.decode("ascii")):
            classes.append(INT); value = int(t); int_lane += v1._u(v1._zz(value - prev_int)); prev_int = value
        elif t in CONST_MAP:
            classes.append(CONST); const_codes.append(CONST_MAP[t])
        else:
            classes.append(RAW); raw_lane += v1._s(t)
    class_bytes = _pack3(classes)
    lanes = (punct, dict_lane, string_lane, int_lane, raw_lane, bytearray(_pack2(const_codes)))
    out = bytearray(v1._u(len(dictionary)))
    for s in dictionary: out += v1._s(s)
    out += v1._u(len(tokens))
    out += v1._u(len(class_bytes)) + class_bytes
    out += v1._u(len(const_codes))
    for lane in lanes: out += v1._u(len(lane))
    for lane in lanes: out += lane
    return bytes(out)


def decode_json(payload: bytes) -> bytes:
    p = 0
    n, p = v1._r(payload, p)
    dictionary = []
    for _ in range(n):
        x, p = v1._g(payload, p); dictionary.append(x)
    count, p = v1._r(payload, p)
    class_len, p = v1._r(payload, p)
    if p + class_len > len(payload): raise ValueError("truncated class stream")
    classes = _unpack3(payload[p:p + class_len], count); p += class_len
    const_count, p = v1._r(payload, p)
    lengths = []
    for _ in range(6):
        x, p = v1._r(payload, p); lengths.append(x)
    lanes = []
    for nbytes in lengths:
        if p + nbytes > len(payload): raise ValueError("truncated lane")
        lanes.append(payload[p:p + nbytes]); p += nbytes
    if p != len(payload): raise ValueError("trailing UBIR V1.6 bytes")
    pp = pd = ps = pi = pr = pc = 0
    if len(lanes[5]) != (const_count * 2 + 7) // 8: raise ValueError("bad constant lane")
    const_codes = _unpack2(lanes[5], const_count)
    out = bytearray(); prev_int = 0
    for tag in classes:
        if tag == PUNCT:
            if pp >= len(lanes[0]): raise ValueError("truncated punctuation lane")
            x = lanes[0][pp]; pp += 1
            if x >= len(PUNCTS): raise ValueError("bad punctuation code")
            out.append(PUNCTS[x])
        elif tag == DICT:
            i, pd = v1._r(lanes[1], pd)
            if i >= len(dictionary): raise ValueError("bad dictionary reference")
            out += dictionary[i]
        elif tag == STRING:
            x, ps = v1._g(lanes[2], ps); out += x
        elif tag == INT:
            z, pi = v1._r(lanes[3], pi); prev_int += v1._uzz(z); out += str(prev_int).encode("ascii")
        elif tag == RAW:
            x, pr = v1._g(lanes[4], pr); out += x
        elif tag == CONST:
            if pc >= const_count: raise ValueError("truncated constant lane")
            code = const_codes[pc]; pc += 1
            if code >= len(CONST_REV): raise ValueError("bad constant code")
            out += CONST_REV[code]
        else: raise ValueError("unknown UBIR V1.6 class")
    if (pp, pd, ps, pi, pr) != tuple(len(x) for x in lanes[:5]): raise ValueError("lane accounting mismatch")
    if pc != const_count: raise ValueError("constant accounting mismatch")
    return bytes(out)


def encode(data: bytes, kind: str) -> bytes:
    if kind != "json": raise ValueError("UBIR V1.6 currently supports JSON only")
    return v1.MAGIC + bytes([v1.VERSION, v1.K_JSON]) + v1._u(len(data)) + encode_json(data)


def decode(blob: bytes) -> bytes:
    if len(blob) < 6 or blob[:4] != v1.MAGIC or blob[4] != v1.VERSION or blob[5] != v1.K_JSON:
        raise ValueError("invalid UBIR V1.6 blob")
    raw, p = v1._r(blob, 6); out = decode_json(blob[p:])
    if len(out) != raw: raise ValueError("UBIR V1.6 length mismatch")
    return out
