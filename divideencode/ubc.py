"""Universal Binary Compiler (UBC) public API.

UBC is a reversible compiler front-end for the DE2 backend.  It compiles
arbitrary bytes into the project's Universal Binary IR pipeline rather than
expanding every input byte into a fixed ``OP_BYTE`` instruction.

The compiler lives in :mod:`divideencode.universal_compiler`; the container
and DE2 backend live in :mod:`divideencode.universal_binary`.  Keeping this
module as the UBC facade gives callers one stable API while making UBC a real
IR compiler instead of a byte-for-byte instruction wrapper.
"""
from __future__ import annotations

from .universal_binary import (
    SearchMode,
    Analysis,
    Result,
    analyze,
    compress as _compress,
    compress_with_stats as _compress_with_stats,
    decompress as _decompress,
    rank_candidates,
)


class UBCError(ValueError):
    """Raised for invalid UBC input or a corrupted UBC container."""


def encode(
    data: bytes | bytearray | memoryview,
    *,
    mode: SearchMode | str = SearchMode.BALANCED,
) -> bytes:
    """Compile arbitrary bytes to a serialized Universal Binary IR program.

    This intentionally returns the IR program, not a DE2 container.  The
    compiler uses the same reversible pipeline planner as UBIR2.
    """
    from .universal_compiler import compile_ir, serialize, plan

    src = bytes(data)
    pipelines = plan(src, max_candidates={
        SearchMode.FAST: 8,
        SearchMode.BALANCED: 24,
        SearchMode.MAX: 64,
    }[SearchMode[mode.upper()] if isinstance(mode, str) else mode])

    # ``encode`` is the language/compiler API: select the best IR by the
    # transformed representation itself, not by adding a DE2 container here.
    # DE2-aware selection remains in ``compress`` below.
    best = min(
        (compile_ir(src, p, verify=True) for p in pipelines),
        key=lambda ir: len(ir.payload),
    )
    return serialize(best)


def decode(program: bytes | bytearray | memoryview) -> bytes:
    """Decode a serialized Universal Binary IR program exactly."""
    from .universal_compiler import deserialize, decode_pipeline

    compiled = deserialize(bytes(program))
    return decode_pipeline(compiled.payload, compiled.pipeline, compiled.original_size)


def compile(data: bytes | bytearray | memoryview, **kwargs) -> bytes:
    return encode(data, **kwargs)


def decompile(program: bytes | bytearray | memoryview) -> bytes:
    return decode(program)


def compress(
    data: bytes | bytearray | memoryview,
    *,
    mode: SearchMode | str = SearchMode.BALANCED,
    level: str = "BALANCED",
    block_size: int = 1 << 20,
) -> bytes:
    """Compile arbitrary bytes to UBC IR and encode the IR with DE2."""
    return _compress(
        bytes(data), mode=mode, level=level, block_size=block_size
    )


def compress_with_stats(
    data: bytes | bytearray | memoryview,
    *,
    mode: SearchMode | str = SearchMode.BALANCED,
    level: str = "BALANCED",
    block_size: int = 1 << 20,
) -> Result:
    """Return the UBC+DE2 result and compiler statistics."""
    return _compress_with_stats(
        bytes(data), mode=mode, level=level, block_size=block_size
    )


def decompress(
    blob: bytes | bytearray | memoryview,
    *,
    verify: bool = True,
) -> bytes:
    """Decode a DE2-backed UBC container back to the original bytes."""
    return _decompress(bytes(blob), verify=verify)


def compile_to_de2(data: bytes | bytearray | memoryview, **kwargs) -> bytes:
    return compress(data, **kwargs)


def decompile_from_de2(
    blob: bytes | bytearray | memoryview,
    *,
    verify: bool = True,
) -> bytes:
    return decompress(blob, verify=verify)


__all__ = [
    "UBCError",
    "SearchMode",
    "Analysis",
    "Result",
    "analyze",
    "rank_candidates",
    "encode",
    "decode",
    "compile",
    "decompile",
    "compress",
    "compress_with_stats",
    "decompress",
    "compile_to_de2",
    "decompile_from_de2",
]
