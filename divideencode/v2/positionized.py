"""DE2 positionized transform with compact symbol-position encoding.

Each distinct byte gets a small dictionary ID implicitly (dictionary order),
and its occurrences are represented as numeric position patterns.  The
position stream is deliberately numeric: absolute first position + gap-1
varints, with cheap arithmetic/run records where they win.

The transform remains lossless and automatically falls back to ordinary DE2
when positionization is not smaller.
"""
from __future__ import annotations

import struct
from .codec import compress as de2_compress, decompress as de2_decompress

MAGIC = b"DE2P"
VERSION = 4

# Compact record tags.
GAPS = 0       # first absolute position, then gap-1 values
ARITH = 1      # start, signed step, count
RUN = 2        # start, count (step=1)


def _uvarint(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative unsigned varint")
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _read_uvarint(buf: bytes, off: int):
    value = 0
    shift = 0
    while off < len(buf):
        b = buf[off]
        off += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, off
        shift += 7
        if shift > 63:
            raise ValueError("invalid varint")
    raise ValueError("truncated varint")


def _svarint(n: int) -> bytes:
    return _uvarint((n << 1) ^ (n >> 63))


def _read_svarint(buf: bytes, off: int):
    z, off = _read_uvarint(buf, off)
    return (z >> 1) ^ -(z & 1), off


def _build_positions(data: bytes):
    positions = [[] for _ in range(256)]
    for pos, b in enumerate(data):
        positions[b].append(pos)

    dictionary = bytearray()
    stream = bytearray()
    for symbol, poslist in enumerate(positions):
        if poslist:
            dictionary.append(symbol)
            stream += _encode_position_list(poslist)
    return bytes(dictionary), bytes(stream)


def _encode_position_list(poslist: list[int]) -> bytes:
    """Compactly encode one symbol's ordered positions."""
    n = len(poslist)
    out = bytearray(_uvarint(n))
    i = 0

    while i < n:
        remaining = n - i
        start = poslist[i]

        if remaining >= 4:
            step = poslist[i + 1] - start
            j = i + 2
            while j < n and poslist[j] - poslist[j - 1] == step:
                j += 1
            count = j - i
            if count >= 4:
                if step == 1:
                    out.append(RUN)
                    out += _uvarint(start)
                    out += _uvarint(count)
                else:
                    out.append(ARITH)
                    out += _uvarint(start)
                    out += _svarint(step)
                    out += _uvarint(count)
                i = j
                continue

        # GAPS record.  gap-1 makes the most common gap=1 become zero.
        # Eight positions keeps the record overhead bounded while still
        # giving DE2 a long numeric stream to exploit.
        take = min(8, remaining)
        out.append(GAPS)
        out += _uvarint(take)
        out += _uvarint(start)
        prev = start
        for k in range(1, take):
            gap = poslist[i + k] - prev
            if gap <= 0:
                raise ValueError("positions must be strictly increasing")
            out += _uvarint(gap - 1)
            prev = poslist[i + k]
        i += take

    return bytes(out)


def _restore_positions(dictionary: bytes, stream: bytes, original_len: int) -> bytes:
    out = bytearray(original_len)
    occupied = bytearray(original_len)
    off = 0
    used = 0

    for symbol in dictionary:
        count, off = _read_uvarint(stream, off)
        positions = []
        while len(positions) < count:
            if off >= len(stream):
                raise ValueError("truncated positional records")
            tag = stream[off]
            off += 1

            if tag == GAPS:
                take, off = _read_uvarint(stream, off)
                if take == 0:
                    raise ValueError("empty gaps record")
                start, off = _read_uvarint(stream, off)
                positions.append(start)
                prev = start
                for _ in range(1, take):
                    gap_minus_1, off = _read_uvarint(stream, off)
                    prev += gap_minus_1 + 1
                    positions.append(prev)

            elif tag == ARITH:
                start, off = _read_uvarint(stream, off)
                step, off = _read_svarint(stream, off)
                run_count, off = _read_uvarint(stream, off)
                if run_count == 0:
                    raise ValueError("empty arithmetic run")
                positions.extend(start + step * k for k in range(run_count))

            elif tag == RUN:
                start, off = _read_uvarint(stream, off)
                run_count, off = _read_uvarint(stream, off)
                if run_count == 0:
                    raise ValueError("empty run")
                positions.extend(range(start, start + run_count))

            else:
                raise ValueError("unknown positional record")

            if len(positions) > count:
                raise ValueError("positional record exceeds symbol count")

        for p in positions:
            if p >= original_len or occupied[p]:
                raise ValueError("invalid or duplicate position")
            occupied[p] = 1
            out[p] = symbol
        used += len(positions)

    if used != original_len or off != len(stream):
        raise ValueError("invalid positionized stream")
    return bytes(out)


def transform(data: bytes):
    return _build_positions(bytes(data))


def inverse(dictionary: bytes, stream: bytes, original_len: int) -> bytes:
    return _restore_positions(dictionary, stream, original_len)


def compress(data: bytes) -> bytes:
    raw = bytes(data)
    dictionary, positions = _build_positions(raw)
    packed = de2_compress(positions)

    candidate = (
        MAGIC + bytes((VERSION,)) +
        struct.pack("<HI", len(dictionary), len(raw)) +
        dictionary + packed
    )

    # Direct DE2 remains the safety net. Positionization is never allowed
    # to make an input larger than the best existing DE2 representation.
    direct = de2_compress(raw)
    fallback = MAGIC + b"\x00" + struct.pack("<I", len(raw)) + direct
    return candidate if len(candidate) < len(fallback) else fallback


def decompress(blob: bytes) -> bytes:
    if len(blob) < 9 or blob[:4] != MAGIC:
        raise ValueError("invalid DE2P blob")
    mode = blob[4]

    if mode == 0:
        original_len = struct.unpack_from("<I", blob, 5)[0]
        out = de2_decompress(blob[9:])
        if len(out) != original_len:
            raise ValueError("invalid direct length")
        return out

    if mode != VERSION or len(blob) < 11:
        raise ValueError("unsupported DE2P version")
    dict_len, original_len = struct.unpack_from("<HI", blob, 5)
    start = 11
    end = start + dict_len
    if end > len(blob):
        raise ValueError("truncated dictionary")
    positions = de2_decompress(blob[end:])
    return _restore_positions(blob[start:end], positions, original_len)


__all__ = ["compress", "decompress", "transform", "inverse"]
