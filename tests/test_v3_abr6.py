from divideencode.v3 import adaptive_binary_v6 as abr6
from divideencode.v3 import adaptive_binary_v6_unified as unified


def test_json_roundtrip_and_candidate():
    data=(b'{"id":123,"name":"Alice","city":"Aleppo","active":true,"id2":124}'*20)
    cs=abr6.candidates(data,'.json')
    assert cs
    for _,blob in cs:
        raw,p=abr6._r(blob,6)
        out,q=abr6._json_decode(blob,p,raw)
        assert out==data and q==len(blob)


def test_csv_columnar_roundtrip_with_quotes():
    data=b'name,age,city\nAlice,24,Aleppo\nBob,25,"New, York"\nAlice,26,Aleppo\n'
    cs=abr6.candidates(data,'.csv')
    assert cs
    for _,blob in cs:
        raw,p=abr6._r(blob,6)
        out,q=abr6._csv_decode(blob,p,raw)
        assert out==data and q==len(blob)


def test_unified_contains_new_candidates():
    data=b'{"id":123,"name":"Alice","id2":124}'*20
    cs=unified.candidates(data,'.json')
    assert any(name.startswith('abr6:') for name,_ in cs)
