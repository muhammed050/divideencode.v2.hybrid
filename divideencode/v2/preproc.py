    pos = 0
    for ln in lens:
        planes.append(undelta_bytes(packed[pos:pos + ln]))
        pos += ln
    if pos != len(packed):
        raise ValueError("plane payload truncated")
    out = bytearray(expected_len)
    for c in range(k):
        out[c::k] = planes[c]
    return bytes(out)


# ---- word split (DIVIDE-lite numeric transform) ----------------------------

from ..divide_transform import pack_bits, unpack_bits


def word_split(data, w, s):
    """Split LE words of width w into quotient stream + packed remainders.

    Returns (q_bytes, r_values, tail, wq).

    The quotient width is computed from every complete input word, not a
    sample, because a sampled maximum can underestimate the true maximum and
    make the later ``to_bytes`` operation overflow.
    """
    n = len(data)
    nw = n // w
    tail = data[nw * w:]
    frombytes = int.from_bytes
    mq = 0
    for i in range(nw):
        v = frombytes(data[i * w:i * w + w], "little")
        q = v >> s
        if q > mq:
            mq = q
    wq = max(1, (mq.bit_length() + 7) // 8)
    qb = bytearray(nw * wq)
    rs = []
    rap = rs.append
    mask = (1 << s) - 1
    for i in range(nw):
        v = frombytes(data[i * w:i * w + w], "little")
        qb[i * wq:(i + 1) * wq] = (v >> s).to_bytes(wq, "little")
        rap(v & mask)
    return bytes(qb), rs, tail, wq


def word_join(q_bytes, r_values, tail, w, s, wq, expected_len):
    out = bytearray()
    frombytes = int.from_bytes
    for i in range(len(r_values)):
        q = frombytes(q_bytes[i * wq:(i + 1) * wq], "little")
        out += ((q << s) | r_values[i]).to_bytes(w, "little")
    out += tail
    if len(out) != expected_len:
        raise ValueError("word join size mismatch")
    return bytes(out)
