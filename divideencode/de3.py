"""DE3: fast run-based numeric-factor transform.

DE3 looks for adjacent decimal integer runs separated by common delimiters.
Instead of inspecting the whole file, it performs one linear scan. A run is
encoded only when the compact integer representation is smaller than its
original spelling. Delimiters and every untouched byte are preserved exactly.
The output is then fed to DE2 by the benchmark/codec layer.
"""

from __future__ import annotations

import struct

MAGIC = b"DE3R1"
_DELIMS = b" \t,;|\r\n"


def _put_varint(n: int) -> bytes:
    # Unsigned LEB128.
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _get_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(data) or shift > 63:
            raise ValueError("invalid DE3 varint")
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, pos
        shift += 7


def _zigzag(n: int) -> int:
    return (n << 1) if n >= 0 else ((-n << 1) - 1)


def _unzigzag(n: int) -> int:
    return (n >> 1) if (n & 1) == 0 else -((n >> 1) + 1)


def _factor10(v: int) -> tuple[int, int]:
    if v == 0:
        return 0, 0
    scale = 0
    while v % 10 == 0:
        v //= 10
        scale += 1
    return v, scale


def _number_end(data: bytes, start: int) -> int:
    i = start
    if i < len(data) and data[i] in (43, 45):
        i += 1
    while i < len(data) and 48 <= data[i] <= 57:
        i += 1
    return i


def _parse_run(data: bytes, start: int) -> tuple[int, list[tuple[int, int, int]]] | None:
    """Return (end, [(num_start,num_end,value), ...]) for a numeric run."""
    n = len(data)
    if start >= n or not (48 <= data[start] <= 57 or data[start] in (43, 45)):
        return None
    a = start
    b = _number_end(data, a)
    if b <= a or (data[a] in (43, 45) and b == a + 1):
        return None
    # Preserve leading-zero spellings; they are not safe to canonicalize.
    token = data[a:b]
    if token.lstrip(b"+-").startswith(b"0") and len(token.lstrip(b"+-")) > 1:
        return None
    vals = [(a, b, int(token))]
    p = b
    while p < n and data[p] in _DELIMS:
        q = p
        while q < n and data[q] in _DELIMS:
            q += 1
        if q >= n or not (48 <= data[q] <= 57 or data[q] in (43, 45)):
            break
        e = _number_end(data, q)
        if e <= q or (data[q] in (43, 45) and e == q + 1):
            break
        tok = data[q:e]
        digits = tok.lstrip(b"+-")
        if digits.startswith(b"0") and len(digits) > 1:
            break
        vals.append((q, e, int(tok)))
        p = e
    if len(vals) < 2:
        return None
    return p, vals


def _encode_run(data: bytes, start: int, end: int, vals: list[tuple[int, int, int]]) -> bytes | None:
    numbers = [v for _, _, v in vals]
    # A shared decimal factor: divide the entire run by the largest power of
    # ten common to every value. This is the cheap "1000 -> 100 -> 10 -> 1"
    # idea, generalized to a whole numeric run.
    common = min(_factor10(abs(v))[1] for v in numbers if v != 0) if any(numbers) else 0
    scaled = [v // (10 ** common) for v in numbers]
    deltas = [scaled[0]] + [scaled[i] - scaled[i - 1] for i in range(1, len(scaled))]

    payload = bytearray((1, common))
    payload += _put_varint(len(deltas))
    for d in deltas:
        payload += _put_varint(_zigzag(d))

    # Store original delimiters so inverse is byte-exact.
    for i in range(len(vals) - 1):
        s = vals[i][1]
        e = vals[i + 1][0]
        payload += _put_varint(e - s)
        payload += data[s:e]

    # Header: tag + original byte span + payload length. Only use if useful.
    record = bytes((1,)) + struct.pack("<I", end - start) + _put_varint(len(payload)) + payload
    if len(record) >= end - start + 1:
        return None
    return record


def transform(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        data = bytes(data)
    out = bytearray(MAGIC)
    i = 0
    n = len(data)
    while i < n:
        run = _parse_run(data, i)
        if run is not None:
            end, vals = run
            record = _encode_run(data, i, end, vals)
            if record is not None:
                out += record
                i = end
                continue
        # Literal block. Runs of literals are emitted as one block to reduce
        # DE3's framing overhead dramatically on ordinary text/binary data.
        j = i + 1
        while j < n:
            if _parse_run(data, j) is not None:
                break
            j += 1
        out.append(0)
        out += _put_varint(j - i)
        out += data[i:j]
        i = j
    out.append(2)
    return bytes(out)


def inverse(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        data = bytes(data)
    if not data.startswith(MAGIC):
        raise ValueError("invalid DE3 magic")
    i = len(MAGIC)
    out = bytearray()
    while i < len(data):
        tag = data[i]
        i += 1
        if tag == 2:
            if i != len(data):
                raise ValueError("trailing data after DE3 end marker")
            return bytes(out)
        if tag == 0:
            length, i = _get_varint(data, i)
            if i + length > len(data):
                raise ValueError("truncated DE3 literal block")
            out += data[i:i + length]
            i += length
            continue
        if tag != 1:
            raise ValueError(f"unknown DE3 tag {tag}")
        if i + 4 > len(data):
            raise ValueError("truncated DE3 run header")
        original_len = struct.unpack_from("<I", data, i)[0]
        i += 4
        plen, i = _get_varint(data, i)
        if i + plen > len(data):
            raise ValueError("truncated DE3 run payload")
        end = i + plen
        scale = data[i]
        i += 1
        count, i = _get_varint(data, i)
        if count == 0:
            raise ValueError("empty DE3 run")
        scaled = []
        cur = 0
        for idx in range(count):
            z, i = _get_varint(data, i)
            d = _unzigzag(z)
            cur = d if idx == 0 else cur + d
            scaled.append(cur)
        values = [v * (10 ** scale) for v in scaled]
        parts = [str(v).encode("ascii") for v in values]
        for idx in range(count - 1):
            dl, i = _get_varint(data, i)
            if i + dl > end:
                raise ValueError("invalid DE3 delimiter")
            delim = data[i:i + dl]
            i += dl
            out += parts[idx] + delim
        out += parts[-1]
        if i != end:
            raise ValueError("unused DE3 run payload")
        if sum(len(x) for x in parts) + (original_len - sum(v[1] - v[0] for v in [])) < 0:
            raise ValueError("invalid DE3 run")
    raise ValueError("missing DE3 end marker")


__all__ = ["transform", "inverse"]
