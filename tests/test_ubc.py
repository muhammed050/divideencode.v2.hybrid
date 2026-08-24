import os

from divideencode.ubc import compress, decode, encode, decompress


def test_ubc_empty():
    data = b""
    program = encode(data)
    assert decode(program) == data


def test_ubc_random_bytes():
    data = bytes((i * 73 + 41) & 0xFF for i in range(10000))
    assert decode(encode(data)) == data


def test_ubc_all_byte_values():
    data = bytes(range(256)) * 100
    assert decode(encode(data)) == data


def test_ubc_binary_with_zeros():
    data = b"\x00" * 4096 + bytes(range(256)) + b"\xff" * 4096
    assert decode(encode(data)) == data


def test_ubc_ir_roundtrip_structured_data():
    data = (b"record,id=000001,status=active,value=12345\n" * 1000)
    program = encode(data)
    assert decode(program) == data
    assert len(program) < len(data)


def test_ubc_de2_roundtrip_random_data():
    data = os.urandom(12000)
    blob = compress(data, mode="BALANCED")
    assert decompress(blob) == data


def test_ubc_de2_roundtrip_binary_words():
    data = b"".join(i.to_bytes(4, "little") for i in range(20000))
    blob = compress(data, mode="BALANCED")
    assert decompress(blob) == data


def test_ubc_is_no_longer_fixed_byte_program():
    data = b"A" * 4096
    program = encode(data)
    # The old UBC emitted 2 bytes per source byte plus a terminator. A real
    # IR compiler must not be forced to expand every input byte.
    assert len(program) < 2 * len(data)
