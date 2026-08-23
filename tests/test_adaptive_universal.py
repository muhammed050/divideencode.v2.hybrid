import random

import pytest

from divideencode.adaptive_universal import (
    FLAG_BWT_MTF, FLAG_BWT_MTF_RLE, FLAG_DIRECT,
    analyze, compress, consecutive_repetition_ratio, decompress,
    shannon_entropy,
)


def test_entropy_and_repetition_metrics():
    assert shannon_entropy(b"a" * 1000) == 0.0
    assert consecutive_repetition_ratio(b"a" * 100) > 0.99
    assert shannon_entropy(bytes(range(256)) * 4) == pytest.approx(8.0)


def test_text_roundtrip_and_path_is_lossless():
    data = (b"record,id=000001,status=active,value=12345\\n" * 1000)
    blob = compress(data, filename="records.log")
    assert blob[0] in (FLAG_BWT_MTF, FLAG_BWT_MTF_RLE, FLAG_DIRECT)
    assert decompress(blob) == data


def test_binary_and_compressed_signatures_use_direct_path():
    data = b"PK\\x03\\x04" + bytes(range(256)) * 100
    blob = compress(data, filename="x.zip")
    assert blob[0] == FLAG_DIRECT
    assert decompress(blob) == data


def test_random_data_roundtrip():
    rng = random.Random(1234)
    data = bytes(rng.randrange(256) for _ in range(12000))
    blob = compress(data, filename="random.bin")
    assert blob[0] == FLAG_DIRECT
    assert decompress(blob) == data


def test_corruption_detected_by_wrapper_checksum():
    data = b"hello world " * 1000
    blob = bytearray(compress(data, filename="x.txt"))
    blob[-1] ^= 1
    with pytest.raises(Exception):
        decompress(bytes(blob))


def test_micro_trial_is_bounded():
    data = b"abcde" * 5000
    metrics = analyze(data, filename="x.txt", trial_size=8192)
    assert 0.0 <= metrics.zero_ratio <= 1.0
