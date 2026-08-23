import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from benchmarks.de2_parser_lab import run_case, Case


class TestParserLab(unittest.TestCase):
    def test_configurations_roundtrip_and_metrics(self):
        data = (b"header:" + b"0123456789abcdef" * 32 + b"\n") * 200
        for chain in (8, 16, 32, 64):
            for lazy in (False, True):
                row = run_case(Case("fixture", data), chain, lazy)
                self.assertEqual(row["input_bytes"], len(data))
                self.assertEqual(row["max_chain"], chain)
                self.assertEqual(row["lazy"], lazy)
                self.assertGreaterEqual(row["match_covered_pct"], 0.0)
                self.assertLessEqual(row["match_covered_pct"], 100.0)
                self.assertGreater(row["tokens"], 0)
                self.assertGreaterEqual(row["tokenize_ms"], 0.0)

    def test_random_data_does_not_claim_match_coverage(self):
        data = bytes(range(256)) * 64
        row = run_case(Case("fixture", data), 32, True)
        self.assertEqual(row["input_bytes"], len(data))
        self.assertLess(row["match_covered_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
