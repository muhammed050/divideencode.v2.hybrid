"""DivideEncode HYBRID -- adaptive general-purpose codec.

In addition to the existing LZMA, DELTA+LZMA and raw DE2 lanes, this build
experiments with reversible representations that preserve byte length but
change byte order/word representation before DE2.  The representation itself
is not expected to compress; DE2 is measured on the transformed bytes and the
smallest complete container is selected.  STORED remains the final fallback.
"""
import lzma
import zlib

from ..bitstream import encode_varint, decode_varint
from ..errors import CorruptedError
from . import codec as de2_codec
from .preproc import classify, delta_bytes, undelta_bytes
from .represent import (
    REP_BITPLANE, REP_DELTA16, REP_DELTA32, REP_XOR16,
    NAMES as REPRESENTATION_NAMES,
    apply as apply_representation,
    inverse as inverse_representation,
)

MAGIC = b"DEH1"

METHOD_STORED = 0
METHOD_LZMA = 1
METHOD_DELTA_LZMA = 2
METHOD_DE2 = 3
METHOD_REP_DE2 = 4

_METHOD_NAMES = {
    METHOD_STORED: "STORED",
    METHOD_LZMA: "LZMA",
    METHOD_DELTA_LZMA: "DELTA+LZMA",
    METHOD_DE2: "DE2",
    METHOD_REP_DE2: "REP+DE2",
}

_REPRESENTATIONS = (
    REP_BITPLANE,
    REP_DELTA16,
    REP_DELTA32,
    REP_XOR16,
)


def _lzma_preset(n):
    if n < 4 * 1024 * 1024:
        return 9 | lzma.PRESET_EXTREME
    if n < 32 * 1024 * 1024:
        return 9
    return 6


# Pure-Python DE2 gets expensive on large inputs.  Keep adaptive search
# bounded by default, while allowing callers/benchmarks to force it.
_DE2_SIZE_LIMIT = 2 * 1024 * 1024
_REP_SEARCH_SIZE_LIMIT = 2 * 1024 * 1024


def _looks_numeric_structured(f):
    if f["n"] == 0:
        return False
    return (
        f["bd8_small"] > 0.30
        or f["hi_zero4"] > 0.30 or f["hi_zero2"] > 0.45
        or f["dist2"] <= 24 or f["dist4"] <= 12
    )


def _representation_candidates(data, force=False):
    """Return (rep_id, transformed) candidates worth measuring.

    The transforms are deliberately broad: unlike the old numeric heuristic,
    this lane is an experiment in discovering structure in arbitrary binary
    data.  Invalid word-alignment candidates are skipped.  A cheap size cap
    prevents an accidental O(N) x 4 pure-Python search on very large files.
    """
    if not data or len(data) > _REP_SEARCH_SIZE_LIMIT:
        return ()
    out = []
    for rep in _REPRESENTATIONS:
        transformed = apply_representation(rep, data)
        if transformed != data or force:
            out.append((rep, transformed))
    return tuple(out)


def compress(data, try_de2=None, try_representations=None):
    """Compress `data` and keep the smallest complete candidate.

    `try_representations` controls the new adaptive representation search:
      None  -> automatic, enabled up to the search-size budget
      True  -> force the representation lane
      False -> disable it

    Each representation is lossless and same-length.  Its transformed bytes
    are compressed by DE2, then the representation id is stored in the
    payload so decompression can invert it.  The complete DEH1 header and
    representation byte count toward the comparison, so an intermediate
    representation may grow arbitrarily without being selected unless the
    final container is actually smaller.
    """
    n = len(data)
    orig_crc = zlib.crc32(data) & 0xFFFFFFFF
    header = MAGIC + encode_varint(n) + orig_crc.to_bytes(4, "little")

    candidates = [(METHOD_STORED, data)]

    if n > 0:
        preset = _lzma_preset(n)
        candidates.append((METHOD_LZMA, lzma.compress(data, preset=preset)))

        f = classify(data)
        if _looks_numeric_structured(f):
            delta = delta_bytes(data)
            candidates.append(
                (METHOD_DELTA_LZMA, lzma.compress(delta, preset=preset))
            )

        want_de2 = try_de2 if try_de2 is not None else (n <= _DE2_SIZE_LIMIT)
        if want_de2:
            candidates.append((METHOD_DE2, de2_codec.compress(data)))

        want_rep = (
            try_representations if try_representations is not None
            else (n <= _REP_SEARCH_SIZE_LIMIT)
        )
        if want_rep:
            # Adaptive Representation Search: the intermediate bytes may be
            # larger in a future representation without violating correctness;
            # only the final DE2 payload is compared against all other lanes.
            for rep, transformed in _representation_candidates(
                data, force=bool(try_representations)
            ):
                rep_blob = de2_codec.compress(transformed)
                candidates.append(
                    (METHOD_REP_DE2, bytes((rep,)) + rep_blob)
                )

    method, payload = min(candidates, key=lambda c: len(c[1]))
    out = bytearray(header)
    out.append(method)
    out.extend(payload)
    return bytes(out), _METHOD_NAMES[method]


def compress_blob(data, try_de2=None, try_representations=None):
    blob, _ = compress(
        data,
        try_de2=try_de2,
        try_representations=try_representations,
    )
    return blob


def decompress(blob):
    if blob[:4] != MAGIC:
        raise CorruptedError("bad magic")
    pos = 4
    orig_len, pos = decode_varint(blob, pos, len(blob))
    if pos + 4 > len(blob):
        raise CorruptedError("truncated header")
    orig_crc = int.from_bytes(blob[pos:pos + 4], "little")
    pos += 4
    if pos >= len(blob):
        if orig_len != 0:
            raise CorruptedError("truncated container")
        return b""
    method = blob[pos]
    payload = blob[pos + 1:]

    try:
        if method == METHOD_STORED:
            restored = payload
        elif method == METHOD_LZMA:
            restored = lzma.decompress(payload)
        elif method == METHOD_DELTA_LZMA:
            restored = undelta_bytes(lzma.decompress(payload))
        elif method == METHOD_DE2:
            restored = de2_codec.decompress(payload)
        elif method == METHOD_REP_DE2:
            if not payload:
                raise CorruptedError("missing representation id")
            rep = payload[0]
            transformed = de2_codec.decompress(payload[1:])
            restored = inverse_representation(rep, transformed)
        else:
            raise CorruptedError("unknown method byte: %d" % method)
    except CorruptedError:
        raise
    except Exception as exc:
        raise CorruptedError(
            "payload decode failed (%s: %s)" % (type(exc).__name__, exc)
        ) from exc

    if len(restored) != orig_len:
        raise CorruptedError(
            "length mismatch: expected %d got %d" % (orig_len, len(restored))
        )
    if (zlib.crc32(restored) & 0xFFFFFFFF) != orig_crc:
        raise CorruptedError("crc32 mismatch: corrupted container")
    return restored


def method_name(method):
    """Diagnostic name for a DEH1 method byte."""
    return _METHOD_NAMES.get(method, "UNKNOWN")


def representation_name(rep):
    """Diagnostic name for a representation id."""
    return REPRESENTATION_NAMES.get(rep, "UNKNOWN")
