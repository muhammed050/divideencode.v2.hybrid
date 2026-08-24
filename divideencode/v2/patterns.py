"""Reversible pattern transforms for DE2 experiments."""

PATTERN_DELTA2 = 1
PATTERN_XOR = 2
PATTERN_RANK = 3


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
        prev_x, prev_d = x, d
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


def symbol_rank(data):
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    symbols = [b for b, c in enumerate(counts) if c]
    symbols.sort(key=lambda b: (-counts[b], b))
    k = len(symbols)
    bits = 1 if k <= 2 else (2 if k <= 4 else (4 if k <= 16 else 8))
    rank = [0] * 256
    for i, b in enumerate(symbols):
        rank[b] = i
    if bits == 8:
        stream = bytes(rank[b] for b in data)
    else:
        out = bytearray((len(data) * bits + 7) // 8)
        acc = nbits = pos = 0
        mask = (1 << bits) - 1
        for b in data:
            acc |= (rank[b] & mask) << nbits
            nbits += bits
            if nbits >= 8:
                out[pos] = acc & 255
                pos += 1
                acc >>= 8
                nbits -= 8
        if nbits:
            out[pos] = acc & 255
        stream = bytes(out)
    return stream, bytes(symbols), bits


def symbol_unrank(stream, dictionary, original_len, bits):
    if bits == 8:
        return bytes(dictionary[r] for r in stream[:original_len])
    out = bytearray(original_len)
    mask = (1 << bits) - 1
    acc = nbits = pos = 0
    for i in range(original_len):
        while nbits < bits:
            if pos >= len(stream):
                raise ValueError("truncated rank stream")
            acc |= stream[pos] << nbits
            pos += 1
            nbits += 8
        r = acc & mask
        acc >>= bits
        nbits -= bits
        if r >= len(dictionary):
            raise ValueError("invalid rank")
        out[i] = dictionary[r]
    return bytes(out)


def should_try(data, kind):
    n = len(data)
    if n < 2048:
        return False
    if kind == PATTERN_RANK:
        counts = [0] * 256
        for b in data:
            counts[b] += 1
        used = sum(c != 0 for c in counts)
        if used <= 16:
            return True
        top = sorted(counts, reverse=True)[:min(16, used)]
        return sum(top) / n > (0.35 if used == 256 else 0.70)
    sample = data[:min(n, 16384)]
    if kind == PATTERN_XOR:
        small = 0
        prev = sample[0]
        for b in sample[1:]:
            small += (b ^ prev) < 32
            prev = b
        return small / max(1, len(sample) - 1) > 0.20
    small = repeat = 0
    prev = sample[0]
    prev_d = None
    for b in sample[1:]:
        d = (b - prev) & 255
        small += d < 16 or d > 240
        repeat += prev_d is not None and d == prev_d
        prev, prev_d = b, d
    return small / max(1, len(sample) - 1) > 0.35 or repeat / max(1, len(sample) - 2) > 0.12


def apply(data, kind):
    if kind == PATTERN_DELTA2:
        return delta2(data)
    if kind == PATTERN_XOR:
        return xor_prev(data)
    raise ValueError("rank uses symbol_rank()")


def inverse(data, kind):
    if kind == PATTERN_DELTA2:
        return undelta2(data)
    if kind == PATTERN_XOR:
        return unxor_prev(data)
    raise ValueError("rank uses symbol_unrank()")
