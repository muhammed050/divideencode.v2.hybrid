from pathlib import Path
from divideencode.v3 import hybrid_json_ir as h


def test_roundtrip_whitespace_and_json_lexemes():
    data=b'{\n  "a" : 100,\n  "b" : 105,\n  "s" : "repeat",\n  "t" : "repeat"\n}\n'
    blob=h.encode(data)
    assert h.decode(blob)==data


def test_large_json_roundtrip():
    data=(Path(__file__).parent.parent/'benchmarks'/'corpus'/'json_large.json').read_bytes()
    assert h.decode(h.encode(data))==data
