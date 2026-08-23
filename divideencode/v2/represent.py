"""Reversible representations used by the DE2 adaptive search.

These transforms deliberately preserve byte length.  They are not compressors;
they only change representation so DE2 can sometimes find structure that is
hard to see in the original byte order.
"""

REP_BITPLANE = 1
REP_DELTA16 = 2
REP_DELTA32 = 3
REP_XOR16 = 4

NAMES = {
    REP_BITPLANE: "BITPLANE",
    REP_DELTA16: "DELTA16",
    REP_DELTA32: "DELTA32",
    REP_XOR16: "XOR16",
}


def _delta_words(data, width):
    if len(data) % width:
        return None
    mask = (1 << (width * 8)) - 1
    out = bytearray(data)
    prev = 0
    for i in range(0, len(data), width):
        cur = int.from_bytes(data[i:i + width], "little")
        d = (cur - prev) & mask
        out[i:i + width] = d.to_bytes(width, "little")
        prev = cur
    return bytes(out)


def _undelta_words(data, width):
    if len(data) % width:
        raise ValueError("invalid word-delta length")
    mask = (1 << (width * 8)) - 1
    out = bytearray(data)
    prev = 0
    for i in range(0, len(data), width):
        d = int.from_bytes(data[i:i + width], "little")
        cur = (prev + d) & mask
        out[i:i + width] = cur.to_bytes(width, "little")
        prev = cur
    return bytes(out)


def _xor_words(data, width):
    if len(data) % width:
        return None
    out = bytearray(data)
    prev = 0
    mask = (1 << (width * 8)) - 1
    for i in range(0, len(data), width):
        cur = int.from_bytes(data[i:i + width], "little")
        x = cur ^ prev
        out[i:i + width] = x.to_bytes(width, "little")
        prev = cur & mask
    return bytes(out)


def _unxor_words(data, width):
    if len(data) % width:
        raise ValueError("invalid word-xor length")
    out = bytearray(data)
    prev = 0
    for i in range(0, len(data), width):
        x = int.from_bytes(data[i:i + width], "little")
        cur = x ^ prev
        out[i:i + width] = cur.to_bytes(width, "little")
        prev = cur
    return bytes(out)


def bitplane(data):
    """Transpose bits within each 8-byte group, preserving total length."""
    out = bytearray(len(data))
    for base in range(0, len(data) - len(data) % 8, 8):
        block = data[base:base + 8]
        for bit in range(8):
            v = 0
            for j, b in enumerate(block):
                v |= ((b >> bit) & 1) << j
            out[base + bit] = v
    rem = len(data) % 8
    if rem:
        base = len(data) - rem
        for bit in range(rem):
            v = 0
            for j, b in enumerate(data[base:]):
                v |= ((b >> bit) & 1) << j
            out[base + bit] = v
    return bytes(out)


def unbitplane(data):
    out = bytearray(len(data))
    for base in range(0, len(data) - len(data) % 8, 8):
        for j in range(8):
            v = 0
            for bit in range(8):
                v |= ((data[base + bit] >> j) & 1) << bit
            out[base + j] = v
    rem = len(data) % 8
    if rem:
        base = len(data) - rem
        for j in range(rem):
            v = 0
            for bit in range(rem):
                v |= ((data[base + bit] >> j) & 1) << bit
            out[base + j] = v
    return bytes(out)


def apply(rep, data):
    if rep == REP_BITPLANE:
        return bitplane(data)
    if rep == REP_DELTA16:
        return _delta_words(data, 2)
    if rep == REP_DELTA32:
        return _delta_words(data, 4)
    if rep == REP_XOR16:
        return _xor_words(data, 2)
    raise ValueError("unknown representation: %d" % rep)


def inverse(rep, data):
    if rep == REP_BITPLANE:
        return unbitplane(data)
    if rep == REP_DELTA16:
        return _undelta_words(data, 2)
    if rep == REP_DELTA32:
        return _undelta_words(data, 4)
    if rep == REP_XOR16:
        return _unxor_words(data, 2)
    raise ValueError("unknown representation: %d" % rep)
