"""DE2 reversible transforms (M3/M4)."""
import array
import sys

from ..errors import CorruptedError
from . import lz

WORD_SIZES = (1, 2, 4)
_TYPECODES = {2: "H", 4: "I"}


def _mask(w):
    return (1 << (8 * w)) - 1


def _words(data, w):
    nw = len(data) // w
    if w == 1:
        return data[:nw]
    a = array.array(_TYPECODES[w])
    a.frombytes(bytes(data[:nw * w]))
    if sys.byteorder != "little":
        a.byteswap()
    return a


def _unwords(vals, w):
    if w == 1:
        return bytes(vals)
    a = array.array(_TYPECODES[w], vals)
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


def _delta_core(data, w, zigzag):
    """Encode word deltas using a preallocated byte buffer.

    The old implementation created a new Python bytes object with
    ``int.to_bytes`` for every word. For multi-megabyte blocks that creates
    millions of temporary objects. Slice assignment keeps the same exact
    wire format while reducing allocation/GC overhead substantially.
    """
    vals = _words(data, w)
    nw = len(vals)
    usable = nw * w
    tail = data[usable:]
    if not nw:
        return bytes(tail)

    mask = _mask(w)
    bits = 8 * w
    half = 1 << (bits - 1)
    full = 1 << bits
    out = bytearray(usable + len(tail))

    prev = int(vals[0])
    out[:w] = prev.to_bytes(w, "little")
    pos = w
    for j in range(1, nw):
        x = int(vals[j])
        d = (x - prev) & mask
        if zigzag:
            sd = d - full if d >= half else d
            d = ((sd << 1) ^ (sd >> bits)) & mask
        out[pos:pos + w] = d.to_bytes(w, "little")
        pos += w
        prev = x

    out[usable:] = tail
    return bytes(out)


def _undelta_core(payload, w, zigzag):
    vals = _words(payload, w)
    nw = len(vals)
    usable = nw * w
    tail = payload[usable:]
    if not nw:
        return bytes(tail)

    mask = _mask(w)
    out = bytearray(usable + len(tail))
    prev = int(vals[0])
    out[:w] = prev.to_bytes(w, "little")
    pos = w
    for j in range(1, nw):
        d = int(vals[j])
        if zigzag:
            sd = (d >> 1) ^ -(d & 1)
            prev = (prev + sd) & mask
        else:
            prev = (prev + d) & mask
        out[pos:pos + w] = prev.to_bytes(w, "little")
        pos += w
    out[usable:] = tail
    return bytes(out)


def _plane_split(data, sw):
    usable = (len(data) // sw) * sw
    parts = [data[i:usable:sw] for i in range(sw)]
    return b"".join(parts) + bytes(data[usable:])


def _plane_join(data, sw, orig_len):
    usable = (orig_len // sw) * sw
    per = usable // sw
    out = bytearray(orig_len)
    for i in range(sw):
        out[i:usable:sw] = data[i * per:(i + 1) * per]
    out[usable:] = data[sw * per:]
    return bytes(out)


def delta_encode(data, w=4, zigzag=True):
    if w not in WORD_SIZES:
        raise ValueError("invalid delta word width %r" % (w,))
    return _delta_core(data, w, zigzag), b"D" + bytes((WORD_SIZES.index(w), 1 if zigzag else 0))


def numeric_encode(data, mono=None, hi_gain=None, _enc=None):
    """Bounded numeric search with cheap LZ screening."""
    if _enc is None:
        _enc = lz.encode

    if hi_gain is not None and hi_gain >= 2.0:
        order = (1, 4, 2)
    elif mono is not None and mono >= 0.85:
        order = (4, 2, 1)
    else:
        order = (2, 4, 1)

    candidates = []
    for w in order:
        transformed = _delta_core(data, w, True)
        try:
            screened = lz.encode_v2(transformed, level="FAST")
        except AttributeError:
            screened = lz.encode(transformed, level="FAST")
        candidates.append((len(screened), w, transformed))

    candidates.sort(key=lambda x: x[0])
    _, best_w, best_transformed = candidates[0]
    best_frame = _enc(best_transformed)
    best_tmeta = b"D" + bytes((WORD_SIZES.index(best_w), 1))

    if best_w >= 2:
        split = _plane_split(best_transformed, best_w)
        try:
            split_screen = lz.encode_v2(split, level="FAST")
        except AttributeError:
            split_screen = lz.encode(split, level="FAST")
        if len(split_screen) < len(best_frame):
            frame = _enc(split)
            if len(frame) < len(best_frame):
                best_frame = frame
                best_tmeta = b"C" + bytes((WORD_SIZES.index(best_w), 1,
                                           WORD_SIZES.index(best_w)))

    return best_frame, best_tmeta


def transform_decode(payload, tmeta, orig_len):
    if not tmeta:
        raise CorruptedError("missing transform metadata")
    kind = tmeta[0:1]
    if kind == b"D":
        if len(tmeta) != 3:
            raise CorruptedError("bad delta tmeta")
        wcode, zz = tmeta[1], tmeta[2]
        if wcode >= len(WORD_SIZES):
            raise CorruptedError("bad delta word code")
        return _undelta_core(payload, WORD_SIZES[wcode], bool(zz))
    if kind == b"C":
        if len(tmeta) != 4:
            raise CorruptedError("bad composite tmeta")
        wcode, zz, scode = tmeta[1], tmeta[2], tmeta[3]
        if wcode >= len(WORD_SIZES) or scode >= len(WORD_SIZES):
            raise CorruptedError("bad composite codes")
        joined = _plane_join(payload, WORD_SIZES[scode], orig_len)
        return _undelta_core(joined, WORD_SIZES[wcode], bool(zz))
    raise CorruptedError("unknown transform kind %r" % (kind,))


def delta_decode(payload, tmeta):
    return transform_decode(payload, tmeta, len(payload))
