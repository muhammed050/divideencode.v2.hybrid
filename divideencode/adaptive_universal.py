"""Adaptive Universal BWT -> DE2 front-end.

One selector, three wire paths:
  0x01 = DE2 direct
  0x02 = BWT -> MTF -> DE2
  0x03 = BWT -> MTF -> RLE -> DE2

The first byte is always the path flag. Metrics use the first 64 KiB and a
bounded 8-16 KiB BWT/MTF trial. BWT is block-local (64 KiB by default) so large
files remain bounded in memory and decoding is independently reversible.
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
    total = len(data) - 2
    return sum(data[i] == data[i + 1] or data[i] == data[i + 2] for i in range(total)) / total


def _bwt(data: bytes) -> tuple[bytes, int]:
    """Cyclic BWT via prefix-doubling ranks; no sentinel is required."""
    n = len(data)
    if n <= 1:
        return data, 0
    order = list(range(n))
    rank = list(data)
    k = 1
    while k < n:
        order.sort(key=lambda i: (rank[i], rank[(i + k) % n]))
        new = [0] * n
        r = 0
        prev = order[0]
        new[prev] = 0
        for idx in order[1:]:
            if (rank[prev], rank[(prev + k) % n]) != (rank[idx], rank[(idx + k) % n]):
                r += 1
            new[idx] = r
            prev = idx
        rank = new
        if r == n - 1:
            break
        k <<= 1
    primary = order.index(0)
    last = bytes(data[(i - 1) % n] for i in order)
    return last, primary


def _ibwt(last: bytes, primary: int) -> bytes:
    n = len(last)
    if n <= 1:
        return last
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
    out = bytearray()
    for b in data:
        p = table.index(b)
        out.append(p)
        if p:
            table.pop(p)
            table.insert(0, b)
    return bytes(out)


def _mtf_decode(data: bytes) -> bytes:
    table = list(range(256))
    out = bytearray()
    for p in data:
        b = table[p]
        out.append(b)
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
        if b == 0 or run >= 4:
            out += bytes((0, b, run))
        else:
            out += bytes((b,)) * run
        i = j
    return bytes(out)


def _rle_decode(data: bytes) -> bytes:
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


def _blocks_encode(data: bytes, block_size: int) -> bytes:
    out = bytearray()
    for off in range(0, len(data), block_size):
        block = data[off:off + block_size]
        last, primary = _bwt(block)
        mtf = _mtf_encode(last)
        out += struct.pack("<II", len(block), primary)
        out += mtf
    return bytes(out)


def _blocks_decode(data: bytes, original_size: int, block_size: int) -> bytes:
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
        last = _mtf_decode(data[pos:pos + raw_len])
        pos += raw_len
        if primary >= raw_len:
            raise CorruptedError("invalid adaptive BWT primary index")
        out += _ibwt(last, primary)
    if pos != len(data):
        raise CorruptedError("adaptive BWT trailing bytes")
    return bytes(out)


def _extension(filename: str | None) -> str | None:
    return filename.rsplit(".", 1)[1].lower() if filename and "." in filename else None


def _signature(data: bytes) -> bool:
    return any(data.startswith(sig) for sig in _COMPRESSED_SIGNATURES)


def analyze(data: bytes, *, filename: str | None = None, trial_size: int = DEFAULT_TRIAL) -> Metrics:
    sample = bytes(data[:DEFAULT_SAMPLE])
    trial = bytes(data[:max(8192, min(trial_size, 16384))])
    if trial:
        last, _ = _bwt(trial)
        zero = _mtf_encode(last).count(0) / len(trial)
    else:
        zero = 1.0
    return Metrics(shannon_entropy(sample), consecutive_repetition_ratio(sample), zero, _signature(sample), _extension(filename))


def choose_path(m: Metrics) -> int:
    if m.signature_compressed or m.extension_hint in _BINARY_EXTS:
        return FLAG_DIRECT
    if m.entropy > 7.5 or m.zero_ratio < 0.15:
        return FLAG_DIRECT
    if m.extension_hint in _TEXT_EXTS and m.zero_ratio >= 0.35:
        return FLAG_BWT_MTF_RLE if m.zero_ratio >= 0.50 else FLAG_BWT_MTF
    if m.entropy < 6.0 and m.zero_ratio > 0.35:
        return FLAG_BWT_MTF_RLE if m.zero_ratio >= 0.50 else FLAG_BWT_MTF
    if m.repetition >= 0.20 and m.zero_ratio >= 0.25 and m.entropy < 7.0:
        return FLAG_BWT_MTF
    return FLAG_DIRECT


def _wrap(flag: int, original_size: int, block_size: int, checksum: int, payload_checksum: int, payload: bytes) -> bytes:
    # The payload checksum is intentionally separate from the source checksum:
    # a bit flip in compressed bytes must be rejected even when the downstream
    # codec happens to decode the corrupted bitstream to the same source bytes.
    return bytes((flag,)) + MAGIC + bytes((VERSION,)) + struct.pack(
        "<IIII", original_size, block_size, checksum, payload_checksum
    ) + payload


def _unwrap(blob: bytes):
    if len(blob) < 22 or blob[0] not in (1, 2, 3) or blob[1:5] != MAGIC or blob[5] != VERSION:
        raise NotDivideEncodedError("not an Adaptive Universal BWT container")
    original_size, block_size, checksum, payload_checksum = struct.unpack_from("<IIII", blob, 6)
    if block_size == 0 or block_size > 1 << 20:
        raise CorruptedError("invalid adaptive BWT block size")
    return blob[0], original_size, block_size, checksum, payload_checksum, bytes(blob[22:])


def compress(data: bytes, *, filename: str | None = None, block_size: int = DEFAULT_BWT_BLOCK, level: str = "BALANCED") -> bytes:
    from .de2 import compress as de2_compress
    src = bytes(data)
    direct = de2_compress(src, block_size=1 << 20, level=level)
    if not src:
        return _wrap(FLAG_DIRECT, 0, block_size, zlib.crc32(src) & 0xFFFFFFFF, zlib.crc32(direct) & 0xFFFFFFFF, direct)
    selected = choose_path(analyze(src, filename=filename))
    if selected != FLAG_DIRECT:
        transformed = _blocks_encode(src, block_size)
        if selected == FLAG_BWT_MTF_RLE:
            transformed = _rle_encode(transformed)
        candidate = de2_compress(transformed, block_size=1 << 20, level=level)
        if len(candidate) < len(direct):
            direct = candidate
        else:
            selected = FLAG_DIRECT
    return _wrap(selected, len(src), block_size, zlib.crc32(src) & 0xFFFFFFFF, zlib.crc32(direct) & 0xFFFFFFFF, direct)


def decompress(blob: bytes, *, verify: bool = True) -> bytes:
    from .de2 import decompress as de2_decompress
    flag, original_size, block_size, checksum, payload_checksum, payload = _unwrap(bytes(blob))
    if verify and zlib.crc32(payload) & 0xFFFFFFFF != payload_checksum:
        raise CorruptedError("adaptive payload checksum mismatch")
    transformed = de2_decompress(payload, verify=verify)
    if flag == FLAG_DIRECT:
        data = transformed
    else:
        if flag == FLAG_BWT_MTF_RLE:
            transformed = _rle_decode(transformed)
        data = _blocks_decode(transformed, original_size, block_size)
    if len(data) != original_size:
        raise CorruptedError("adaptive original size mismatch")
    if verify and zlib.crc32(data) & 0xFFFFFFFF != checksum:
        raise CorruptedError("adaptive source checksum mismatch")
    return data
