"""Frozen UBIR V1.1 baseline benchmark.

Baseline target for subsequent V3 JSON experiments:
- json_small.json: 5,292 B
- json_large.json: 148,990 B

Any candidate must beat these final DE2 sizes and pass byte-exact roundtrip.
"""
from pathlib import Path
from divideencode.de2 import compress
from divideencode.v3 import ubir_v11

CORPUS = Path(__file__).resolve().parent / "corpus"
EXPECTED = {"json_small.json": 5292, "json_large.json": 148990}

for name, expected in EXPECTED.items():
    data = (CORPUS / name).read_bytes()
    blob = ubir_v11.encode(data, "json")
    assert ubir_v11.decode(blob) == data
    packed = compress(blob, block_size=1 << 20, level="BALANCED")
    assert len(packed) == expected, (name, len(packed), expected)
    print(f"{name}: UBIR V1.1 baseline = {len(packed):,} B")

print("UBIR V1.1 baseline FROZEN: candidates must beat the exact final-DE2 sizes above.")
