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
        return list(data[:nw])
    a = array.array(_TYPECODES[w])
    a.frombytes(bytes(data[:nw * w]))
    if sys.byteorder != "little":
        a.byteswap()
    return a


def _unwords(vals, w):
    if w == 1:
        return bytes(bytearray(vals))
    a = array.array(_TYPECODES[w], vals)
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


def _delta_core(data, w, zigzag):
    vals = _words(data, w)
    nw = len(vals)
    tail = bytes(data[nw * w:])
    mask = _mask(w)
    out = bytearray()
    if nw:
        prev = int(vals[0])
        out += prev.to_bytes(w, "little")
        half = 1 << (8 * w - 1)
        full = 1 << (8 * w)
        for j in range(1, nw):
            x = int(vals[j])
            d = (x - prev) & mask
            if zigzag:
                sd = d - full if d >= half else d
                d = ((sd << 1) ^ (sd >> (8 * w))) & mask
            out += d.to_bytes(w, "little")
            prev = x
    return bytes(out) + tail


def _undelta_core(payload, w, zigzag):
    vals = _words(payload, w)
    nw = len(vals)
    tail = payload[nw * w:]
    mask = _mask(w)
    out = bytearray()
    if nw:
        prev = int(vals[0])
        out += prev.to_bytes(w, "little")
        for j in range(1, nw):
            d = int(vals[j])
            if zigzag:
                sd = (d >> 1) ^ -(d & 1)
                prev = (prev + sd) & mask
            else:
                prev = (prev + d) & mask
            out += prev.to_bytes(w, "little")
    return bytes(out) + bytes(tail)


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
    """Bounded numeric search with cheap LZ screening.

    Candidate transforms are first ranked using FAST LZ. Only the best
    transform is then encoded with the caller's real codec/level. This
    keeps the BALANCED/MAX output quality while removing most expensive
    repeated deep LZ searches from the candidate-selection phase.
    """
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
        # Screening is deliberately FAST. The actual winner is re-encoded
        # below with the original codec so BALANCED/MAX quality is retained.
        try:
            screened = lz.encode_v2(transformed, level="FAST")
        except AttributeError:
            screened = lz.encode(transformed, level="FAST")
        candidates.append((len(screened), w, transformed))

    candidates.sort(key=lambda x: x[0])
    _, best_w, best_transformed = candidates[0]
    best_frame = _enc(best_transformed)
    best_tmeta = b"D" + bytes((WORD_SIZES.index(best_w), 1))

    # Only test the plane split when the FAST screen says it has a realistic
    # chance to beat the selected delta. This is a cheap transform, while a
    # second full DE2/LZ encode is not.
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
