"""Retest budget floors + insertion strides under v2 pricing."""
import sys
import time

sys.path.insert(0, ".")
from divideencode.de2 import entropy, lz

FILES = ("natural.txt", "app.log", "data.csv", "src_medium.c",
         "page.html", "json_large.json")
DATA = [open("benchmarks/corpus/" + f, "rb").read() for f in FILES]


def load_variant(patches):
    src = open("divideencode/de2/lz.py").read()
    for old, new in patches:
        assert old in src, old[:60]
        src = src.replace(old, new)
    src = src.replace("from ..bitstream import",
                      "from divideencode.bitstream import")
    src = src.replace("from ..errors import",
                      "from divideencode.errors import")
    src = src.replace("from . import entropy",
                      "from divideencode.de2 import entropy")
    ns = {"__name__": "lzvar"}
    exec(compile(src, "lzvar", "exec"), ns)
    return ns


def run(ns, tag):
    tot_t = tot_c = 0.0
    per = []
    for f, data in zip(FILES, DATA):
        t0 = time.perf_counter()
        blob = ns["encode_v2"](data)
        dt = time.perf_counter() - t0
        out, _ = ns["decode_v2"](blob, 0, len(blob), len(data),
                                 entropy.DecodeTables())
        assert out == data, f
        tot_t += dt
        tot_c += len(blob)
        per.append("%s=%d" % (f[:5], len(blob)))
    print("%-26s %6.2fs %5.2f MB/s total=%8d | %s" %
          (tag, tot_t, tot_n_mb() / tot_t, tot_c, " ".join(per)))


def tot_n_mb():
    return sum(len(d) for d in DATA) / 1048576.0


base = load_variant([])
run(base, "current (floor32,step L<=16)")

# floor variants
for fl in (8, 6, 4):
    ns = load_variant([("insert_step=0, budget_floor=32)",
                        "insert_step=0, budget_floor=%d)" % fl)])
    run(ns, "floor=%d" % fl)

# insertion stride variants
ns = load_variant([("step = 1 if L <= 16 else (2 if L <= 64 else 4)",
                    "step = 2 if L <= 16 else (4 if L <= 64 else 8)")])
run(ns, "stride x2")

# combined floor6 + stride x2
ns = load_variant([("insert_step=0, budget_floor=32)",
                    "insert_step=0, budget_floor=6)"),
                   ("step = 1 if L <= 16 else (2 if L <= 64 else 4)",
                    "step = 2 if L <= 16 else (4 if L <= 64 else 8)")])
run(ns, "floor6 + stride x2")
