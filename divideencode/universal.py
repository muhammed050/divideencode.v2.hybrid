"""DU1 — one universal reversible preconditioner for DE2.

The project goal here is deliberately narrow: do not classify file types and
 do not choose between a family of codecs.  DU1 applies one fixed mathematical
 transformation to every byte stream, then gives that representation to DE2.

For byte x_i, with x_-1 = 0:
    r_i = (x_i - x_{i-1}) mod 256
    s_i = r_i                 when r_i < 128
          r_i - 256           otherwise
    z_i = 2*s_i               when s_i >= 0
          -2*s_i - 1          otherwise

The signed residual is mapped by zigzag so nearby values occupy nearby small
symbols.  The transform is exactly reversible and format-agnostic.
"""
from __future__ import annotations

import zlib

from .bitstream import decode_varint, encode_varint
from .errors import CorruptedError, NotDivideEncodedError

MAGIC = b"DU1"
VERSION = 1
FLAG_TRANSFORM = 1
FLAG_IDENTITY = 0


def _zigzag_signed(value: int) -> int:
    return value << 1 if value >= 0 else (-value << 1) - 1


def _unzigzag(value: int) -> int:
    return value >> 1 if not (value & 1) else -((value >> 1) + 1)


def encode(data: bytes) -> bytes:
    """Apply the single universal residual+zigzag transform."""
    src = bytes(data)
    out = bytearray(len(src))
    prev = 0
    for i, value in enumerate(src):
        residual = (value - prev) & 0xFF
        signed = residual if residual < 128 else residual - 256
        out[i] = _zigzag_signed(signed)
        prev = value
    return bytes(out)


def decode(data: bytes, original_size: int | None = None) -> bytes:
    """Reverse :func:`encode` byte-for-byte."""
    src = bytes(data)
    if original_size is not None and len(src) != original_size:
        raise CorruptedError("DU1 transformed size mismatch")
    out = bytearray(len(src))
    prev = 0
    for i, encoded in enumerate(src):
        value = (prev + _unzigzag(encoded)) & 0xFF
        out[i] = value
        prev = value
    return bytes(out)


def _wrap(flags: int, original_size: int, payload: bytes, checksum: int) -> bytes:
    out = bytearray(MAGIC)
    out.append(VERSION)
    out.append(flags)
    out += encode_varint(original_size)
    out += encode_varint(len(payload))
    out += checksum.to_bytes(4, "little")
    out += payload
    return bytes(out)


def _unwrap(blob: bytes) -> tuple[int, int, int, bytes]:
    if len(blob) < 9 or blob[:3] != MAGIC:
        raise NotDivideEncodedError("not a DU1 universal container")
    if blob[3] != VERSION:
        raise NotDivideEncodedError("unsupported DU1 version %d" % blob[3])
    flags = blob[4]
    if flags not in (FLAG_IDENTITY, FLAG_TRANSFORM):
        raise CorruptedError("unknown DU1 flags 0x%02x" % flags)
    original_size, pos = decode_varint(blob, 5, len(blob))
    payload_size, pos = decode_varint(blob, pos, len(blob))
    if pos + 4 > len(blob):
        raise CorruptedError("DU1 checksum truncated")
    checksum = int.from_bytes(blob[pos:pos + 4], "little")
    pos += 4
    if payload_size != len(blob) - pos:
        raise CorruptedError("DU1 payload size mismatch")
    return flags, original_size, checksum, bytes(blob[pos:])


def compress(data: bytes, *, block_size: int = 1 << 20,
             level: str = "BALANCED") -> bytes:
    """DU1 -> DE2.

    The transformed representation is always attempted first.  If DE2 makes
    the untouched bytes smaller, DU1 records identity instead.  This is not a
    second transform/codec; it is the lossless safety escape for data on which
    a reversible preconditioner cannot improve DE2.
    """
    from .de2 import compress as de2_compress

    src = bytes(data)
    transformed = encode(src)
    transformed_de2 = de2_compress(transformed, block_size=block_size,
                                   level=level)

    # Compare only against direct DE2 to prevent the universal layer from
    # ever becoming a size regression.  The actual transform remains unique.
    direct_de2 = de2_compress(src, block_size=block_size, level=level)
    if len(transformed_de2) < len(direct_de2):
        flags = FLAG_TRANSFORM
        payload = transformed_de2
    else:
        flags = FLAG_IDENTITY
        payload = direct_de2

    return _wrap(flags, len(src), payload, zlib.crc32(src) & 0xFFFFFFFF)


def decompress(blob: bytes, *, verify: bool = True) -> bytes:
    """DE2 -> DU1 inverse -> original bytes."""
    from .de2 import decompress as de2_decompress

    flags, original_size, checksum, payload = _unwrap(bytes(blob))
    transformed = de2_decompress(payload, verify=verify)
    if len(transformed) != original_size:
        raise CorruptedError("DU1 original size mismatch")
    data = decode(transformed, original_size) if flags == FLAG_TRANSFORM else transformed
    if verify and (zlib.crc32(data) & 0xFFFFFFFF) != checksum:
        raise CorruptedError("DU1 source checksum mismatch")
    return data


def transform_ratio(data: bytes) -> float:
    """Return transformed-byte size / source-byte size (always 1.0 for non-empty input)."""
    src = bytes(data)
    return 1.0 if src else 1.0
