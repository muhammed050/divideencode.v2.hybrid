from divideencode.adaptive_binary import encode, decode, choose_mode


def test_roundtrip_json_exact():
    data = b'{"id":123,"name":"Ali"}\n  {"id":124,"name":"Omar"}\n'
    assert decode(encode(data, "json")) == data


def test_roundtrip_csv_exact():
    data = b'id,name,city\n1,Ali,Istanbul\n2,Ali,Istanbul\n'
    assert decode(encode(data, "csv")) == data


def test_roundtrip_text_exact():
    data = (b"the quick brown fox jumps over the quick brown fox\n" * 100)
    assert decode(encode(data, "text")) == data


def test_auto_detection():
    assert choose_mode(b'{"a":1}') == "json"
    assert choose_mode(b"a,b\n1,2\n") == "csv"
    assert choose_mode(b"hello world\n") == "text"


def test_representation_is_binary():
    data = b'{"name":"Ali","name":"Ali"}'
    blob = encode(data, "json")
    assert blob[:4] == b"ABR1"
    assert b"\x00" in blob
