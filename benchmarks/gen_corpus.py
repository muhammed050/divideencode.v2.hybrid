"""Deterministic benchmark corpus generator for DivideEncode v3.

Generates a reproducible corpus under benchmarks/corpus/ covering every
class mandated by dd.txt PHASE 0:

    source code, JSON, HTML/CSS/JS, CSV, logs, repetitive text,
    natural language text, binary, already-compressed data,
    small (<16 KiB), medium (100 KiB..1 MiB), large (>2 MiB)

Everything is seeded; regenerating produces byte-identical files so
benchmark runs are comparable across commits.
"""
import os
import random
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")

WORDS = ("the quick brown fox jumps over lazy dog while public static void "
         "return value result buffer window stream packet signal network "
         "process memory system design pattern engine module service client "
         "server request response header field record table column index "
         "query update insert delete select from where group order limit").split()

JS_SNIPPETS = [
    "function handle(x) { return x * 2 + 1; }\n",
    "const cfg = {retries: 3, timeout: 2500, name: \"svc\"};\n",
    "export async function load(u) { const r = await fetch(u);"
    " return r.json(); }\n",
    "if (!ready) { console.warn('not ready'); return null; }\n",
    "for (let i = 0; i < items.length; i++) { sum += items[i].price; }\n",
]
PY_SNIPPETS = [
    "def process(rows):\n    total = 0\n    for r in rows:\n"
    "        total += r.value\n    return total\n",
    "class Engine:\n    def __init__(self, size):\n        self.size = size\n"
    "        self.cache = {}\n",
    "@dataclass\nclass Point:\n    x: float\n    y: float\n",
    "async def fetch(url, session):\n    async with session.get(url) as resp:"
    "\n        return await resp.text()\n",
    "if __name__ == '__main__':\n    main(sys.argv[1:])\n",
]


def _w(rng, k=None):
    if k is None:
        k = rng.randint(3, 12)
    return " ".join(rng.choice(WORDS) for _ in range(k))


def gen_source(rng, lines):
    parts = []
    for i in range(lines):
        r = rng.random()
        if r < 0.4:
            parts.append("    // step %d: %s" % (i, _w(rng)))
        elif r < 0.8:
            parts.append(rng.choice(JS_SNIPPETS))
        else:
            parts.append(rng.choice(PY_SNIPPETS))
    return "".join(parts).encode()


def gen_json(rng, records):
    rows = []
    for i in range(records):
        rows.append('{"id": %d, "name": "%s", "tags": ["%s", "%s"], '
                    '"score": %.3f, "active": %s}' % (
                        i, _w(rng, 2).replace(" ", "_"),
                        rng.choice(WORDS), rng.choice(WORDS),
                        rng.random() * 100,
                        "true" if rng.random() < 0.5 else "false"))
    return ("[" + ",\n".join(rows) + "]").encode()


def gen_html(rng, blocks):
    head = ("<html><head><title>%s</title>"
            "<style>body{font-family:sans-serif;margin:0 auto;color:#333}"
            ".nav{display:flex;gap:8px}.card{border:1px solid #ddd;"
            "padding:12px;border-radius:6px}</style></head><body>" % _w(rng, 3))
    body = []
    for i in range(blocks):
        body.append('<div class="card"><h2>%s</h2><p>%s.</p>'
                    '<a href="/item/%d">read more</a></div>' %
                    (_w(rng, 2), _w(rng, rng.randint(10, 25)), i))
    tail = ("<script>document.querySelectorAll('.card').forEach(c=>c.onclick="
            "()=>c.classList.toggle('open'));</script></body></html>")
    return (head + "".join(body) + tail).encode()


def gen_csv(rng, rows):
    out = ["id,timestamp,user,action,value,note"]
    for i in range(rows):
        out.append("%d,2026-%02d-%02dT%02d:%02d:%02dZ,%s,%s,%.2f,%s" % (
            i, rng.randint(1, 12), rng.randint(1, 28), rng.randint(0, 23),
            rng.randint(0, 59), rng.randint(0, 59),
            _w(rng, 2).replace(" ", "."), rng.choice(("login", "view",
             "click", "buy", "logout")),
            rng.random() * 500, _w(rng)))
    return ("\n".join(out)).encode()


