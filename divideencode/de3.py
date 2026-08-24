"""DE3: fast numeric-factor transform.

The transform is deliberately deterministic and cheap: decimal integer runs are
encoded as mantissa + count of trailing decimal zeroes. Non-numeric bytes are
kept verbatim. It is lossless and intended as a preprocessing experiment.

Wire format is private to DE3:
  0x00 literal byte, followed by the byte
  0x01 integer token, followed by varint(magnitude), one byte(scale)
  0x02 end of stream

A token is emitted only when a decimal integer has at least one trailing zero;
otherwise the original bytes are emitted as literals. This keeps the transform
simple and avoids making common non-factorable numbers larger.
"""

from __future__ import annotations

_DIGITS = b"0123456789"


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


def _factor10(magnitude: int) -> tuple[int, int]:
    scale = 0
    while magnitude and magnitude % 10 == 0:
        magnitude //= 10
        scale += 1
    return magnitude, scale


def transform(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        data = bytes(data)
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if 48 <= b <= 57:
            j = i + 1
            while j < n and 48 <= data[j] <= 57:
                j += 1
            token = data[i:j]
            # Do not turn a leading-zero decimal token into an integer: the
            # spelling itself is meaningful in text formats.
            if len(token) == 1 or token[0] != 48:
                magnitude = int(token)
                mantissa, scale = _factor10(magnitude)
                # Token is useful only if it actually factors and its compact
                # representation is no larger than the original token.
                encoded = bytes((1,)) + _put_varint(mantissa) + bytes((scale,))
                if scale and len(encoded) < len(token) + 1:
                    out += encoded
                    i = j
                    continue
        out += bytes((0, b))
        i += 1
    out.append(2)
    return bytes(out)


def inverse(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        data = bytes(data)
    out = bytearray()
    i = 0
    while i < len(data):
        tag = data[i]
        i += 1
        if tag == 2:
            if i != len(data):
                raise ValueError("trailing data after DE3 end marker")
            return bytes(out)
        if tag == 0:
            if i >= len(data):
                raise ValueError("truncated DE3 literal")
            out.append(data[i])
            i += 1
            continue
        if tag == 1:
            mantissa, i = _get_varint(data, i)
            if i >= len(data):
                raise ValueError("truncated DE3 scale")
            scale = data[i]
            i += 1
            out += str(mantissa * (10 ** scale)).encode("ascii")
            continue
        raise ValueError(f"unknown DE3 tag {tag}")
    raise ValueError("missing DE3 end marker")


__all__ = ["transform", "inverse"]
