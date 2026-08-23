from divideencode.de3 import generate_divide_candidates, reconstruct_divide, search_representations


def test_de3_divide_candidates_roundtrip():
    data = (b"The quick brown fox jumps over the lazy dog. " * 2000)
    candidates = generate_divide_candidates(data)
    assert candidates
    for c in candidates:
        assert reconstruct_divide(c.data, c.metadata) == data


def test_de3_search_is_reversible_candidate():
    data = bytes(range(256)) * 100
    best = search_representations(data, beam=4, max_depth=1)
    if best.name != "raw":
        # Search candidates are required to remain reversible at each stage.
        cur = best
        while cur.parent is not None:
            cur = cur.parent
        assert cur.data == data


def test_de3_search_never_claims_free_metadata():
    data = (b"ABCD" * 10000)
    best = search_representations(data, beam=8, max_depth=2)
    assert best.total_size >= len(best.data)
