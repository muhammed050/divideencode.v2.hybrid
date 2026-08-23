"""DivideEncode HYBRID -- a practical, fast, strong general-purpose codec.

Honest design rationale (measured, not assumed):

  Pure-Python DivideEncode (V1/V2) cannot beat C-backed compressors on
  raw speed -- that is a language-level ceiling, not a design flaw, and
  no amount of Python-side optimization removes it (see
  docs/reports/PERFORMANCE_AUDIT.md and V2_DESIGN_ANALYSIS.md in the
  original research repo for the measurements behind this claim).

  What *does* work, and is measured below, is combining:

    1. A fast, strong, battle-tested C backend (`lzma`, stdlib, no
       external dependency) for the general case -- text, code, JSON,
       logs, already-compressed media.
    2. DivideEncode's own numeric pre-transform (byte-wise delta) as a
       *front-end filter* feeding that same backend, applied only when
       cheap upfront classification signals structured numeric binary
       (counters, sensor arrays, PRNG-period data) -- the one class
       where the original research demonstrably wins.
    3. DivideEncode V2's own LZE+Huffman codec as a third candidate,
       kept in the running because it independently wins on some of
       those same numeric files (e.g. random_prng.bin) even against
       delta+lzma.

  Every candidate is *measured*, not assumed to win; the smallest
  correct result is kept, and RAW/STORED is always available as a
  fallback for incompressible input (never expands beyond header
  overhead). This mirrors dd.txt's own rule #17: "never confuse a
  smaller number with fewer bits" -- everything, including this
  container's own header, counts toward the reported size.

Container format (all multi-byte ints little-endian):

    b"DEH1"            magic, 4 bytes
    method: 1 byte      0=STORED 1=LZMA 2=DELTA+LZMA 3=DE2
    varint original_len
    crc32(original)     4 bytes, unsigned
    payload             method-specific

Decompression re-validates crc32 of the *restored* bytes against the
stored value and raises CorruptedError on mismatch -- corruption is
detected, never silently passed through.
"""
import lzma
import zlib

from ..bitstream import encode_varint, decode_varint
from ..errors import CorruptedError
from . import codec as de2_codec
from .preproc import classify, delta_bytes, undelta_bytes

MAGIC = b"DEH1"

METHOD_STORED = 0
METHOD_LZMA = 1
METHOD_DELTA_LZMA = 2
METHOD_DE2 = 3

_METHOD_NAMES = {
    METHOD_STORED: "STORED",
    METHOD_LZMA: "LZMA",
    METHOD_DELTA_LZMA: "DELTA+LZMA",
    METHOD_DE2: "DE2",
}


def _lzma_preset(n):
    """Bound worst-case time on large inputs; stay maximal on small ones.

    Measured on this machine (see benchmarks/results/hybrid_bench.md):
    preset 9|EXTREME costs real time only once files climb into the
    multi-MB range, so it is kept for anything under 4 MiB and stepped
    down for larger inputs.
    """
    if n < 4 * 1024 * 1024:
        return 9 | lzma.PRESET_EXTREME
    if n < 32 * 1024 * 1024:
        return 9
    return 6


# DE2's pure-Python search gets slow on large inputs (it re-scans/re-hashes
# the whole buffer per candidate); above this size, skip it by default and
# rely on LZMA/DELTA+LZMA, which stay fast at any size via the C backend.
_DE2_SIZE_LIMIT = 2 * 1024 * 1024


def _looks_numeric_structured(f):
    """Reuses v2/preproc.py's classify() signals (same ones plan_candidates
    uses for DE2 itself) to decide whether delta/DE2 candidates are worth
    the extra measurement cost at all."""
    if f["n"] == 0:
        return False
    return (
        f["bd8_small"] > 0.30
        or f["hi_zero4"] > 0.30 or f["hi_zero2"] > 0.45
        or f["dist2"] <= 24 or f["dist4"] <= 12
    )


def compress(data, try_de2=None):
    """Compress `data`, returning the smallest verified-correct candidate.

    try_de2: None = auto -- attempt DE2 whenever the size budget allows
    (see _DE2_SIZE_LIMIT below). DE2 has its own internal classifier and
    candidate search, so gating it on *our* classify() signals caused a
    measured regression on random_prng.bin (DE2 alone: 384 B; gated
    hybrid picked LZMA at 1212 B instead) -- fixed by always trying it
    within the size budget rather than pre-filtering. Pass True/False to
    force it on/off regardless of size.
    """
    n = len(data)
    orig_crc = zlib.crc32(data) & 0xFFFFFFFF
    header = MAGIC + encode_varint(n) + orig_crc.to_bytes(4, "little")

    candidates = []  # (method, payload)
    candidates.append((METHOD_STORED, data))

    if n > 0:
        preset = _lzma_preset(n)
        candidates.append((METHOD_LZMA, lzma.compress(data, preset=preset)))

        f = classify(data)
        if _looks_numeric_structured(f):
            delta = delta_bytes(data)
            candidates.append(
                (METHOD_DELTA_LZMA, lzma.compress(delta, preset=preset)))

        # DE2's own LZE+Huffman codec has its own internal classifier and
        # candidate search (including its own delta/struct paths), so it
        # can win even when our cheap classify() signals above don't fire
        # (e.g. random_prng.bin). Always measure it within a size budget
        # that keeps worst-case total compress time bounded on large
        # general-purpose files, rather than pre-filtering by heuristic.
        want_de2 = try_de2 if try_de2 is not None else (n <= _DE2_SIZE_LIMIT)
        if want_de2:
            candidates.append((METHOD_DE2, de2_codec.compress(data)))

    method, payload = min(candidates, key=lambda c: len(c[1]))
    out = bytearray(header)
    out.append(method)
    out.extend(payload)
    return bytes(out), _METHOD_NAMES[method]


def compress_blob(data, try_de2=None):
    """Same as compress() but returns only the container bytes (drops the
    diagnostic method name), for drop-in use as a normal codec API."""
    blob, _ = compress(data, try_de2=try_de2)
    return blob


def decompress(blob):
    if blob[:4] != MAGIC:
        raise CorruptedError("bad magic")
    pos = 4
    orig_len, pos = decode_varint(blob, pos, len(blob))
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
        else:
            raise CorruptedError("unknown method byte: %d" % method)
    except CorruptedError:
        raise
    except Exception as exc:
        # Any backend decode failure (bad LZMA stream, DE2 container
        # rejecting a bad CRC/header, etc.) is corruption from this
        # container's point of view -- normalize to CorruptedError so
        # callers get one consistent exception type to catch, per this
        # project's own rule that corrupted input must be detected, not
        # surfaced as a random backend-specific exception.
        raise CorruptedError("payload decode failed (%s: %s)"
                              % (type(exc).__name__, exc)) from exc

    if len(restored) != orig_len:
        raise CorruptedError("length mismatch: expected %d got %d"
                              % (orig_len, len(restored)))
    if (zlib.crc32(restored) & 0xFFFFFFFF) != orig_crc:
        raise CorruptedError("crc32 mismatch: corrupted container")
    return restored
