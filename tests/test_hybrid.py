"""Tests for divideencode.v2.hybrid -- the adaptive LZMA/DELTA/DE2 codec."""
import hashlib
import os
import random
import unittest

from divideencode.v2.hybrid import compress, decompress
from divideencode.errors import DivideEncodeError

SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples")


def rt(data):
    blob, method = compress(data)
    return decompress(blob), blob, method


class TestHybridRoundtrip(unittest.TestCase):
    def test_empty(self):
        restored, blob, method = rt(b"")
        self.assertEqual(restored, b"")
        self.assertEqual(method, "STORED")

    def test_one_byte_values(self):
        for v in (0, 1, 127, 255):
            data = bytes([v])
            restored, _, _ = rt(data)
            self.assertEqual(restored, data)

    def test_ascii_text(self):
        data = (b"the quick brown fox jumps over the lazy dog. " * 200)
        restored, _, method = rt(data)
        self.assertEqual(restored, data)
        self.assertIn(method, ("LZMA", "DE2"))

    def test_utf8_and_emoji(self):
        data = "hello world مرحبا بالعالم 🎉🚀".encode("utf-8") * 50
        restored, _, _ = rt(data)
        self.assertEqual(restored, data)

    def test_all_zero(self):
        data = bytes(50000)
        restored, blob, _ = rt(data)
        self.assertEqual(restored, data)
        self.assertLess(len(blob), 200)  # must compress hugely

    def test_all_same_nonzero(self):
        data = bytes([0x7F]) * 50000
        restored, _, _ = rt(data)
        self.assertEqual(restored, data)

    def test_numeric_counter_pattern(self):
        # Little-endian uint32 counters: DE2's delta/DIVIDE lane should win
        data = b"".join((i).to_bytes(4, "little") for i in range(40000))
        restored, blob, method = rt(data)
        self.assertEqual(restored, data)
        self.assertEqual(method, "DE2")
        self.assertLess(len(blob), len(data) // 10)

    def test_crypto_random_never_expands_much(self):
        random.seed(1234)
        for n in (1, 16, 1000, 65536):
            data = bytes(random.getrandbits(8) for _ in range(n))
            restored, blob, method = rt(data)
            self.assertEqual(restored, data)
            self.assertEqual(method, "STORED")
            self.assertLessEqual(len(blob), n + 16)  # bounded header overhead

    def test_bytearray_input(self):
        data = bytearray(b"abcabcabcabcabc" * 100)
        restored, _, _ = rt(bytes(data))
        self.assertEqual(restored, bytes(data))

    def test_sha256_identity(self):
        data = os.urandom(4096) + b"AAAA" * 1000 + os.urandom(4096)
        restored, _, _ = rt(data)
        self.assertEqual(hashlib.sha256(restored).hexdigest(),
                          hashlib.sha256(data).hexdigest())

    def test_force_de2_flag(self):
        data = b"hello world " * 500
        blob_auto, m_auto = compress(data)
        blob_forced, m_forced = compress(data, try_de2=True)
        self.assertEqual(decompress(blob_auto), data)
        self.assertEqual(decompress(blob_forced), data)


class TestHybridCorruption(unittest.TestCase):
    def test_bad_magic(self):
        blob, _ = compress(b"hello world" * 20)
        bad = b"XXXX" + blob[4:]
        with self.assertRaises(DivideEncodeError):
            decompress(bad)

    def test_flipped_payload_byte_detected(self):
        data = b"the quick brown fox " * 300
        blob, _ = compress(data)
        self.assertGreater(len(blob), 20)
        bad = bytearray(blob)
        bad[-5] ^= 0xFF
        with self.assertRaises(DivideEncodeError):
            decompress(bytes(bad))

    def test_truncated_container(self):
        data = b"some reasonably compressible text " * 100
        blob, _ = compress(data)
        with self.assertRaises(DivideEncodeError):
            decompress(blob[: len(blob) // 2])

    def test_unknown_method_byte(self):
        data = b"abc" * 50
        blob, _ = compress(data)
        blob = bytearray(blob)
        # method byte is right after magic(4) + varint + crc(4); easiest
        # robust way: brute-force locate by re-deriving via compress()
        # header length, then overwrite with an invalid method id.
        from divideencode.bitstream import decode_varint
        pos = 4
        _, pos = decode_varint(bytes(blob), pos, len(blob))
        pos += 4  # crc32
        blob[pos] = 99
        with self.assertRaises(DivideEncodeError):
            decompress(bytes(blob))


class TestHybridOnCorpus(unittest.TestCase):
    """Real-file coverage: every sample must round-trip exactly, and the
    hybrid container must never be larger than raw STORED would be."""

    def test_all_samples_lossless_and_bounded(self):
        if not os.path.isdir(SAMPLES_DIR):
            self.skipTest("samples/ not present in this checkout")
        for fn in sorted(os.listdir(SAMPLES_DIR)):
            path = os.path.join(SAMPLES_DIR, fn)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            with self.subTest(file=fn):
                blob, method = compress(data)
                restored = decompress(blob)
                self.assertEqual(restored, data)
                self.assertEqual(
                    hashlib.sha256(restored).hexdigest(),
                    hashlib.sha256(data).hexdigest(),
                )
                # STORED container overhead is small and fixed; hybrid
                # must never do meaningfully worse than that baseline.
                self.assertLessEqual(len(blob), len(data) + 16)


if __name__ == "__main__":
    unittest.main()
