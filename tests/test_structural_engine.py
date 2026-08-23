from divideencode.v2.structural import adaptive_transform, transform, inverse, analyze


def test_roundtrip_raw():
    data = bytes(range(256)) * 3
    assert inverse(transform(data)) == data


def test_delta_structured():
    values = list(range(1000, 100000, 7))
    data = b''.join(v.to_bytes(4, 'little') for v in values)
    blob = transform(data)
    assert inverse(blob) == data
    assert len(blob) < len(data)
    assert analyze(data)[0].kind == 'delta'


def test_rle():
    data = (b'A' * 5000) + (b'B' * 3000) + (b'C' * 2000)
    blob = transform(data)
    assert inverse(blob) == data
    assert len(blob) < len(data)


def test_dictionary():
    rows = [b'ERROR|Istanbul|5001|FAILED'] * 500
    data = b''.join(rows)
    blob = transform(data)
    assert inverse(blob) == data
    assert len(blob) < len(data)


def test_adaptive_decision_can_reject_structural():
    data = b'raw-data' * 100

    def scorer(blob):
        # Simulate a downstream compressor that strongly prefers RAW.
        return 1 if blob[3] == 0 else 10_000

    decision = adaptive_transform(data, scorer=scorer)
    assert decision.kind == 'raw'
    assert inverse(decision.blob) == data
    assert decision.downstream_size == 1


def test_adaptive_decision_can_select_structural():
    values = list(range(1000, 5000, 7))
    data = b''.join(v.to_bytes(4, 'little') for v in values)

    def scorer(blob):
        return 1 if blob[3] == 1 else 10_000

    decision = adaptive_transform(data, scorer=scorer)
    assert decision.kind == 'delta'
    assert inverse(decision.blob) == data
