"""Canonical external byte-symbol dictionary for DE2.

The dictionary is intentionally fixed: every possible byte value (0..255)
has exactly one stable symbol ID. This avoids storing a per-file dictionary.
"""

MAGIC = b"DE2SYM1"
VERSION = 1
SYMBOL_COUNT = 256

# Canonical mapping: byte -> compact symbol ID.
BYTE_TO_ID = bytes(range(256))
ID_TO_BYTE = bytes(range(256))


def symbol_id(byte_value: int) -> int:
    if not 0 <= byte_value <= 255:
        raise ValueError("byte value must be in range 0..255")
    return BYTE_TO_ID[byte_value]


def byte_value(symbol: int) -> int:
    if not 0 <= symbol <= 255:
        raise ValueError("symbol ID must be in range 0..255")
    return ID_TO_BYTE[symbol]


def encode(data: bytes) -> bytes:
    """Convert raw bytes to canonical symbol IDs."""
    return bytes(BYTE_TO_ID[b] for b in data)


def decode(symbols: bytes) -> bytes:
    """Convert canonical symbol IDs back to raw bytes."""
    return bytes(ID_TO_BYTE[s] for s in symbols)


def dictionary_bytes() -> bytes:
    """Return the complete fixed dictionary as 256 byte values."""
    return ID_TO_BYTE


__all__ = [
    "MAGIC", "VERSION", "SYMBOL_COUNT", "BYTE_TO_ID", "ID_TO_BYTE",
    "symbol_id", "byte_value", "encode", "decode", "dictionary_bytes",
]
