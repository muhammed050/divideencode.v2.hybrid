import os

from divideencode.v2.universal import compress, decompress, compress_if_smaller


def test_empty_roundtrip():
    blob = compress(b"")
    assert decompress(blob) == b""


def test_text_roundtrip():
    data = (b"The quick brown fox jumps over the lazy dog. " * 5000)
    assert decompress(compress(data, block_size=8192)) == data


def test_mixed_data_roundtrip():
    text = (b"alpha,beta,gamma,delta\n" * 3000)
    numeric = bytes((i * 17 + (i >> 8)) & 0xFF for i in range(90000))
    random_tail = os.urandom(50000)
    data = text + random_tail + numeric + text[:17000]
    assert decompress(compress(data, block_size=16384)) == data


def test_tiny_and_incompressible_roundtrip():
    for n in range(1, 128):
        data = bytes((i * 131 + 17) & 0xFF for i in range(n))
        assert decompress(compress(data)) == data


def test_candidate_is_lossless():
    data = (b"0123456789abcdef" * 20000) + os.urandom(70000)
    blob = compress_if_smaller(data, block_size=32768)
    # compress_if_smaller may return a normal DE2 container, so validate by
    # dispatching on the magic selected by the caller in real use below.
    if blob[:4] == b"DUV1":
        assert decompress(blob) == data
    else:
        from divideencode.v2.codec import decompress as de2_decompress
        assert de2_decompress(blob) == data
