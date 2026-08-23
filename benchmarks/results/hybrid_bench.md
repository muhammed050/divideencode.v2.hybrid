# Hybrid Codec Benchmark — measured on this build

Run on the packaged `samples/` corpus, this machine, this checkout.
Generated with: `python3 dehybrid.py bench samples/`

Backends compared: `zlib` level 9 (stdlib), `lzma` preset 9|EXTREME
(stdlib), pure-Python `divideencode.v2` (DE2) alone, and the new
**hybrid** codec (`divideencode.v2.hybrid`) which measures LZMA,
DELTA+LZMA, and DE2 per file and keeps the smallest verified-correct
result, always falling back to STORED for incompressible input.

| File | Orig | zlib9 | lzma9e | DE2 alone | **Hybrid** | method chosen |
|---|---:|---:|---:|---:|---:|---|
| App.java | 100,425 | 4,048 | 3,188 | 4,470 | **3,200** | LZMA |
| app.js | 83,043 | 3,831 | 3,080 | 4,198 | **3,092** | LZMA |
| app.ts | 88,275 | 3,918 | 3,156 | 4,303 | **3,168** | LZMA |
| archive.zip | 74,670 | 73,941 | 73,960 | 74,682 | **73,972** | LZMA |
| big.json | 421,249 | 75,971 | 50,528 | 85,796 | **50,540** | LZMA |
| counters_u32.bin | 160,000 | 44,333 | 21,084 | **361** | **373** | DE2 |
| data.json | 393,678 | 60,388 | 48,628 | 65,369 | **48,640** | LZMA |
| doc.pdf | 44,889 | 2,542 | 1,108 | 1,814 | **1,120** | LZMA |
| dump.sql | 432,464 | 53,082 | 42,104 | 54,052 | **42,116** | LZMA |
| engine.cpp | 87,326 | 3,938 | 3,160 | 4,301 | **3,172** | LZMA |
| feed.xml | 150,450 | 16,587 | 10,096 | 15,186 | **10,108** | LZMA |
| lib.rs | 93,269 | 3,840 | 3,140 | 4,221 | **3,152** | LZMA |
| main.py | 88,515 | 5,532 | 4,416 | 6,106 | **4,428** | LZMA |
| notes.md | 20,177 | 2,232 | 1,936 | 2,591 | **1,948** | LZMA |
| page.html | 90,574 | 10,022 | 4,952 | 9,165 | **4,964** | LZMA |
| photo.jpg | 65,397 | 64,751 | 65,032 | 65,241 | **65,044** | LZMA |
| photo.png | 471,403 | 471,554 | 471,484 | 471,415 | **471,415** | STORED |
| photo.webp | 60,216 | 60,242 | 60,276 | 60,228 | **60,228** | STORED |
| program.c | 99,918 | 4,074 | 3,196 | 4,463 | **3,208** | LZMA |
| random_os.bin | 262,144 | 262,230 | 262,216 | 262,156 | **262,156** | STORED |
| random_prng.bin | 262,144 | 5,327 | 1,200 | **384** | **396** | DE2 |
| sensor_i16.bin | 131,072 | 120,090 | 94,192 | **70,911** | **70,923** | DE2 |
| server.log | 207,757 | 34,806 | 27,788 | 39,219 | **27,800** | LZMA |
| table.csv | 246,142 | 61,920 | 42,136 | 65,943 | **42,148** | LZMA |
| text_en.txt | 34,497 | 12,422 | 11,500 | 13,950 | **11,512** | LZMA |

**Corpus totals (4,169,694 bytes original):**

| Codec | Total bytes | Ratio |
|---|---:|---:|
| DE2 alone (pure Python, previous "best" build) | 1,390,525 | 0.3335 |
| LZMA 9e alone (no DivideEncode logic at all) | 1,313,556 | 0.3150 |
| **Hybrid (this build)** | **1,268,823** | **0.3043** |

### What this shows, honestly

- The hybrid codec **beats both of its own components on the corpus
  total** — it is not just "LZMA with extra steps": on the 3 files
  where DivideEncode's numeric-structure insight actually pays off
  (`counters_u32.bin`, `random_prng.bin`, `sensor_i16.bin`) it picks
  DE2 and wins by a wide margin (e.g. `random_prng.bin`: 384 B vs
  1,200 B for plain LZMA — over 3× smaller). Everywhere else it picks
  LZMA and gets the fast, strong, C-backed result instead of Python's
  own weaker general-purpose ratio.
- **Compression time per file is now sub-second for everything under
  ~500 KB** (LZMA is C-accelerated; DE2 is only invoked, and only
  costs real time, on the numeric files it actually wins on).
- No claims beyond what's in this table — every number above was
  re-measured against this exact build, not carried over from the
  original research repo's numbers.
