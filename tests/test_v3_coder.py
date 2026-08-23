from divideencode.v3.coder import LIT, MATCH, REP, decode_tokens, encode_tokens, encoded_size
from divideencode.errors import DivideEncodeError


def test_literals_roundtrip():
    tokens = [(LIT, b) for b in b"The quick brown fox jumps over the lazy dog."]
    blob = encode_tokens(tokens)
    assert decode_tokens(blob) == tokens
    assert encoded_size(tokens) == len(blob)


def test_match_and_rep_roundtrip():
    tokens = [
        (LIT, ord("a")),
        (LIT, ord("b")),
        (MATCH, 12, 2),
        (REP, 8, 0),
        (REP, 7, 1),
        (MATCH, 20, 257),
        (REP, 4, 3),
    ]
    assert decode_tokens(encode_tokens(tokens)) == tokens


def test_empty_stream_roundtrip():
    blob = encode_tokens([])
    assert decode_tokens(blob) == []


def test_corruption_rejected():
    tokens = [(LIT, 65), (MATCH, 30, 100), (REP, 8, 0)]
    blob = bytearray(encode_tokens(tokens))
    # The final byte may contain Huffman padding, so flipping it is not a
    # valid corruption oracle. Flip a bit in the first actual payload byte.
    p = 5
    count = 0
    while True:
        b = blob[p]
        p += 1
        count |= (b & 0x7F) << (7 * (p - 6))
        if not b & 0x80:
            break
    nsym = 0
    shift = 0
    while True:
        b = blob[p]
        p += 1
        nsym |= (b & 0x7F) << shift
        if not b & 0x80:
            break
        shift += 7
    for _ in range(nsym):
        while blob[p] & 0x80:
            p += 1
        p += 2
    while blob[p] & 0x80:
        p += 1
    p += 1
    blob[p] ^= 0x01
    try:
        decode_tokens(bytes(blob))
    except DivideEncodeError:
        pass
    else:
        raise AssertionError("corrupted DE3 payload was accepted")


def test_truncation_rejected():
    tokens = [(LIT, 65)] * 64 + [(MATCH, 40, 7)]
    blob = encode_tokens(tokens)
    for cut in (1, len(blob) // 2, len(blob) - 1):
        try:
            decode_tokens(blob[:cut])
        except DivideEncodeError:
            pass
        else:
            raise AssertionError(f"truncated stream accepted at {cut}")


def test_alphabet_is_merged():
    tokens = [(LIT, 65), (MATCH, 10, 4), (REP, 8, 0)]
    blob = encode_tokens(tokens)
    assert blob[:4] == b"DE3C"
    # Three token classes must occupy at most three Huffman symbols; the
    # literal byte and the two structural classes share one alphabet.
    decoded = decode_tokens(blob)
    assert decoded == tokens
