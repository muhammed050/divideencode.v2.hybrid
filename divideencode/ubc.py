"""Universal Binary Compiler (UBC): bytes -> UBC language -> DE2."""
from __future__ import annotations

import struct
import zlib

MAGIC = b"UBC1"
VERSION = 1
OP_BYTE = 0x01
OP_END = 0x00
_HEADER = struct.Struct("<4sBBQII")


class UBCError(ValueError):
    pass


def encode(data: bytes | bytearray | memoryview) -> bytes:
    """Translate arbitrary bytes into the universal UBC binary language."""
    src = bytes(data)
    body = bytearray(2 * len(src) + 1)
    p = 0
    for value in src:
        body[p] = OP_BYTE
        body[p + 1] = value
        p += 2
    body[p] = OP_END
    crc = zlib.crc32(src) & 0xFFFFFFFF
    return _HEADER.pack(MAGIC, VERSION, 0, len(src), len(body), crc) + body


def decode(program: bytes | bytearray | memoryview) -> bytes:
    """Translate a UBC binary-language program back to the exact bytes."""
    blob = bytes(program)
    if len(blob) < _HEADER.size:
        raise UBCError("truncated UBC program")
    magic, version, flags, original_size, body_size, crc = _HEADER.unpack_from(blob)
    if magic != MAGIC or version != VERSION or flags != 0:
        raise UBCError("invalid UBC program header")
    if body_size != len(blob) - _HEADER.size:
        raise UBCError("UBC body size mismatch")

    body = blob[_HEADER.size:]
    out = bytearray()
    p = 0
    while p < len(body):
        opcode = body[p]
        p += 1
        if opcode == OP_END:
            if p != len(body):
                raise UBCError("data after UBC END")
            break
        if opcode != OP_BYTE or p >= len(body):
            raise UBCError("invalid UBC instruction")
        out.append(body[p])
        p += 1
    else:
        raise UBCError("missing UBC END")

    if len(out) != original_size:
        raise UBCError("UBC original size mismatch")
    if zlib.crc32(out) & 0xFFFFFFFF != crc:
        raise UBCError("UBC checksum mismatch")
    return bytes(out)


def compile(data: bytes | bytearray | memoryview) -> bytes:
    return encode(data)


def decompile(program: bytes | bytearray | memoryview) -> bytes:
    return decode(program)


def compress(data: bytes | bytearray | memoryview, **kwargs) -> bytes:
    """Direct UBC -> DE2 backend. No selector or extra transform is used."""
    from .de2 import compress as de2_compress
    return de2_compress(encode(data), **kwargs)


def decompress(blob: bytes | bytearray | memoryview, *, verify: bool = True) -> bytes:
    """Direct DE2 -> UBC -> original bytes backend."""
    from .de2 import decompress as de2_decompress
    return decode(de2_decompress(bytes(blob), verify=verify))


def compile_to_de2(data: bytes | bytearray | memoryview, **kwargs) -> bytes:
    return compress(data, **kwargs)


def decompile_from_de2(blob: bytes | bytearray | memoryview, *, verify: bool = True) -> bytes:
    return decompress(blob, verify=verify)
