from divideencode.de2 import block_modes, compress, decompress
from divideencode.de2.phrase import decode as phrase_decode
from divideencode.de2.phrase import encode as phrase_encode


def test_phrase_ir_roundtrip():
    data = (b"alpha beta gamma delta " * 400) + b"tail"
    transformed, meta = phrase_encode(data, phrase_len=6, max_dict=255)
    assert transformed is not None
    assert phrase_decode(transformed, meta, len(data)) == data


def test_de2_phrase_candidate_roundtrip():
    data = (b"the quick brown fox jumps over the lazy dog; " * 3000)
    blob = compress(data)
    assert decompress(blob) == data
    assert len(blob) < len(data)
    assert block_modes(blob) in (["LZ"], ["STRUCT+LZ"])
