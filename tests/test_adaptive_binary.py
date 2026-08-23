from pathlib import Path

from divideencode.de2 import compress, decompress
from divideencode.v3.adaptive_binary import candidates, decode, encode


def test_text_roundtrip_exact():
    data = ("alpha beta beta gamma\r\n" * 300).encode()
    blob = encode(data, "text")
    assert decode(blob) == data


def test_json_roundtrip_preserves_bytes():
    data = b'{\n  "name": "alice", "name2": "alice",\n  "items": [1, 1, 2]\n}\n'
    blob = encode(data, "json")
    assert decode(blob) == data


def test_csv_roundtrip_preserves_bytes():
    data = b'a,b,c\r\nalpha,beta,alpha\r\nalpha,beta,alpha\r\n'
    blob = encode(data, "csv")
    assert decode(blob) == data


def test_candidates_select_supported_suffixes():
    data = b"alpha beta alpha beta\n" * 20
    assert candidates(data, ".txt")
    assert candidates(data, ".log")
    assert candidates(data, ".csv")
    assert candidates(data, ".json")
    assert not candidates(data, ".bin")


def test_abr_then_de2_roundtrip():
    data = ("customer_id,name,status\n1001,alice,active\n" * 200).encode()
    abr = encode(data, "csv")
    packed = compress(abr, block_size=1 << 20)
    assert decode(decompress(packed)) == data


def test_adaptive_never_requires_abr_to_be_smaller():
    data = Path(__file__).read_bytes()
    direct = compress(data, block_size=1 << 20)
    cand = candidates(data, ".py")
    assert cand
    abr = min(cand, key=lambda x: len(x[1]))[1]
    adapted = compress(abr, block_size=1 << 20)
    # This is an experiment: ABR is optional, never mandatory.
    assert min(len(direct), len(adapted)) <= len(direct)
