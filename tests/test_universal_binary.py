from divideencode.universal_binary import (
    SearchMode,
    compress,
    compress_with_stats,
    decompress,
    rank_candidates,
)
from divideencode.universal_ir import Kind


def test_ubir2_roundtrip_repetitive_binary():
    data = (b"HEADER-0001\x00\x01\x02\x03" * 4096) + bytes(range(256)) * 32
    blob = compress(data, mode=SearchMode.BALANCED, level="FAST")
    assert decompress(blob) == data


def test_ubir2_roundtrip_random():
    data = bytes(((i * 73) + 19) & 0xFF for i in range(100_000))
    blob = compress(data, mode=SearchMode.FAST, level="FAST")
    assert decompress(blob) == data


def test_ubir2_always_keeps_direct_baseline():
    data = bytes(range(256)) * 256
    candidates = rank_candidates(data, mode=SearchMode.BALANCED)
    assert candidates[0] == Kind.DIRECT
    result = compress_with_stats(data, mode=SearchMode.FAST, level="FAST")
    assert result.kind in Kind
    assert result.data
    assert result.candidates_tested >= 1
