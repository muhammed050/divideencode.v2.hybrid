from divideencode.ubc import compile, decode, encode, decompile


def test_ubc_empty():
    data = b""
    program = encode(data)
    assert decode(program) == data


def test_ubc_random_bytes():
    data = bytes((i * 73 + 41) & 0xFF for i in range(10000))
    assert decompile(compile(data)) == data


def test_ubc_all_byte_values():
    data = bytes(range(256)) * 100
    assert decode(encode(data)) == data


def test_ubc_binary_with_zeros():
    data = b"\x00" * 4096 + bytes(range(256)) + b"\xff" * 4096
    assert decode(encode(data)) == data
