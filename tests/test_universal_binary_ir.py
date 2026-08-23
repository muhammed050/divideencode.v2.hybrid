from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from divideencode import de2
from divideencode.v3 import universal_binary_ir as ubir


def test_json_roundtrip_preserves_bytes():
    data = b'{\n  "name": "Ali",\n  "age": 24,\n  "city": "Istanbul",\n  "items": [24, 25, 26, 24]\n}\n'
    blob = ubir.encode(data, "json")
    assert ubir.decode(blob) == data
    assert ubir.candidates(data, ".json")


def test_json_transform_is_selected_by_final_de2_size():
    data = b'{"a":"repeat","b":"repeat","c":"repeat","n":100,"m":105,"k":110}'
    direct = de2.compress(data, block_size=1 << 20, level="BALANCED")
    blob = ubir.encode(data, "json")
    packed = de2.compress(blob, block_size=1 << 20, level="BALANCED")
    assert ubir.decode(blob) == data
    # The IR itself is allowed to be larger than the source; only the final
    # packed representation is the optimization criterion.
    assert len(packed) <= len(direct)


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
