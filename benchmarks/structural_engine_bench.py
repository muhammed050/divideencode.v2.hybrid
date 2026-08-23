from __future__ import annotations

import argparse
import os
import time

from divideencode.v2.structural import analyze, transform, inverse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', nargs='?')
    args = ap.parse_args()
    if args.path:
        data = open(args.path, 'rb').read()
        name = args.path
    else:
        data = (b'row|Istanbul|1000|OK\n' * 20000)
        name = 'synthetic-structured'
    t = time.perf_counter()
    candidates = analyze(data)
    blob = transform(data)
    elapsed = time.perf_counter() - t
    assert inverse(blob) == data
    print('=' * 72)
    print('STRUCTURAL ENGINE — FIRST TEST')
    print(f'file       : {name}')
    print(f'input      : {len(data):,} bytes')
    print(f'output     : {len(blob):,} bytes')
    print(f'ratio      : {len(blob)/len(data):.6f}')
    print(f'saved      : {(1-len(blob)/len(data))*100:.2f}%')
    print(f'time       : {elapsed:.4f}s')
    print('roundtrip  : True')
    print('candidates :')
    for c in candidates:
        print(f'  {c.kind:8s} {c.score:,} bytes')
    print('=' * 72)


if __name__ == '__main__':
    main()
