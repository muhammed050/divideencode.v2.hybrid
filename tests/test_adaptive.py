from divideencode.v3.adaptive import analyze, search_block


def test_search_is_deterministic():
    data = (b"abc123" * 5000) + (bytes(range(64)) * 100)
    assert search_block(data, depth=2, beam=8) == search_block(data, depth=2, beam=8)


def test_analysis_uses_one_mib_blocks():
    data = b"A" * (2 * 1024 * 1024 + 17)
    winners = analyze(data, block_size=1024 * 1024)
    assert len(winners) == 3
    assert all(w.cost > 0 for w in winners)


def test_candidate_accounts_for_metadata():
    data = b"A" * 10000
    winner = search_block(data)
    assert winner.cost >= 8 + len(winner.chain)
