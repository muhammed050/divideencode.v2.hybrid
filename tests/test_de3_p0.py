import pytest

from divideencode.de3_p0 import compress, decompress


def test_empty_roundtrip():
    blob = compress(b"")
    assert decompress(blob) == b""


def test_roundtrip_repetitive():
    data = (b"hello world " * 5000) + bytes(range(256)) * 20
    assert decompress(compress(data)) == data


def test_roundtrip_binary():
    data = bytes((i * 37 + (i >> 3)) & 255 for i in range(100_000))
    assert decompress(compress(data)) == data


def test_random_roundtrip():
    data = bytes(range(256)) * 257
    assert decompress(compress(data)) == data


def test_corruption_rejected():
    data = b"abcde" * 5000
    blob = bytearray(compress(data))
    blob[-1] ^= 1
    with pytest.raises(Exception):
        decompress(blob)


def test_truncation_rejected():
    data = b"some structured text " * 2000
    blob = compress(data)
    with pytest.raises(Exception):
        decompress(blob[:-1])
