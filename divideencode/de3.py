"""DE3 numeric-factor preprocessor for DE2.

DE3 is intentionally conservative: it does one linear scan, rewrites only
integer runs that are provably smaller, and otherwise returns the original
bytes so DE2 remains the authoritative compressor.

The numeric representation is:
    integer run -> common trailing-zero factor -> ZigZag delta stream

The record format is compact and self-delimiting; no fixed 32-bit payload
lengths are stored for every run. Signed integers are preserved exactly.
"""
from __future__ import annotations

MAGIC = b"DE3R3"
_LITERAL = 0
_RUN = 1
_END = 2
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


def _factor10(v: int) -> int:
    v = abs(v)
    scale = 0
    while v and v % 10 == 0:
        v //= 10
        scale += 1
    return scale


def _number_end(data: bytes, start: int) -> int:
    i = start
    if i < len(data) and data[i] == 45:  # '-'
        i += 1
    while i < len(data) and 48 <= data[i] <= 57:
        i += 1
    return i


def _valid_number(data: bytes, a: int, b: int) -> bool:
    if b <= a or data[a] == 43:  # '+' is rejected because reconstruction changes it
        return False
    if data[a] == 45 and b == a + 1:
        return False
    digits = data[a:b].lstrip(b"-")
    return not (len(digits) > 1 and digits.startswith(b"0"))


def _parse_run(data: bytes, start: int):
    n = len(data)
    if start >= n or not (48 <= data[start] <= 57 or data[start] == 45):
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
        if q >= n or not (48 <= data[q] <= 57 or data[q] == 45):
            break
        e = _number_end(data, q)
        if not _valid_number(data, q, e):
            break
        vals.append((q, e, int(data[q:e])))
        p = e
    return (p, vals) if len(vals) >= 3 else None


def _encode_run(data: bytes, start: int, end: int, vals) -> bytes | None:
    numbers = [v for _, _, v in vals]
    # Factoring is useful only when every non-zero value shares the factor.
    scales = [_factor10(v) for v in numbers if v]
    common = min(scales, default=0)
    if common == 0:
        return None
    divisor = 10 ** common
    scaled = [v // divisor for v in numbers]
    deltas = [scaled[0]] + [scaled[i] - scaled[i - 1] for i in range(1, len(scaled))]

    payload = bytearray((common,))
    payload += _put_varint(len(deltas))
    for d in deltas:
        payload += _put_varint(_zigzag(d))

    # Preserve the exact separators between numbers.
    for i in range(len(vals) - 1):
        s, e = vals[i][1], vals[i + 1][0]
        sep = data[s:e]
        payload += _put_varint(len(sep))
        payload += sep

    # tag + original length + payload. All fields are varints.
    record = bytes((_RUN,)) + _put_varint(end - start) + bytes(payload)
    return record if len(record) + 1 < end - start else None


def transform(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        data = bytes(data)
    if not data:
        return data

    records = bytearray(MAGIC)
    literal = bytearray()
    changed = False

    def flush_literal() -> None:
        if literal:
            records.append(_LITERAL)
            records.extend(_put_varint(len(literal)))
            records.extend(literal)
            literal.clear()

    i = 0
    n = len(data)
    while i < n:
        run = _parse_run(data, i)
        if run is not None:
            end, vals = run
            rec = _encode_run(data, i, end, vals)
            if rec is not None:
                flush_literal()
                records.extend(rec)
                changed = True
                i = end
                continue

        j = i + 1
        while j < n and not (48 <= data[j] <= 57 or data[j] == 45):
            j += 1
        literal.extend(data[i:j])
        i = j

    if not changed:
        return data
    flush_literal()
    records.append(_END)
    encoded = bytes(records)
    return encoded if len(encoded) < len(data) else data


def inverse(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        data = bytes(data)
    if not data.startswith(MAGIC):
        return data

    i = len(MAGIC)
    out = bytearray()
    while i < len(data):
        tag = data[i]
        i += 1

        if tag == _END:
            if i != len(data):
                raise ValueError("trailing data after DE3 end marker")
            return bytes(out)

        if tag == _LITERAL:
            length, i = _get_varint(data, i)
            if i + length > len(data):
                raise ValueError("truncated DE3 literal block")
            out += data[i:i + length]
            i += length
            continue

        if tag != _RUN:
            raise ValueError("invalid DE3 record")

        original_len, i = _get_varint(data, i)
        if i >= len(data):
            raise ValueError("truncated DE3 run")
        scale = data[i]
        i += 1
        count, i = _get_varint(data, i)
        if count < 3:
            raise ValueError("invalid DE3 run count")

        scaled = []
        cur = 0
        for idx in range(count):
            z, i = _get_varint(data, i)
            d = _unzigzag(z)
            cur = d if idx == 0 else cur + d
            scaled.append(cur)

        values = [v * (10 ** scale) for v in scaled]
        start_out = len(out)
        for idx in range(count - 1):
            out += str(values[idx]).encode("ascii")
            sep_len, i = _get_varint(data, i)
            if i + sep_len > len(data):
                raise ValueError("truncated DE3 separator")
            out += data[i:i + sep_len]
            i += sep_len
        out += str(values[-1]).encode("ascii")

        if len(out) - start_out != original_len:
            raise ValueError("DE3 run length mismatch")

    raise ValueError("missing DE3 end marker")


__all__ = ["transform", "inverse"]
