import sys, time
sys.path.insert(0, ".")
from divideencode.de2 import lz

FILES = ("natural.txt", "data.csv", "app.log", "src_medium.c")

def run(cfg_overrides, tag):
    lz.LEVELS["BALANCED"].update(cfg_overrides)
    tot_t = 0.0
    tot_n = 0
    sizes = {}
    for f in FILES:
        data = open("benchmarks/corpus/" + f, "rb").read()
        t0 = time.perf_counter()
        blob = lz.encode(data)
        dt = time.perf_counter() - t0
        out, _ = lz.decode(blob, 0, len(blob), len(data),
                           __import__("divideencode.de2.entropy",
                                      fromlist=["x"]).DecodeTables())
        assert out == data, f
        tot_t += dt
        tot_n += len(data)
        sizes[f] = len(blob)
    print("%-28s %7.2fs %6.2f MB/s | %s" %
          (tag, tot_t, tot_n / 1048576 / tot_t,
           " ".join("%s=%d" % (f[:6], s) for f, s in sizes.items())))

BASE = dict(max_chain=32, lazy=True, nice_len=96, good_len=24,
            insert_step=0, budget_floor=6)

run(dict(BASE), "floor=6")
run(dict(BASE, budget_floor=2), "floor=2")
run(dict(BASE, budget_floor=4), "floor=4")
run(dict(BASE, budget_floor=8), "floor=8")
run(dict(BASE, budget_floor=32), "floor=32 (no adapt)")
run(dict(BASE, max_chain=16), "chain16 floor=6")
run(dict(BASE, max_chain=64, budget_floor=8), "chain64 floor=8")
