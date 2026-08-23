from divideencode.v2.structural import transform, inverse, analyze


def test_roundtrip_raw():
    data = bytes(range(256)) * 3
    assert inverse(transform(data)) == data


def test_delta_structured():
    values = list(range(1000, 100000, 7))
    data = b''.join(v.to_bytes(4, 'little') for v in values)
    blob = transform(data)
    assert inverse(blob) == data
    assert len(blob) < len(data)
    assert analyze(data)[0].kind == 'delta'


def test_rle():
    data = (b'A' * 5000) + (b'B' * 3000) + (b'C' * 2000)
    blob = transform(data)
    assert inverse(blob) == data
    assert len(blob) < len(data)


def test_dictionary():
    rows = [b'ERROR|Istanbul|5001|FAILED'] * 500
    data = b''.join(rows)
    blob = transform(data)
    assert inverse(blob) == data
    assert len(blob) < len(data)