def gen_log(rng, lines):
    levels = ("INFO", "WARN", "ERROR", "DEBUG")
    mods = ("auth.session", "net.tcp", "db.pool", "api.handler", "job.queue")
    msgs = ("connection established to upstream peer",
            "request completed status=%d duration=%dms",
            "cache miss key=user_%04d fetching from origin",
            "retrying operation attempt=%d backoff=%dms",
            "pool exhausted waiting for idle connection")
    out = []
    t_h = t_m = t_s = t_ms = 0
    for i in range(lines):
        m = rng.choice(msgs)
        if "%d" in m:
            m = m % tuple(rng.randint(0, 9999)
                          for _ in range(m.count("%")))
        t_ms += rng.randint(1, 40)
        while t_ms >= 1000:
            t_ms -= 1000
            t_s += 1
        while t_s >= 60:
            t_s -= 60
            t_m += 1
        while t_m >= 60:
            t_m -= 60
            t_h += 1
        out.append("2026-08-22T%02d:%02d:%02d.%03dZ %s %s : %s" % (
            t_h, t_m, t_s, t_ms, rng.choice(levels), rng.choice(mods), m))
    return ("\n".join(out)).encode()


def gen_natural(rng, sentences):
    openers = ("The system reported that", "During the test window",
               "Engineers observed how", "Records indicate that",
               "After careful analysis the team found")
    out = []
    for _ in range(sentences):
        out.append("%s %s %s." % (rng.choice(openers), _w(rng),
                                  _w(rng, rng.randint(4, 10))))
    return ("\n".join(out)).encode()


def gen_repetitive(rng, blocks):
    unit = ("%s %s\n" % (_w(rng), _w(rng))).encode()
    return (unit * (blocks * 4096 // max(1, len(unit)) + 1))


def gen_binary(rng, size):
    """Structured binary: headers + ramps + noise regions."""
    out = bytearray()
    while len(out) < size:
        r = rng.random()
        if r < 0.25:
            base = rng.randint(0, 1 << 30)
            for j in range(2048):
                out += ((base + j) & 0xFFFFFFFF).to_bytes(4, "little")
        elif r < 0.5:
            out += bytes(rng.randrange(256) for _ in range(512))
        else:
            v = rng.randint(0, 255)
            out += bytes((v,) * 1024)
    return bytes(out[:size])


def gen_compressed(rng, target):
    """Already-compressed data: compress other samples."""
    parts = [gen_source(rng, 400), gen_json(rng, 2000)]
    blob = b"".join(parts)
    chunks = []
    total = 0
    while total < target:
        c = zlib.compress(blob[:65536], 9)
        chunks.append(c)
        total += len(c)
    return b"".join(chunks)[:target]


def build():
    os.makedirs(CORPUS, exist_ok=True)

    # one master seed -> per-file derived seeds (stable across runs)
    master = random.Random(0xDE2E2)
    files = []

    def add(name, data):
        files.append((name, data))

    add("src_small.c", gen_source(random.Random(master.getrandbits(32)), 200))
    add("src_medium.c", gen_source(random.Random(master.getrandbits(32)), 3000))
    add("json_small.json", gen_json(random.Random(master.getrandbits(32)), 300))
    add("json_large.json", gen_json(random.Random(master.getrandbits(32)),
                                    12000))
    add("page.html", gen_html(random.Random(master.getrandbits(32)), 1500))
    add("styles.css", (
        "body{margin:0;font-family:sans-serif}\n"
        ".card{padding:12px;border-radius:6px;border:1px solid #ddd}\n"
        ".nav{display:flex;gap:8px;align-items:center}\n" * 900).encode())
    add("data.csv", gen_csv(random.Random(master.getrandbits(32)), 8000))
    add("app.log", gen_log(random.Random(master.getrandbits(32)), 12000))
    add("repeat.txt", gen_repetitive(random.Random(master.getrandbits(32)),
                                     700))
    add("natural.txt", gen_natural(random.Random(master.getrandbits(32)),
                                   6000))
    add("binary.bin", gen_binary(random.Random(master.getrandbits(32)),
                                 3 << 20))
    rrng = random.Random(42)
    add("random.raw", bytes(rrng.randrange(256) for _ in range(1 << 18)))
    add("compressed.zip", gen_compressed(random.Random(master.getrandbits(32)),
                                         1 << 20))

    for name, data in files:
        with open(os.path.join(CORPUS, name), "wb") as fh:
            fh.write(data)
        print("%-18s %9d bytes" % (name, len(data)))


if __name__ == "__main__":
    build()
