"""DE3: fast run-based numeric-factor transform.

One linear scan finds adjacent decimal integer runs separated by common
 delimiters. A run is encoded only when the compact factor+delta representation
is smaller than its original spelling. Untouched bytes and delimiters remain
byte-exact. The transformed stream is intended to be compressed by DE2.
"""

from __future__ import annotations

import struct

MAGIC = b"DE3R1"
_DELIMS = b" \t,;|\r\n"


def _put_varint(n: int) -> bytes:
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
    return (n >> 1) if not (n & 1) else -((n >> 1) + 1)


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


def _valid_number(data: bytes, a: int, b: int) -> bool:
    if b <= a or (data[a] in (43, 45) and b == a + 1):
        return False
    digits = data[a:b].lstrip(b"+-")
    return not (len(digits) > 1 and digits.startswith(b"0"))


def _parse_run(data: bytes, start: int):
    n = len(data)
    if start >= n or not (48 <= data[start] <= 57 or data[start] in (43, 45)):
        return None
    b = _number_end(data, start)
    if not _valid_number(data, start, b):
        return None
    vals = [(start, b, int(data[start:b]))]
    p = b
    while p < n and data[p] in _DELIMS:
        q = p
        while q < n and data[q] in _DELIMS:
            q += 1
        if q >= n or not (48 <= data[q] <= 57 or data[q] in (43, 45)):
            break
        e = _number_end(data, q)
        if not _valid_number(data, q, e):
            break
        vals.append((q, e, int(data[q:e])))
        p = e
    return (p, vals) if len(vals) >= 2 else None


def _encode_run(data: bytes, start: int, end: int, vals) -> bytes | None:
    numbers = [v for _, _, v in vals]
    nonzero = [abs(v) for v in numbers if v]
    common = min(_factor10(v)[1] for v in nonzero) if nonzero else 0
    scaled = [v // (10 ** common) for v in numbers]
    deltas = [scaled[0]] + [scaled[i] - scaled[i - 1] for i in range(1, len(scaled))]

    payload = bytearray((1, common))
    payload += _put_varint(len(deltas))
    for d in deltas:
        payload += _put_varint(_zigzag(d))

    for i in range(len(vals) - 1):
        s, e = vals[i][1], vals[i + 1][0]
        payload += _put_varint(e - s)
        payload += data[s:e]

    record = bytes((1,)) + struct.pack("<I", end - start) + _put_varint(len(payload)) + payload
    return record if len(record) < end - start + 1 else None


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

        # Jump directly to the next possible numeric start instead of calling
        # the parser at every byte. This keeps DE3 linear on incompressible data.
        j = i + 1
        while j < n and not (48 <= data[j] <= 57 or data[j] in (43, 45)):
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
        if tag != 1 or i + 4 > len(data):
            raise ValueError("invalid DE3 run")

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
        run_start = len(out)
        for idx in range(count - 1):
            dl, i = _get_varint(data, i)
            if i + dl > end:
                raise ValueError("invalid DE3 delimiter")
            out += parts[idx]
            out += data[i:i + dl]
            i += dl
        out += parts[-1]
        if i != end or len(out) - run_start != original_len:
            raise ValueError("DE3 run length mismatch")
    raise ValueError("missing DE3 end marker")


__all__ = ["transform", "inverse"]
