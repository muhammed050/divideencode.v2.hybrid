from pathlib import Path
import sys
import time
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from divideencode import de2
from divideencode.v3 import universal_binary_ir as ubir

CORPUS = Path(__file__).parent / "corpus"
BS = 1 << 20


def _u(n: int) -> bytes:
    out = bytearray()
    while n >= 128:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _r(data: bytes, p: int):
    n = 0
    shift = 0
    while True:
        b = data[p]
        p += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, p
        shift += 7


def _s(b: bytes) -> bytes:
    return _u(len(b)) + b


def _g(data: bytes, p: int):
    n, p = _r(data, p)
    return data[p:p + n], p + n


def json_ablation(data: bytes, mode: str) -> bytes:
    tokens = ubir._json_tokens(data)
    strings = Counter(t for t in tokens if t[:1] == b'"')
    use_dict = mode in {"dict", "both"}
    use_delta = mode in {"delta", "both"}
    dictionary = sorted(
        (x for x, n in strings.items() if use_dict and n >= 2),
        key=lambda x: (-strings[x] * len(x), x),
    )
    ids = {x: i for i, x in enumerate(dictionary)}
    out = bytearray(_u(len(dictionary)))
    for s in dictionary:
        out += _s(s)
    out += _u(len(tokens))
    prev_int = 0
    for t in tokens:
        if t[:1] in b"{}[],:":
            out.append(ubir.J_PUNCT)
            out += _s(t)
        elif t[:1] == b'"':
            i = ids.get(t)
            if i is None:
                out.append(ubir.J_STRING)
                out += _s(t)
            else:
                out.append(ubir.J_DICT)
                out += _u(i)
        elif ubir._JSON_INT.fullmatch(t.decode("ascii")):
            out.append(ubir.J_INT)
            value = int(t)
            n = value - prev_int if use_delta else value
            out += _u(ubir._zz(n))
            if use_delta:
                prev_int = value
        else:
            out.append(ubir.J_RAW)
            out += _s(t)
    return bytes(ubir.MAGIC + bytes([ubir.VERSION, ubir.K_JSON]) + _u(len(data)) + out)


def json_ablation_decode(blob: bytes, mode: str) -> bytes:
    if blob[:4] != ubir.MAGIC:
        raise ValueError("bad UBIR magic")
    raw, p = _r(blob, 6)
    payload = blob[p:]
    p = 0
    nd, p = _r(payload, p)
    dictionary = []
    for _ in range(nd):
        x, p = _g(payload, p)
        dictionary.append(x)
    count, p = _r(payload, p)
    out = bytearray()
    prev_int = 0
    for _ in range(count):
        tag = payload[p]
        p += 1
        if tag in (ubir.J_PUNCT, ubir.J_STRING, ubir.J_RAW):
            x, p = _g(payload, p)
            out += x
        elif tag == ubir.J_DICT:
            i, p = _r(payload, p)
            out += dictionary[i]
        elif tag == ubir.J_INT:
            z, p = _r(payload, p)
            value = ubir._uzz(z)
            if mode in {"delta", "both"}:
                prev_int += value
                value = prev_int
            out += str(value).encode("ascii")
        else:
            raise ValueError("bad tag")
    if p != len(payload) or len(out) != raw:
        raise ValueError("ablation roundtrip mismatch")
    return bytes(out)


def packed(blob: bytes):
    t = time.perf_counter()
    p = de2.compress(blob, block_size=BS, level="BALANCED")
    return len(p), time.perf_counter() - t


def run():
    p = CORPUS / "json_large.json"
    data = p.read_bytes()
    direct, dt = packed(data)
    print("UBIR JSON ABLATION — json_large.json")
    print(f"source={len(data):,} B direct_DE2={direct:,} B time={dt:.2f}s")
    for mode in ("dict", "delta", "both"):
        ir = json_ablation(data, mode)
        assert json_ablation_decode(ir, mode) == data
        size, et = packed(ir)
        print(f"{mode:>5s}: ir={len(ir):,} B packed={size:,} B delta={size-direct:+,} B ({(size/direct-1)*100:+.2f}%) enc={et:.2f}s")


if __name__ == "__main__":
    run()
