"""Fast universal file compressor.

The public universal API uses DE2 for the payload while keeping the DU1
container contract for compatibility and corruption detection. The DU1
header carries source/payload CRCs, so a damaged final byte cannot silently
pass through the decoder.
"""
from __future__ import annotations

import zlib

from .errors import CorruptedError, NotDivideEncodedError


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def compress(data: bytes, *, block_size: int = 1 << 20,
             level: str = "BALANCED") -> bytes:
    """Compress bytes into the compatible DU1 container using DE2 payload."""
    src = bytes(data)
    from .de2 import compress as de2_compress

    payload = de2_compress(src, block_size=block_size, level=level)
    header = bytearray(b"DU1")
    header.append(2)  # container version
    header.append(0)  # flags: no legacy byte-delta transform
    header.extend(_encode_varint(len(src)))
    header.extend(_encode_varint(len(payload)))
    header.extend((zlib.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "little"))
    header.extend((zlib.crc32(src) & 0xFFFFFFFF).to_bytes(4, "little"))
    return bytes(header) + payload


def decompress(blob: bytes, *, verify: bool = True) -> bytes:
    """Decode the current DU1 universal format or a legacy DU1 container.

    A bare DE2 container is also accepted for callers that explicitly pass
    one, preserving the previous reader behavior.
    """
    src = bytes(blob)
    if src[:3] == b"DE2":
        from .de2 import decompress as de2_decompress
        return de2_decompress(src, verify=verify)
    if src[:3] != b"DU1":
        raise NotDivideEncodedError("not a DivideEncode universal container")

    from .bitstream import decode_varint

    if len(src) < 13 or src[3] != 2:
        raise NotDivideEncodedError("unsupported DU1 container")
    flags = src[4]
    if flags not in (0, 1):
        raise CorruptedError("unknown DU1 flags")
    original_size, pos = decode_varint(src, 5, len(src))
    payload_size, pos = decode_varint(src, pos, len(src))
    if pos + 8 > len(src) or payload_size != len(src) - pos - 8:
        raise CorruptedError("DU1 container truncated")
    payload_crc = int.from_bytes(src[pos:pos + 4], "little")
    source_crc = int.from_bytes(src[pos + 4:pos + 8], "little")
    pos += 8
    payload = src[pos:]
    if (zlib.crc32(payload) & 0xFFFFFFFF) != payload_crc:
        raise CorruptedError("DU1 payload checksum mismatch")
    from .de2 import decompress as de2_decompress
    transformed = de2_decompress(payload, verify=verify)
    if len(transformed) != original_size:
        raise CorruptedError("DU1 original size mismatch")
    if flags:
        out = bytearray(len(transformed))
        prev = 0
        for i, encoded in enumerate(transformed):
            value = encoded >> 1
            if encoded & 1:
                value = -value - 1
            out[i] = (prev + value) & 0xFF
            prev = out[i]
        data = bytes(out)
    else:
        data = transformed
    if verify and (zlib.crc32(data) & 0xFFFFFFFF) != source_crc:
        raise CorruptedError("DU1 source checksum mismatch")
    return data


# Compatibility API: older versions exposed encode/decode under these names.
encode = compress
decode = decompress


def transform_ratio(data: bytes) -> float:
    """Legacy compatibility helper; the current path is adaptive per block."""
    return 1.0
