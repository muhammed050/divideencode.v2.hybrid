from divideencode.v2.structural_v3 import adaptive_transform, analyze, inverse, transform


def test_raw_roundtrip():
    data = b"raw-data-" * 100
    assert inverse(transform(data)) == data


def test_numeric_delta_roundtrip():
    data = b"".join(v.to_bytes(4, "little") for v in range(1000, 100000, 7))
    blob = transform(data)
    assert inverse(blob) == data
    assert len(blob) < len(data)


def test_composed_pipeline_roundtrip():
    # Repeated numeric values make delta + RLE/dictionary candidates useful.
    values = [1000] * 5000 + [1007] * 5000 + [1014] * 5000
    data = b"".join(v.to_bytes(4, "little") for v in values)
    candidates = analyze(data, max_depth=2)
    assert candidates
    assert all(inverse(c.blob) == data for c in candidates[:5])
    assert inverse(candidates[0].blob) == data


def test_adaptive_can_keep_raw():
    data = bytes(range(256)) * 100

    def scorer(blob):
        return 1 if len(blob) >= len(data) else 1000

    decision = adaptive_transform(data, scorer)
    assert decision.kinds == ()
    assert inverse(decision.blob) == data


def test_adaptive_selects_smaller_candidate():
    data = b"abc123," * 20000

    def scorer(blob):
        return len(blob)

    decision = adaptive_transform(data, scorer)
    assert decision.kinds
    assert decision.downstream_size == len(decision.blob)
    assert inverse(decision.blob) == data
