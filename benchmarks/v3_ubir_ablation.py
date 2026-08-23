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


def _s(b: bytes) -> bytes:
    return _u(len(b)) + b


def json_tokens(data: bytes):
    return ubir._json_tokens(data)


def json_ablation(data: bytes, mode: str) -> bytes:
    tokens = json_tokens(data)
    strings = Counter(t for t in tokens if t[:1] == b'"')
    use_dict = mode in {"dict", "both"}
    use_delta = mode in {"delta", "both"}
    dictionary = []
    if use_dict:
        dictionary = sorted(
            (x for x, n in strings.items() if n >= 2),
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
            prev_int = value if use_delta else 0
        else:
            out.append(ubir.J_RAW)
            out += _s(t)
    return bytes(ubir.MAGIC + bytes([ubir.VERSION, ubir.K_JSON]) + _u(len(data)) + out)


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
        # The existing decoder understands the common wire format, so each
        # variant is independently checked for byte-exact reconstruction.
        assert ubir.decode(ir) == data
        size, et = packed(ir)
        print(f"{mode:>5s}: ir={len(ir):,} B packed={size:,} B delta={size-direct:+,} B ({(size/direct-1)*100:+.2f}%) enc={et:.2f}s")


if __name__ == "__main__":
    run()
