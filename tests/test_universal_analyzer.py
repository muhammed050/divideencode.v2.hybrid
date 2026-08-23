from divideencode.v3.universal_analyzer import candidates, decode, detect, encode


def test_text_roundtrip():
    data = (b"hello world hello world\n" * 100)
    assert detect(data, ".txt") == "text"
    for c in candidates(data, ".txt"):
        assert decode(c.blob) == data


def test_source_roundtrip():
    data = (b"int value = value + 1;\n" * 100)
    assert detect(data, ".c") == "source"
    blob = encode(data, "source")
    assert decode(blob) == data


def test_binary_roundtrip():
    data = bytes(range(256)) * 100
    assert detect(data, ".raw") == "binary"
    blob = encode(data, "binary")
    assert decode(blob) == data


def test_json_delegation_roundtrip():
    data = b'{"name":"x","name":"x","n":123,"n":123}'
    blob = encode(data, "json")
    assert decode(blob) == data
