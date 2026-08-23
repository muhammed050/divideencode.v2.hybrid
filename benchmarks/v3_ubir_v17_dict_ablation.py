"""UBIR V1.7 dictionary-lane ablation.

Research only: does a different representation of dictionary references make
DE2's job easier? V1.6 is not modified here. We measure current varint IDs,
ID deltas, and move-to-front ranks on the exact V1.6 dictionary/reference
stream. We also run a generic repetition diagnostic across the whole corpus
so a JSON win is not mistaken for a general win.
"""
from collections import Counter
from pathlib import Path
import re, sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from divideencode.de2 import compress
from divideencode.v3 import ubir_v16 as v16

CORPUS = Path(__file__).resolve().parent / "corpus"
TOKEN_RE = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")


def packed(b: bytes) -> int:
    return len(compress(b, block_size=1 << 20, level="BALANCED"))


def parse_lanes(data: bytes):
    ir = v16.encode(data, "json")
    p = 6 + len(v16.v1._u(len(data)))
    b = ir[p:]
    q = 0
    nd, q = v16.v1._r(b, q)
    dictionary = []
    for _ in range(nd):
        x, q = v16.v1._g(b, q)
        dictionary.append(x)
    count, q = v16.v1._r(b, q)
    class_len, q = v16.v1._r(b, q)
    classes = v16._unpack3(b[q:q + class_len], count)
    q += class_len
    const_count, q = v16.v1._r(b, q)
    lengths = []
    for _ in range(6):
        x, q = v16.v1._r(b, q)
        lengths.append(x)
    lanes = []
    for n in lengths:
        lanes.append(b[q:q + n])
        q += n
    ids = []
    p = 0
    for tag in classes:
        if tag == v16.DICT:
            x, p = v16.v1._r(lanes[v16.DICT], p)
            ids.append(x)
    return ir, dictionary, lanes[v16.DICT], ids


def enc_ids(ids):
    return b"".join(v16.v1._u(x) for x in ids)


def enc_delta(ids):
    out = bytearray(); prev = 0
    for x in ids:
        out += v16.v1._u(v16.v1._zz(x - prev))
        prev = x
    return bytes(out)


def enc_mtf(ids, n):
    order = list(range(n))
    out = bytearray()
    for x in ids:
        try:
            rank = order.index(x)
        except ValueError:
            raise ValueError("dictionary ID out of range")
        out += v16.v1._u(rank)
        if rank:
            order.pop(rank)
            order.insert(0, x)
    return bytes(out)


def generic_repetition(path: Path, data: bytes):
    if not data or data.count(b"\x00") > max(32, len(data) // 100):
        return None
    toks = TOKEN_RE.findall(data)
    if not toks:
        return (0, 0, 0, 0)
    c = Counter(toks)
    repeated = sum(n for n in c.values() if n >= 2)
    unique_repeated = sum(1 for n in c.values() if n >= 2)
    raw = sum(len(t) * n for t, n in c.items() if n >= 2)
    # A conservative dictionary-only estimate: one stored copy plus one
    # byte-sized reference per occurrence. This is diagnostic, not a codec.
    estimate = sum(len(t) + n for t, n in c.items() if n >= 2)
    return len(toks), unique_repeated, raw, estimate


for name in ("json_small.json", "json_large.json"):
    data = (CORPUS / name).read_bytes()
    ir, dictionary, current, ids = parse_lanes(data)
    cur = packed(current)
    delta = enc_delta(ids)
    mtf = enc_mtf(ids, len(dictionary))
    print("\n" + "=" * 80)
    print(name)
    print(f"V1.6 whole IR={len(ir):,} DE2={packed(ir):,} B")
    print(f"dict refs={len(ids):,} dictionary={len(dictionary):,}")
    print(f"  current varint : raw={len(current):,} DE2={cur:,}")
    print(f"  delta+zigzag   : raw={len(delta):,} DE2={packed(delta):,} delta_DE2={packed(delta)-cur:+,}")
    print(f"  move-to-front  : raw={len(mtf):,} DE2={packed(mtf):,} delta_DE2={packed(mtf)-cur:+,}")

print("\n" + "=" * 80)
print("WHOLE-CORPUS GENERIC REPETITION DIAGNOSTIC (not a codec result)")
for path in sorted(CORPUS.iterdir()):
    if not path.is_file():
        continue
    data = path.read_bytes()
    r = generic_repetition(path, data)
    if r is None:
        print(f"{path.name:28s} binary/skip")
        continue
    toks, uniq, raw, estimate = r
    print(f"{path.name:28s} tokens={toks:8,} repeated_values={uniq:7,} repeated_raw={raw:9,} dict_est={estimate:9,}")
