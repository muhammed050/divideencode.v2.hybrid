"""Adaptive Universal BWT front-end for DE2.

The selector is deliberately a single front-end: it does not expose a family
of codecs to callers.  It measures the input, performs a bounded BWT+MTF trial,
and selects either DE2-direct or BWT->MTF (optionally RLE) before handing the
result to DE2.

Container format:
    [1-byte path flag] [header/version/metadata] [DE2 payload]

Flags:
    0x01 direct DE2
    0x02 BWT -> MTF -> DE2
    0x03 BWT -> MTF -> RLE -> DE2

BWT is applied independently to bounded blocks so the universal front-end
remains practical on large files.  Each BWT block carries its primary index;
the block size and original size are stored in the wrapper metadata.
"""
from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass

from .errors import CorruptedError, NotDivideEncodedError

FLAG_DIRECT = 0x01
FLAG_BWT_MTF = 0x02
FLAG_BWT_MTF_RLE = 0x03
MAGIC = b"AUB1"
VERSION = 1
DEFAULT_SAMPLE = 64 * 1024
DEFAULT_TRIAL = 12 * 1024
DEFAULT_BWT_BLOCK = 64 * 1024

_COMPRESSED_SIGNATURES = (
    b"PK\x03\x04", b"\x1f\x8b", b"BZh", b"7z\xbc\xaf\x27\x1c",
    b"\xfd7zXZ\x00", b"Rar!\x1a\x07", b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"\x28\xb5\x2f\xfd",
)
_TEXT_EXTS = {"txt", "log", "csv", "json", "xml", "c", "h", "cpp", "hpp", "html", "htm", "js", "ts", "py", "java", "md"}
_BINARY_EXTS = {"exe", "dll", "bin", "dat", "so", "o", "class", "wasm"}


@dataclass(frozen=True)
class Metrics:
    entropy: float
    repetition: float
    zero_ratio: float
    signature_compressed: bool
    extension_hint: str | None


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts if c)


def consecutive_repetition_ratio(data: bytes) -> float:
    if len(data) < 3:
        return 0.0
    hits = 0
    total = len(data) - 2
    for i in range(total):
        if data[i] == data[i + 1] or data[i] == data[i + 2]:
            hits += 1
    return hits / total


def _bwt(block: bytes) -> tuple[bytes, int]:
    """Cyclic BWT using prefix-doubling ranks; practical for 64 KiB blocks."""
    n = len(block)
    if n <= 1:
        return block, 0
    # Add a unique sentinel rank smaller than every byte.  Sorting cyclic
    # rotations of block + sentinel gives a standard reversible BWT.
    s = list(block) + [-1]
    m = n + 1
    order = list(range(m))
    rank = [x + 1 for x in s]
    k = 1
    while k < m:
        order.sort(key=lambda i: (rank[i], rank[(i + k) % m]))
        new_rank = [0] * m
        r = 0
        prev = order[0]
        new_rank[prev] = 0
        for idx in order[1:]:
            a = (rank[prev], rank[(prev + k) % m])
            b = (rank[idx], rank[(idx + k) % m])
            if a != b:
                r += 1
            new_rank[idx] = r
            prev = idx
        rank = new_rank
        if r == m - 1:
            break
        k <<= 1
    last = bytearray()
    primary = 0
    for row, start in enumerate(order):
        if start == 0:
            primary = row
        last.append(0 if start == n else block[start - 1])
    # Remove the sentinel row: it is the row whose last byte was sentinel.
    sentinel_row = order.index(n)
    del last[sentinel_row]
    if sentinel_row < primary:
        primary -= 1
    return bytes(last), primary


def _ibwt(last: bytes, primary: int) -> bytes:
    n = len(last)
    if n <= 1:
        return last
    # Standard LF mapping with occurrence ranks. Python's lists keep this
    # bounded to the configured BWT block size.
    counts = [0] * 256
    occ = [0] * n
    for i, b in enumerate(last):
        occ[i] = counts[b]
        counts[b] += 1
    starts = [0] * 256
    total = 0
    for b in range(256):
        starts[b] = total
        total += counts[b]
    row = primary
    out = bytearray(n)
    for i in range(n - 1, -1, -1):
        b = last[row]
        out[i] = b
        row = starts[b] + occ[row]
    return bytes(out)


