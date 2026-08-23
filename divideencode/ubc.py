"""Universal Binary Compiler (UBC).

The UBC language is deliberately simple: every input byte is represented by a
literal BYTE token.  The representation is therefore defined for *all* byte
strings, including completely random data.  DE2 is the backend: it receives
only the UBC bytecode and may compress its structure.

This module does not classify files and does not choose transforms.  Its sole
job is the universal, lossless translation requested by UBC:

    bytes -> UBC binary language -> bytes
"""
from __future__ import annotations

import struct
import zlib

MAGIC = b"UBC1"
VERSION = 1
# One instruction: opcode + literal byte.
OP_BYTE = 0x01
# Stream terminator. It is never ambiguous because every instruction has a
# fixed two-byte representation.
OP_END = 0x00
_HEADER = struct.Struct("<4sBBQII")


class UBCError(ValueError):
    pass


def encode(data: bytes | bytearray | memoryview) -> bytes:
    """Translate arbitrary bytes into the UBC binary language."""
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
    """Alias for the universal compiler entry point."""
    return encode(data)


def decompile(program: bytes | bytearray | memoryview) -> bytes:
    """Alias for the universal decoder entry point."""
    return decode(program)
