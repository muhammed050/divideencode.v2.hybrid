import random

import pytest

from divideencode.universal import decode, encode, compress, decompress


def test_du1_roundtrip_empty():
    assert decode(encode(b"")) == b""


def test_du1_roundtrip_representative_data():
    samples = [
        b"a" * 4096,
        (b"abcdefghijklmnopqrstuvwxyz0123456789" * 500),
        bytes(range(256)) * 20,
        bytes((i * 37 + 11) & 255 for i in range(8192)),
    ]
    for data in samples:
        assert decode(encode(data)) == data


def test_du1_fuzz_roundtrip():
    rng = random.Random(0xD3E2)
    for size in [1, 2, 3, 7, 31, 32, 255, 256, 257, 1024]:
        data = bytes(rng.randrange(256) for _ in range(size))
        assert decode(encode(data)) == data


def test_du1_de2_roundtrip():
    data = (b"record:00000001,status=active,value=100\n" * 3000)
    blob = compress(data)
    assert decompress(blob) == data


def test_du1_corruption_is_detected():
    data = b"hello world " * 500
    blob = bytearray(compress(data))
    blob[-1] ^= 0x01
    with pytest.raises(Exception):
        decompress(bytes(blob))