def _mtf_encode(data: bytes) -> bytes:
    table = list(range(256))
    out = bytearray(len(data))
    for i, b in enumerate(data):
        p = table.index(b)
        out[i] = p
        if p:
            table.pop(p)
            table.insert(0, b)
    return bytes(out)


def _mtf_decode(data: bytes) -> bytes:
    table = list(range(256))
    out = bytearray(len(data))
    for i, p in enumerate(data):
        if p > 255:
            raise CorruptedError("invalid MTF symbol")
        b = table[p]
        out[i] = b
        if p:
            table.pop(p)
            table.insert(0, b)
    return bytes(out)


def _rle_encode(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        j = i + 1
        while j < len(data) and data[j] == b and j - i < 255:
            j += 1
        run = j - i
        if run >= 4 or b == 0:
            out += b"\x00" + bytes((b, run))
        else:
            out += bytes((b,)) * run
        i = j
    return bytes(out)


def _rle_decode(data: bytes, expected: int) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0:
            if i + 2 >= len(data):
                raise CorruptedError("truncated adaptive RLE")
            value, run = data[i + 1], data[i + 2]
            if run == 0:
                raise CorruptedError("invalid adaptive RLE run")
            out += bytes((value,)) * run
            i += 3
        else:
            out.append(b)
            i += 1
        if len(out) > expected:
            raise CorruptedError("adaptive RLE expansion overflow")
    if len(out) != expected:
        raise CorruptedError("adaptive RLE size mismatch")
    return bytes(out)


def _bwt_blocks_encode(data: bytes, block_size: int) -> bytes:
    out = bytearray()
    for off in range(0, len(data), block_size):
        block = data[off:off + block_size]
        last, primary = _bwt(block)
        transformed = _mtf_encode(last)
        out += struct.pack("<II", len(block), primary)
        out += transformed
    return bytes(out)


def _bwt_blocks_decode(data: bytes, original_size: int, block_size: int) -> bytes:
    out = bytearray()
    pos = 0
    while len(out) < original_size:
        if pos + 8 > len(data):
            raise CorruptedError("truncated adaptive BWT block header")
        raw_len, primary = struct.unpack_from("<II", data, pos)
        pos += 8
        if raw_len == 0 or raw_len > block_size or len(out) + raw_len > original_size:
            raise CorruptedError("invalid adaptive BWT block length")
        if pos + raw_len > len(data):
            raise CorruptedError("truncated adaptive BWT block")
        mtf = data[pos:pos + raw_len]
        pos += raw_len
        last = _mtf_decode(mtf)
        if primary >= raw_len:
            raise CorruptedError("invalid adaptive BWT primary index")
        out += _ibwt(last, primary)
    if pos != len(data):
        raise CorruptedError("adaptive BWT payload trailing bytes")
    return bytes(out)


def _signature(data: bytes) -> bool:
    return any(data.startswith(sig) for sig in _COMPRESSED_SIGNATURES)


def _extension_hint(filename: str | None) -> str | None:
    if not filename or "." not in filename:
        return None
    return filename.rsplit(".", 1)[1].lower()


def analyze(data: bytes, *, filename: str | None = None, trial_size: int = DEFAULT_TRIAL) -> Metrics:
    sample = bytes(data[:DEFAULT_SAMPLE])
    trial = bytes(data[:max(8192, min(trial_size, 16384))])
    if not trial:
        zero = 1.0
    else:
        last, _ = _bwt(trial)
        mtf = _mtf_encode(last)
        zero = mtf.count(0) / len(mtf)
    return Metrics(
        entropy=shannon_entropy(sample),
        repetition=consecutive_repetition_ratio(sample),
        zero_ratio=zero,
        signature_compressed=_signature(sample),
        extension_hint=_extension_hint(filename),
    )


def choose_path(metrics: Metrics) -> int:
    ext = metrics.extension_hint
    if metrics.signature_compressed or ext in _BINARY_EXTS:
        return FLAG_DIRECT
    if ext in _TEXT_EXTS:
        if metrics.zero_ratio >= 0.35:
            return FLAG_BWT_MTF_RLE if metrics.zero_ratio >= 0.50 else FLAG_BWT_MTF
        if metrics.zero_ratio < 0.15:
            return FLAG_DIRECT
    if metrics.entropy > 7.5 or metrics.zero_ratio < 0.15:
        return FLAG_DIRECT
    if metrics.entropy < 6.0 and metrics.zero_ratio > 0.35:
        return FLAG_BWT_MTF_RLE if metrics.zero_ratio >= 0.50 else FLAG_BWT_MTF
    if metrics.repetition >= 0.20 and metrics.zero_ratio >= 0.25 and metrics.entropy < 7.0:
        return FLAG_BWT_MTF
    return FLAG_DIRECT


def _wrap(flag: int, original_size: int, block_size: int, payload: bytes, checksum: int) -> bytes:
    return bytes((flag,)) + MAGIC + bytes((VERSION,)) + struct.pack("<III", original_size, block_size, checksum) + payload


def _unwrap(blob: bytes) -> tuple[int, int, int, int, bytes]:
    if len(blob) < 18 or blob[0] not in (FLAG_DIRECT, FLAG_BWT_MTF, FLAG_BWT_MTF_RLE):
        raise NotDivideEncodedError("not an Adaptive Universal BWT container")
    if blob[1:5] != MAGIC or blob[5] != VERSION:
        raise NotDivideEncodedError("unsupported Adaptive Universal BWT container")
    original_size, block_size, checksum = struct.unpack_from("<III", blob, 6)
    if block_size == 0 or block_size > 1 << 20:
        raise CorruptedError("invalid adaptive BWT block size")
    return blob[0], original_size, block_size, checksum, bytes(blob[18:])


def compress(data: bytes, *, filename: str | None = None, block_size: int = DEFAULT_BWT_BLOCK, level: str = "BALANCED") -> bytes:
    from .de2 import compress as de2_compress
    src = bytes(data)
    if not src:
        return _wrap(FLAG_DIRECT, 0, block_size, de2_compress(b"", level=level), zlib.crc32(src) & 0xFFFFFFFF)
    metrics = analyze(src, filename=filename)
    selected = choose_path(metrics)
    direct = de2_compress(src, block_size=1 << 20, level=level)
    if selected == FLAG_DIRECT:
        return _wrap(FLAG_DIRECT, len(src), block_size, direct, zlib.crc32(src) & 0xFFFFFFFF)
    transformed = _bwt_blocks_encode(src, block_size)
    if selected == FLAG_BWT_MTF_RLE:
        transformed = _rle_encode(transformed)
    trial_payload = de2_compress(transformed, block_size=1 << 20, level=level)
    # Never let the adaptive front-end regress against direct DE2.
    if len(trial_payload) >= len(direct):
        selected = FLAG_DIRECT
        payload = direct
    else:
        payload = trial_payload
    return _wrap(selected, len(src), block_size, payload, zlib.crc32(src) & 0xFFFFFFFF)


def decompress(blob: bytes, *, verify: bool = True) -> bytes:
    from .de2 import decompress as de2_decompress
    flag, original_size, block_size, checksum, payload = _unwrap(bytes(blob))
    transformed = de2_decompress(payload, verify=verify)
    if flag == FLAG_DIRECT:
        data = transformed
    else:
        if flag == FLAG_BWT_MTF_RLE:
            # RLE output length is not known independently; decode with a
            # bounded stream parser, then BWT validates each block.
            transformed = _rle_decode_unknown(transformed)
        data = _bwt_blocks_decode(transformed, original_size, block_size)
    if len(data) != original_size:
        raise CorruptedError("adaptive original size mismatch")
    if verify and (zlib.crc32(data) & 0xFFFFFFFF) != checksum:
        raise CorruptedError("adaptive source checksum mismatch")
    return data


def _rle_decode_unknown(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0:
            if i + 2 >= len(data):
                raise CorruptedError("truncated adaptive RLE")
            value, run = data[i + 1], data[i + 2]
            if run == 0:
                raise CorruptedError("invalid adaptive RLE run")
            out += bytes((value,)) * run
            i += 3
        else:
            out.append(b)
            i += 1
    return bytes(out)
