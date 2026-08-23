from divideencode.adaptive_de2 import compress, decompress


def test_adaptive_de2_roundtrip_json():
    data = (b'{"id":123,"name":"Ali","city":"Istanbul"}\n' * 50)
    assert decompress(compress(data)) == data


def test_adaptive_de2_roundtrip_csv():
    data = (b"id,name,city\n1,Ali,Istanbul\n2,Ali,Istanbul\n" * 50)
    assert decompress(compress(data)) == data


def test_adaptive_de2_roundtrip_text():
    data = (b"the quick brown fox jumps over the quick brown fox\n" * 100)
    assert decompress(compress(data)) == data
