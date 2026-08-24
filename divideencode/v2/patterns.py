"""Cheap reversible transforms whose goal is to make changing data repeat.

No search tree: a tiny prefix sample decides whether each transform is worth
trying, then DE2 measures the resulting payload exactly.
"""

PATTERN_DELTA2 = 1
PATTERN_XOR = 2


def delta2(data):
    n = len(data)
    if n < 2:
        return bytes(data)
    out = bytearray(n)
    out[0] = data[0]
    prev_x = data[0]
    prev_d = (data[1] - prev_x) & 0xFF
    out[1] = prev_d
    prev_x = data[1]
    for i in range(2, n):
        x = data[i]
        d = (x - prev_x) & 0xFF
        out[i] = (d - prev_d) & 0xFF
        prev_x = x
        prev_d = d
    return bytes(out)


def undelta2(data):
    n = len(data)
    if n < 2:
        return bytes(data)
    out = bytearray(n)
    out[0] = data[0]
    prev_x = out[0]
    prev_d = data[1]
    prev_x = (prev_x + prev_d) & 0xFF
    out[1] = prev_x
    for i in range(2, n):
        prev_d = (prev_d + data[i]) & 0xFF
        prev_x = (prev_x + prev_d) & 0xFF
        out[i] = prev_x
    return bytes(out)


def xor_prev(data):
    out = bytearray(len(data))
    prev = 0
    for i, b in enumerate(data):
        out[i] = b ^ prev
        prev = b
    return bytes(out)


def unxor_prev(data):
    out = bytearray(len(data))
    prev = 0
    for i, b in enumerate(data):
        prev ^= b
        out[i] = prev
    return bytes(out)


def should_try(data, kind):
    """O(1)-ish sampled gate; never scans the whole input."""
    n = len(data)
    if n < 2048:
        return False
    sample = data[:min(n, 16384)]
    if kind == PATTERN_XOR:
        # XOR is useful when adjacent bytes share many high bits / are close.
        small = 0
        prev = sample[0]
        for b in sample[1:]:
            d = b ^ prev
            small += d < 32
            prev = b
        return small / max(1, len(sample) - 1) > 0.20
    # Second delta is useful when first differences themselves repeat.
    small = 0
    repeat = 0
    prev = sample[0]
    prev_d = None
    for b in sample[1:]:
        d = (b - prev) & 0xFF
        if d < 16 or d > 240:
            small += 1
        if prev_d is not None and d == prev_d:
            repeat += 1
        prev = b
        prev_d = d
    return (small / max(1, len(sample) - 1) > 0.35 or
            repeat / max(1, len(sample) - 2) > 0.12)


def apply(data, kind):
    if kind == PATTERN_DELTA2:
        return delta2(data)
    if kind == PATTERN_XOR:
        return xor_prev(data)
    raise ValueError("unknown DE2 pattern transform")


def inverse(data, kind):
    if kind == PATTERN_DELTA2:
        return undelta2(data)
    if kind == PATTERN_XOR:
        return unxor_prev(data)
    raise ValueError("unknown DE2 pattern transform")
