import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from divideencode.v2.lz import apply_tokens
from divideencode.v2.lz_opt import tokenize_bounded


class TestBoundedParser(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(tokenize_bounded(b""), [])

    def test_roundtrip(self):
        cases = [
            b"abcabcabcabc" * 500,
            b"0123456789abcdef" * 1000,
            bytes(range(256)) * 300,
            (b"The quick brown fox jumps over the lazy dog. " * 1000),
        ]
        for data in cases:
            for lookahead in (8, 16, 32):
                with self.subTest(size=len(data), lookahead=lookahead):
                    self.assertEqual(apply_tokens(tokenize_bounded(
                        data, lookahead=lookahead)), data)

    def test_deterministic(self):
        data = b"header:payload:" + bytes(range(64))
        a = tokenize_bounded(data, lookahead=16)
        b = tokenize_bounded(data, lookahead=16)
        self.assertEqual(a, b)

    def test_random_roundtrip(self):
        import random
        rng = random.Random(0xB0UND)
        data = bytes(rng.getrandbits(8) for _ in range(4096))
        self.assertEqual(apply_tokens(tokenize_bounded(data, lookahead=16)), data)


if __name__ == "__main__":
    unittest.main()
