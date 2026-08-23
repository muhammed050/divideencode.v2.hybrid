"""Mutation fuzz: corrupted DE2 blobs must fail cleanly, never silently.

Invariants under random bit/byte/truncation mutations of valid blobs:
- decompress() returns the exact original bytes, OR
- raises DivideEncodeError (CorruptedError / NotDivideEncodedError)
Any other exception or wrong payload is a bug.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from divideencode import de2
from divideencode.de2 import container
from divideencode.errors import CorruptedError, DivideEncodeError


def _samples():
    rng = random.Random(0xF00D)
    cases = [
        b"",
        b"a" * 5000,
        bytes(rng.randrange(256) for _ in range(3000)),
        b"the cat sat on the mat. " * 400,
        b"\x00" * 70000,
    ]
    blobs = []
    for level in ("FAST", "BALANCED", "MAX"):
        for c in cases:
            blobs.append((c, de2.compress(c, level=level)))
    return blobs


class TestMutationFuzz(unittest.TestCase):
    def test_mutations_fail_clean(self):
        rng = random.Random(2026)
        blobs = _samples()
        checked = 0
        for _round in range(120):
            orig, blob = rng.choice(blobs)
            b = bytearray(blob)
            kind = rng.randrange(4)
            if kind == 0 and len(b) > 12:          # single bit flip
                i = rng.randrange(len(b))
                b[i] ^= 1 << rng.randrange(8)
            elif kind == 1 and len(b) > 12:        # random byte stomp
                i = rng.randrange(len(b))
                b[i] = rng.randrange(256)
            elif kind == 2 and len(b) > 16:        # truncate
                b = b[:rng.randrange(1, len(b))]
            else:                                  # header field stomp
                if len(b) > 8:
                    b[rng.randrange(0, 6)] = rng.randrange(256)
            mutated = bytes(b)
            try:
                out = de2.decompress(mutated)
            except DivideEncodeError:
                pass          # clean rejection: expected
            else:
                # accepted: must be byte-perfect original
                self.assertEqual(out, orig,
                                 "corrupted blob decoded to wrong data")
            checked += 1
        self.assertGreater(checked, 100)

    def test_truncation_never_wrong_data(self):
        rng = random.Random(77)
        orig = b"log line %d with some words " * 1 % (1,) * 800
        blob = de2.compress(orig)
        for cut in range(4, len(blob), max(1, len(blob) // 200)):
            try:
                out = de2.decompress(blob[:cut])
            except DivideEncodeError:
                continue
            self.assertEqual(out, orig[:len(out)] if len(out) < len(orig)
                             else orig)


if __name__ == "__main__":
    unittest.main()
