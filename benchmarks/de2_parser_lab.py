"""DE2 parser laboratory.

This benchmark is intentionally read-only with respect to production code. It
compares tokenizer configurations on the same inputs and records both parser
statistics and final DE2 payload size.

Examples:
    python benchmarks/de2_parser_lab.py
    python benchmarks/de2_parser_lab.py --samples samples --out parser_lab.json
    python benchmarks/de2_parser_lab.py --sizes 8,16,32,64 --csv parser_lab.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import struct
import sys
import time
from dataclasses import asdict, dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from divideencode.v2.lz import tokenize, token_stats
from divideencode.v2.codec import _lze_core


@dataclass(frozen=True)
class Case:
    name: str
    data: bytes


def synthetic_cases() -> list[Case]:
    rng = random.Random(0xDE2)
    cases = [
        Case("empty", b""),
        Case("text_short", b"the quick brown fox jumps over the lazy dog " * 200),
        Case("json", (b'{"id":123,"name":"user","active":true,"items":[1,2,3]}\n' * 5000)),
        Case("logs", b"2026-08-23 10:20:30 INFO api status=200 latency=42ms\n" * 5000),
        Case("zeros", bytes(200000)),
        Case("ones", b"\xff" * 200000),
        Case("periodic", (b"0123456789abcdef" * 1024) * 80),
        Case("mixed", (b"header\x00\x00\x00payload:" + bytes(range(64))) * 4000),
        Case("random", bytes(rng.getrandbits(8) for _ in range(200000))),
    ]
    vals = [i * 3 % 65536 for i in range(80000)]
    cases.append(Case("u16", struct.pack("<%dH" % len(vals), *vals)))
    return cases


def load_sample_cases(samples_dir: str) -> list[Case]:
    out = []
    if not os.path.isdir(samples_dir):
        return out
    for name in sorted(os.listdir(samples_dir)):
        path = os.path.join(samples_dir, name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                out.append(Case("sample:" + name, fh.read()))
    return out


def run_case(case: Case, max_chain: int, lazy: bool) -> dict:
    data = case.data
    t0 = time.perf_counter()
    tokens = tokenize(data, max_chain=max_chain, lazy=lazy)
    tokenize_ms = (time.perf_counter() - t0) * 1000.0
    stats = token_stats(tokens)

    t1 = time.perf_counter()
    lze = _lze_core(data)
    lze_ms = (time.perf_counter() - t1) * 1000.0
    lze_size = None if lze is None else len(lze)

    return {
        "case": case.name,
        "input_bytes": len(data),
        "max_chain": max_chain,
        "lazy": lazy,
        "tokenize_ms": round(tokenize_ms, 3),
        "lze_ms": round(lze_ms, 3),
        "lze_bytes": lze_size,
        "lze_ratio": None if lze_size is None or not data else round(lze_size / len(data), 6),
        **stats,
    }


def write_json(rows, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, sort_keys=True)


def write_csv(rows, path):
    if not rows:
        return
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", default=os.path.join(ROOT, "samples"))
    ap.add_argument("--out", default="parser_lab.json")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--chains", default="8,16,32,64")
    args = ap.parse_args()

    chains = [int(x) for x in args.chains.split(",") if x.strip()]
    cases = synthetic_cases() + load_sample_cases(args.samples)
    rows = []
    for case in cases:
        for chain in chains:
            for lazy in (False, True):
                rows.append(run_case(case, chain, lazy))

    write_json(rows, args.out)
    if args.csv:
        write_csv(rows, args.csv)

    print("DE2 parser lab")
    print("cases=%d configurations=%d rows=%d" %
          (len(cases), len(chains) * 2, len(rows)))
    print("output=%s" % args.out)
    print()
    print("case                         chain lazy  tokens   match%%  LZE bytes   tokenize ms")
    print("---------------------------  ----- ----  -------  -------  ---------  -----------")
    for row in rows:
        if row["case"].startswith("sample:") or row["case"] in {"json", "u16", "random"}:
            covered = row["match_covered"]
            match_pct = 0.0 if not row["input_bytes"] else 100.0 * covered / row["input_bytes"]
            print("%-27s  %5d %4s  %7d  %6.1f  %9s  %11.3f" % (
                row["case"][:27], row["max_chain"], str(row["lazy"]),
                row["tokens"], match_pct,
                str(row["lze_bytes"]), row["tokenize_ms"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
