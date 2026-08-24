"""DE3: direct numeric factor experiment.

Idea under test, deliberately kept simple:
1. Read numeric symbols/runs.
2. Convert each number to an integer.
3. Find the common factor of 10 by repeatedly dividing by 10.
4. Store the factor count and the reduced integers.
5. Reconstruct the original decimal numbers exactly.

No delta coding, no entropy model, no pattern scoring and no expensive search.
DE3 is an experiment around the numeric-factor idea only.
"""
from __future__ import annotations

MAGIC = b"DE3F1"
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


def _factor10(v: int) -> int:
    """Repeatedly divide by 10 and return how many divisions succeeded."""
    v = abs(v)
    count = 0
    while v and v % 10 == 0:
        v //= 10
        count += 1
    return count


def _number_end(data: bytes, start: int) -> int:
    i = start
    if i < len(data) and data[i] == 45:
        i += 1
    while i < len(data) and 48 <= data[i] <= 57:
        i += 1
    return i


def _valid_number(data: bytes, a: int, b: int) -> bool:
    if b <= a or data[a] == 43:
        return False
    if data[a] == 45 and b == a + 1:
        return False
    digits = data[a:b].lstrip(b"-")
    # Preserve decimal spelling exactly; don't rewrite 001 -> 1.
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

    return (p, vals) if len(vals) >= 2 else None


def _encode_run(data: bytes, start: int, end: int, vals) -> bytes | None:
    numbers = [v for _, _, v in vals]

    # The requested operation: repeatedly divide by 10 while ALL values
    # can be divided exactly. For example 1000, 2000, 3000 -> /10 ->
    # 100,200,300 -> /10 -> 10,20,30 -> /10 -> 1,2,3.
    common = min((_factor10(v) for v in numbers if v), default=0)
    if common <= 0:
        return None

    divisor = 10 ** common
    reduced = [v // divisor for v in numbers]

    payload = bytearray()
    payload.append(common)
    payload.extend(_put_varint(len(reduced)))

    for v in reduced:
        # signed magnitude with a tiny ZigZag-like representation.
        z = (v << 1) if v >= 0 else ((-v << 1) - 1)
        payload.extend(_put_varint(z))

    # Store the exact separators between numbers.
    for i in range(len(vals) - 1):
        sep = data[vals[i][1]:vals[i + 1][0]]
        payload.extend(_put_varint(len(sep)))
        payload.extend(sep)

    record = bytes((_RUN,)) + _put_varint(end - start) + bytes(payload)
    return record


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
    return bytes(records)


def _unzigzag(z: int) -> int:
    return (z >> 1) if not (z & 1) else -((z >> 1) + 1)


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
                raise ValueError("truncated DE3 literal")
            out.extend(data[i:i + length])
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
        if count < 2:
            raise ValueError("invalid DE3 run count")

        values = []
        divisor = 10 ** scale
        for _ in range(count):
            z, i = _get_varint(data, i)
            values.append(_unzigzag(z) * divisor)

        start_out = len(out)
        for idx, value in enumerate(values):
            out.extend(str(value).encode("ascii"))
            if idx + 1 < count:
                sep_len, i = _get_varint(data, i)
                if i + sep_len > len(data):
                    raise ValueError("truncated DE3 separator")
                out.extend(data[i:i + sep_len])
                i += sep_len

        if len(out) - start_out != original_len:
            raise ValueError("DE3 run length mismatch")

    raise ValueError("missing DE3 end marker")


__all__ = ["transform", "inverse"]
