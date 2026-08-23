"""Round-trip tests for the V2.0 universal binary normalizer."""
from __future__ import annotations

from divideencode.v3 import universal_binary_normalizer as ubn


def test_all_transforms_roundtrip():
    samples = [
        b"",
        b"a",
        b"\x00\xff\x00\xff" * 17,
        bytes(range(256)) * 5,
        (b"hello world " * 1000),
        bytes((i * 37 + 11) & 0xFF for i in range(4097)),
    ]
    for data in samples:
        for name, transformed in ubn.candidates(data):
            blob = ubn.pack(name, transformed, len(data))
            assert ubn.restore(blob) == data, name
