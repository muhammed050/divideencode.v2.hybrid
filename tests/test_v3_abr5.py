from divideencode.v3 import adaptive_binary_v5 as abr5


def test_roundtrip_representative_text():
    samples = [
        b'alpha beta alpha beta\\n' * 20,
        b'city,age\\nAleppo,24\\nAleppo,25\\nAleppo,26\\n',
        b'{"user":"Ali","age":24,"city":"Aleppo","user2":"Ali"}',
        ('line 100 value 101 value 102\\n' * 100).encode(),
    ]
    for data in samples:
        suffix = '.csv' if b',' in data and data.startswith(b'city') else ('.json' if data.startswith(b'{') else '.txt')
        cs = abr5.candidates(data, suffix)
        assert cs
        for _, blob in cs:
            assert abr5.decode(blob) == data


def test_empty_roundtrip():
    blob = abr5.encode(b'', 'text')
    assert abr5.decode(blob) == b''
