from divideencode.v2.structural_v5 import adaptive_transform, analyze, inverse, transform


def test_raw_roundtrip():
    data = b"raw-data-" * 100
    assert inverse(transform(data)) == data


def test_fixed_record_roundtrip():
    rows = []
    for i in range(2000):
        rows.append(i.to_bytes(4, "little") + (100000 + i * 3).to_bytes(4, "little") + bytes((i & 255, 7, 0, 1)))
    data = b"".join(rows)
    candidates = analyze(data, max_depth=3)
    assert candidates
    assert all(inverse(c.blob) == data for c in candidates[:10])


def test_column_delta_roundtrip():
    data = b"".join((i * 7).to_bytes(4, "little") + (1000 + i).to_bytes(4, "little") for i in range(5000))
    blob = transform(data, max_depth=3)
    assert inverse(blob) == data
    assert len(blob) < len(data)


def test_composed_roundtrip():
    data = (b"record,100,200,active\n" * 5000)
    candidates = analyze(data, max_depth=3)
    assert candidates
    assert inverse(candidates[0].blob) == data


def test_adaptive_never_regresses():
    data = bytes(range(256)) * 256

    def scorer(blob):
        return len(blob)

    decision = adaptive_transform(data, scorer, max_depth=3)
    assert decision.downstream_size <= len(data)
    assert inverse(decision.blob) == data
