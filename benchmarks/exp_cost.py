"""Experiments: explicit min-match length and lazy take-margin."""
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
        assert old in src, old[:50]
        src = src.replace(old, new)
    src = src.replace("from ..bitstream import",
                      "from divideencode.bitstream import")
    src = src.replace("from ..errors import",
                      "from divideencode.errors import")
    src = src.replace("from . import entropy",
                      "from divideencode.de2 import entropy")
    ns = {"__name__": "lzvar"}
    exec(compile(src, "lzvar", "exec"), ns)
    return ns["encode"], ns["decode"]


def measure(tag, enc, dec):
    tot_t = tot_n = tot_c = 0.0
    per = []
    for f, data in zip(FILES, DATA):
        t0 = time.perf_counter()
        blob = enc(data)
        dt = time.perf_counter() - t0
        out, _ = dec(blob, 0, len(blob), len(data), entropy.DecodeTables())
        assert out == data, (tag, f)
        tot_t += dt
        tot_n += len(data)
        tot_c += len(blob)
        per.append("%s=%d" % (f[:5], len(blob)))
    print("%-30s %6.2fs total=%8d | %s" %
          (tag, tot_t, tot_c, " ".join(per)))


base_enc, base_dec = load_variant([])
measure("base", base_enc, base_dec)

# A: chain candidates must reach 5 bytes to beat literals/reps
mm5 = [("if bl > best_len:\n                    best_len = bl\n"
        "                    best_dist = bd\n                    best_rep = -1",
        "if bl > best_len and bl >= 5:\n                    best_len = bl\n"
        "                    best_dist = bd\n"
        "                    best_rep = -1")]
enc5, dec5 = load_variant(mm5)
measure("min_explicit=5", enc5, dec5)

# B: lazy margin — new candidate must beat held by 2
marg = [("take_new = best_len > pend_len",
         "take_new = best_len > pend_len + 1")]
encm, decm = load_variant(marg)
measure("lazy_margin+1", encm, decm)

# C: combined
comb = mm5 + [("take_new = best_len > pend_len",
               "take_new = best_len > pend_len + 1")]
encc, decc = load_variant(comb)
measure("mm5+margin", encc, decc)

# D: nice_len/good_len tuning on BALANCED
nice = [("_LEVEL_BALANCED = dict(max_chain=32, lazy=True, nice_len=96,"
         " good_len=24,",
         "_LEVEL_BALANCED = dict(max_chain=32, lazy=True, nice_len=160,"
         " good_len=36,")]
encn, decn = load_variant(nice)
measure("nice160/good36", encn, decn)
