from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from divideencode.v3 import binary_json


def test_binary_json_roundtrip_formatting():
    data=b'{\n  "name" : "Ali",\n  "age" : 24,\n  "items" : [ 24,25 , 26 ]\n}\n'
    blob=binary_json.encode(data)
    assert binary_json.decode(blob)==data


def test_binary_json_roundtrip_scalars_and_lexical_numbers():
    data=b'{"a":-10,"b":1.20e+3,"c":true,"d":false,"e":null,"a":20}'
    assert binary_json.decode(binary_json.encode(data))==data


def test_binary_json_large_corpus_roundtrip():
    p=Path(__file__).parents[1]/"benchmarks"/"corpus"/"json_large.json"
    data=p.read_bytes()
    assert binary_json.decode(binary_json.encode(data))==data
