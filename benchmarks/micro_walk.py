import sys, time
sys.path.insert(0, ".")
from divideencode.de2 import lz
from array import array

data = open("benchmarks/corpus/natural.txt", "rb").read()[:262144]
n = len(data)

# instrument by wrapping _match_length and counting probes externally:
# replicate the search loop exactly with counters
M32 = lz.M32
KNUTH = lz._KNUTH
nm = lz.MIN_MATCH
window = lz.DEFAULT_WINDOW

def run(max_chain, good_len, nice_len):
    hb = 18
    hshift = 32 - hb
    head = [-1] * (1 << hb)
    prev = array("i", b"\xff\xff\xff\xff") * n
    fb4 = int.from_bytes
    stats = dict(walks=0, probes=0, ml_calls=0, positions=0, matches=0,
                 lit_positions=0)
    r0, r1, r2, r3 = 1, 2, 4, 8
    i = 0
    ins_upto = 0
    mlen = lz._match_length
    while i < n - nm + 1:
        stats["positions"] += 1
        best_len = 0
        di = data[i]
        # rep checks counted as probes too
        for d in (r0, r1, r2, r3):
            if d <= i and data[i - d] == di:
                stats["probes"] += 1
                l = mlen(data, i - d, i, n - i)
                stats["ml_calls"] += 1
                if l > best_len:
                    best_len = l
        h = (fb4(data[i:i + 4], "little") * KNUTH & M32) >> hshift
        pos = head[h]
        depth = max_chain >> 2 if best_len >= good_len else max_chain
        low_i = i - window
        bl = best_len
        walked_any = pos >= 0
        while pos >= 0 and depth > 0:
            if pos < low_i:
                break
            depth -= 1
            stats["probes"] += 1
            if bl < n - i and data[pos + bl] == data[i + bl]:
                l = mlen(data, pos, i, n - i)
                stats["ml_calls"] += 1
                if l > bl:
                    bl = l
                    if l >= nice_len or l >= n - i:
                        break
                    if bl >= good_len and depth > 8:
                        depth = 8
            pos = prev[pos]
        if walked_any:
            stats["walks"] += 1
        if bl >= 4:
            stats["matches"] += 1
        prev[i] = head[h]
        head[h] = i
        i += 1
    return stats

for mc, gl, nl in ((32, 24, 96), (16, 24, 96), (8, 16, 48), (4, 12, 32)):
    t0 = time.perf_counter()
    s = run(mc, gl, nl)
    dt = time.perf_counter() - t0
    print("chain=%-3d good=%-3d nice=%-3d | %.0fms pos=%d walks=%.2f/pos "
          "probes=%.2f/pos ml=%.2f/pos matches=%.2f/pos" % (
              mc, gl, nl, dt * 1000, s["positions"],
              s["walks"] / s["positions"], s["probes"] / s["positions"],
              s["ml_calls"] / s["positions"], s["matches"] / s["positions"]))
