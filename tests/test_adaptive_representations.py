import random

from divideencode.v2.hybrid import compress, decompress, METHOD_REP_DE2
from divideencode.v2.represent import (
    REP_BITPLANE, REP_DELTA16, REP_DELTA32, REP_XOR16,
    apply, inverse,
)


def test_representation_roundtrips():
    rng = random.Random(12345)
    cases = [
        b"",
        b"abc" * 101,
        bytes(range(256)) * 9,
        bytes(rng.randrange(256) for _ in range(4097)),
    ]
    for data in cases:
        for rep in (REP_BITPLANE, REP_DELTA16, REP_DELTA32, REP_XOR16):
            if rep in (REP_DELTA16, REP_XOR16) and len(data) % 2:
                continue
            if rep == REP_DELTA32 and len(data) % 4:
                continue
            transformed = apply(rep, data)
            assert len(transformed) == len(data)
            assert inverse(rep, transformed) == data


def test_adaptive_representation_container_roundtrip():
    # Structured binary where representation search is allowed explicitly.
    data = bytearray()
    for i in range(12000):
        data.extend((i * 257 & 0xFFFF).to_bytes(2, "little"))
    data = bytes(data)

    blob, method = compress(data, try_de2=True, try_representations=True)
    assert decompress(blob) == data
    assert method in {"STORED", "LZMA", "DELTA+LZMA", "DE2", "REP+DE2"}


def test_adaptive_search_never_changes_original_for_random_data():
    rng = random.Random(777)
    data = bytes(rng.randrange(256) for _ in range(4096))
    blob, _ = compress(data, try_de2=True, try_representations=True)
    assert decompress(blob) == data


def test_rep_method_can_be_decoded_when_selected():
    # Exercise the explicit representation lane even if the adaptive winner
    # changes with codec internals: construct and decode every representation
    # through the same DE2 payload contract.
    from divideencode.v2 import codec as de2
    from divideencode.v2.hybrid import MAGIC, encode_varint
    import zlib

    data = bytes(range(256)) * 32
    for rep in (REP_BITPLANE, REP_DELTA16, REP_DELTA32, REP_XOR16):
        transformed = apply(rep, data)
        payload = bytes((rep,)) + de2.compress(transformed)
        blob = MAGIC + encode_varint(len(data)) + (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little") + bytes((METHOD_REP_DE2,)) + payload
        assert decompress(blob) == data
