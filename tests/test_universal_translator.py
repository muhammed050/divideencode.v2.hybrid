from divideencode.de2 import compress, decompress, block_modes


def test_universal_text_roundtrip():
    data = (b"function main() { return 42; }\n" * 4000)
    blob = compress(data)
    assert decompress(blob) == data
    assert block_modes(blob)[0] in {"STRUCT+LZ", "STRUCT_LZ", "LZ"}


def test_universal_random_falls_back_without_expansion():
    data = bytes(range(256)) * 1024
    blob = compress(data)
    assert decompress(blob) == data
    assert len(blob) < len(data)


def test_universal_empty():
    data = b""
    blob = compress(data)
    assert decompress(blob) == data
