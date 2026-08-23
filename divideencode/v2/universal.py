"""DivideEncode Universal -- adaptive partitioning layer.

The important architectural change here is *divide first, optimize second*.
A file is not assumed to have one statistical personality. Each independent
block is measured against DivideEncode's reversible transforms and the
smallest complete representation is kept for that block.

This cannot mathematically compress every possible byte string below its
original information content; incompressible data is kept stored. The goal is
instead to avoid losing opportunities when a file is heterogeneous: text,
numeric records, repeated regions and random regions can coexist.

Format (little-endian varints):
    magic       4 bytes: DUV1
    original_len
    block_size
    block_count
    repeated block records:
        raw_len
        payload_len
        payload (normal DE2 method-prefixed payload)

The block payload is produced by the existing DE2 candidate machinery, so
all existing transforms remain available and the new layer adds no lossy
operation.
"""
from ..errors import CorruptedError
from ..bitstream import encode_varint, decode_varint
from . import codec
from .preproc import plan_candidates

MAGIC = b"DUV1"
DEFAULT_BLOCK_SIZE = 64 * 1024
MIN_BLOCK_SIZE = 1024
MAX_BLOCK_SIZE = 4 * 1024 * 1024


def _best_payload(block):
    """Measure every existing DE2 candidate for one block."""
    best = bytes((codec.METHOD_STORED,)) + block
    for method, param in plan_candidates(block):
        payload = codec._method_payload(block, method, param)
        if payload is not None and len(payload) < len(best):
            best = payload
    return best


def compress(data, block_size=DEFAULT_BLOCK_SIZE):
    """Compress using adaptive per-block DivideEncode selection."""
    if isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    if not isinstance(data, bytes):
        raise TypeError("compress expects bytes-like data")
    if block_size < MIN_BLOCK_SIZE or block_size > MAX_BLOCK_SIZE:
        raise ValueError("block_size must be between 1024 and 4194304")
    if not data:
        return MAGIC + encode_varint(0) + encode_varint(block_size) + encode_varint(0)

    blocks = [data[i:i + block_size] for i in range(0, len(data), block_size)]
    records = []
    total = 0
    for block in blocks:
        payload = _best_payload(block)
        records.append((len(block), payload))
        total += len(payload) + len(encode_varint(len(block))) + len(encode_varint(len(payload)))

    out = bytearray(MAGIC)
    out += encode_varint(len(data))
    out += encode_varint(block_size)
    out += encode_varint(len(records))
    for raw_len, payload in records:
        out += encode_varint(raw_len)
        out += encode_varint(len(payload))
        out += payload
    return bytes(out)


def decompress(blob):
    """Restore a Universal Divide stream and validate every boundary."""
    blob = bytes(blob)
    if len(blob) < 4 or blob[:4] != MAGIC:
        raise CorruptedError("bad universal magic")
    pos = 4
    expected, pos = decode_varint(blob, pos, len(blob))
    block_size, pos = decode_varint(blob, pos, len(blob))
    count, pos = decode_varint(blob, pos, len(blob))
    if block_size < MIN_BLOCK_SIZE or block_size > MAX_BLOCK_SIZE:
        raise CorruptedError("invalid universal block size")
    if expected == 0:
        if count != 0 or pos != len(blob):
            raise CorruptedError("invalid empty universal stream")
        return b""
    if count == 0:
        raise CorruptedError("missing universal blocks")

    out = bytearray()
    for _ in range(count):
        raw_len, pos = decode_varint(blob, pos, len(blob))
        payload_len, pos = decode_varint(blob, pos, len(blob))
        if raw_len == 0 or raw_len > block_size:
            raise CorruptedError("invalid universal block length")
        end = pos + payload_len
        if end > len(blob):
            raise CorruptedError("truncated universal block")
        block, consumed = codec.decode_payload(blob, raw_len, pos, end)
        if consumed != end or len(block) != raw_len:
            raise CorruptedError("universal block boundary mismatch")
        out += block
        pos = end
        if len(out) > expected:
            raise CorruptedError("universal output exceeds original length")

    if pos != len(blob) or len(out) != expected:
        raise CorruptedError("universal stream size mismatch")
    return bytes(out)


def compress_if_smaller(data, block_size=DEFAULT_BLOCK_SIZE):
    """Return Universal output only when it beats the normal DE2 container.

    The comparison includes both containers in full. This makes the new
    architecture safe to use as a candidate rather than a mandatory wrapper.
    """
    normal = codec.compress(data)
    universal = compress(data, block_size=block_size)
    return universal if len(universal) < len(normal) else normal


__all__ = ["MAGIC", "DEFAULT_BLOCK_SIZE", "compress", "decompress",
           "compress_if_smaller"]
