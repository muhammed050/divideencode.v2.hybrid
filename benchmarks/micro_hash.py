import sys, time
sys.path.insert(0, ".")
sys.path.insert(0, os_dir := ".")

data = open("benchmarks/corpus/natural.txt", "rb").read()[:262144]
n = len(data)
KNUTH = 0x9E3779B1
M32 = 0xFFFFFFFF

def t(f, reps=5):
    best = 9e9
    for _ in range(reps):
        t0 = time.perf_counter()
        r = f()
        dt = time.perf_counter() - t0
        best = min(best, dt)
    return best, r

# variant A: current inline expression
def va():
    hs = []
    h = 0
    for i in range(n - 4):
        h = ((((data[i] << 24) | (data[i+1] << 16) | (data[i+2] << 8) |
               data[i+3]) * KNUTH) & M32) >> 12
        hs.append(h)
    return hs

# variant B: int.from_bytes + mult
def vb():
    hs = []
    fb = int.from_bytes
    for i in range(n - 4):
        h = (fb(data[i:i+4], "little") * KNUTH & M32) >> 12
        hs.append(h)
    return hs

# variant C: raw int key into dict (no hash math)
def vc():
    d = {}
    dg = d.get
    out = []
    for i in range(n - 4):
        out.append(dg((data[i] << 24 | data[i+1] << 16 | data[i+2] << 8 |
                       data[i+3]), -1))
    return out

# variant D: int.from_bytes key -> dict get/set
def vd():
    d = {}
    dg = d.get
    out = []
    fb = int.from_bytes
    for i in range(n - 4):
        k = fb(data[i:i+4], "little")
        out.append(dg(k, -1))
        d[k] = i
    return out

# variant E: expression key -> dict get/set
def ve():
    d = {}
    dg = d.get
    out = []
    for i in range(n - 4):
        k = (data[i] << 24 | data[i+1] << 16 | data[i+2] << 8 | data[i+3])
        out.append(dg(k, -1))
        d[k] = i
    return out

for name, f in (("A expr->list", va), ("B frombytes*mult", vb),
                ("C expr->dict.get", vc), ("D fb->dict g+s", vd),
                ("E expr->dict g+s", ve)):
    dt, _ = t(f)
    print("%-20s %7.1f ms" % (name, dt * 1000))

# match-length variants on realistic candidate mix
import random
rng = random.Random(3)
cands = []
for _ in range(20000):
    a = rng.randrange(0, n - 64)
    b = rng.randrange(0, n - 64)
    cands.append((a, b, min(n - b, 60)))

def ml_old(a, b, limit):
    l = 0
    while l + 8 <= limit and data[a+l:a+l+8] == data[b+l:b+l+8]:
        l += 8
    while l < limit and data[a+l] == data[b+l]:
        l += 1
    return l

def ml_chunk32(a, b, limit):
    l = 0
    while l < limit:
        step = limit - l
        if step > 32:
            step = 32
        if data[a+l:a+l+step] == data[b+l:b+l+step]:
            l += step
            continue
        while l < limit and data[a+l] == data[b+l]:
            l += 1
        return l
    return l

def bench_ml(fn):
    s = 0
    for a, b, lim in cands:
        s += fn(a, b, lim)
    return s

dt, s = t(lambda: bench_ml(ml_old), 9)
print("ml_old      %7.2f ms (sum %d)" % (dt * 1000, s))
dt, s = t(lambda: bench_ml(ml_chunk32), 9)
print("ml_chunk32  %7.2f ms (sum %d)" % (dt * 1000, s))

# combined: full scan with variant E style + insertion into prev-array
from array import array
def full_e():
    head = {}
    prev = array("i", b"\xff\xff\xff\xff") * n
    dg = head.get
    for i in range(n - 4):
        k = (data[i] << 24 | data[i+1] << 16 | data[i+2] << 8 | data[i+3])
        p = dg(k, -1)
        prev[i] = p
        head[k] = i
    return head

dt, _ = t(full_e, 5)
print("full scan E (get+set+prev) %7.1f ms" % (dt * 1000))
