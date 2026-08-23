from divideencode.v2.structural_v4 import adaptive_transform, analyze, inverse, transform


def test_raw_roundtrip():
    data = b"raw-data-" * 100
    assert inverse(transform(data)) == data


def test_numeric_delta_roundtrip():
    data = b"".join(v.to_bytes(4, "little") for v in range(1000, 100000, 7))
    blob = transform(data)
    assert inverse(blob) == data
    assert len(blob) < len(data)


def test_xor_roundtrip():
    data = bytes(range(256)) * 64
    candidates = analyze(data, max_depth=2)
    assert candidates
    assert all(inverse(c.blob) == data for c in candidates[:10])


def test_composed_roundtrip():
    data = b"abc123," * 20000
    candidates = analyze(data, max_depth=3)
    assert candidates
    assert inverse(candidates[0].blob) == data


def test_adaptive_never_forces_raw_regression():
    data = bytes(range(256)) * 100

    def scorer(blob):
        return len(blob)

    decision = adaptive_transform(data, scorer, max_depth=3)
    assert decision.downstream_size <= len(data)
    assert inverse(decision.blob) == data
