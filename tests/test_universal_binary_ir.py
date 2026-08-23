from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from divideencode.v3 import universal_binary_ir as ubir


def test_json_roundtrip_preserves_bytes():
    data = b'{\n  "name": "Ali",\n  "age": 24,\n  "city": "Istanbul",\n  "items": [24, 25, 26, 24]\n}\n'
    blob = ubir.encode(data, "json")
    assert ubir.decode(blob) == data
    assert ubir.candidates(data, ".json")


def test_json_dictionary_and_delta_are_used():
    data = b'{"a":"repeat","b":"repeat","c":"repeat","n":100,"m":105,"k":110}'
    blob = ubir.encode(data, "json")
    assert len(blob) < len(data)
    assert ubir.decode(blob) == data


def test_csv_roundtrip():
    data = b"id,name,country\n1,Ali,TR\n2,Omar,TR\n3,Ali,SY\n4,Ali,TR\n"
    blob = ubir.encode(data, "csv")
    assert ubir.decode(blob) == data
    assert ubir.candidates(data, ".csv")


def test_noncanonical_csv_is_not_selected():
    data = b"id,name\r\n1,A\r\n2,B\r\n"
    assert ubir.candidates(data, ".csv") == []


def test_binary_and_text_are_not_claimed():
    assert ubir.candidates(b"\\x00\\xff\\x01", ".raw") == []
    assert ubir.candidates(b"hello hello", ".txt") == []
