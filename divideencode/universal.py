"""Fast universal file compressor.

The public universal path uses the single-pass DE2 universal translator:
input bytes -> one representation decision per block -> DE2.

The legacy DU1 decoder is retained so previously generated DU1 containers
remain readable. ``encode``/``decode`` remain compatibility aliases for the
public universal API used by older callers and tests.
"""
from __future__ import annotations

from .errors import CorruptedError, NotDivideEncodedError


def compress(data: bytes, *, block_size: int = 1 << 20,
             level: str = "BALANCED") -> bytes:
    """Compress any bytes using the single universal DE2 path."""
    from .de2 import compress as de2_compress
    return de2_compress(bytes(data), block_size=block_size, level=level)


def decompress(blob: bytes, *, verify: bool = True) -> bytes:
    """Decode the current DE2 universal format or a legacy DU1 container."""
    src = bytes(blob)
    if src[:3] == b"DE2":
        from .de2 import decompress as de2_decompress
        return de2_decompress(src, verify=verify)
    if src[:3] != b"DU1":
        raise NotDivideEncodedError("not a DivideEncode universal container")

    import zlib
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
