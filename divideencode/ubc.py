"""Universal Binary Compiler (UBC) public API.

UBC is a reversible compiler front-end for the DE2 backend. It compiles
arbitrary bytes into the project's Universal Binary IR pipeline rather than
expanding every input byte into a fixed OP_BYTE instruction.
"""
from __future__ import annotations
from .universal_binary import SearchMode, Analysis, Result, analyze, compress as _compress, compress_with_stats as _compress_with_stats, decompress as _decompress, rank_candidates

class UBCError(ValueError):
    """Raised for invalid UBC input or a corrupted UBC container."""

def _mode(value):
    if isinstance(value, SearchMode): return value
    return SearchMode[str(value).upper()]

def encode(data: bytes | bytearray | memoryview, *, mode: SearchMode | str = SearchMode.BALANCED) -> bytes:
    """Compile arbitrary bytes to a serialized Universal Binary IR program.

    Candidate verification is deferred until the single winning pipeline;
    rejected candidates are only transformed once during the search.
    """
    from .universal_compiler import compile_ir, serialize, plan, verify_pipeline
    src = bytes(data); m = _mode(mode)
    limit = {SearchMode.FAST: 8, SearchMode.BALANCED: 24, SearchMode.MAX: 64}[m]
    pipelines = plan(src, max_candidates=limit)
    best = min((compile_ir(src, p, verify=False) for p in pipelines), key=lambda ir: len(ir.payload))
    verify_pipeline(src, best.pipeline)
    return serialize(best)

def decode(program: bytes | bytearray | memoryview) -> bytes:
    from .universal_compiler import deserialize, decode_pipeline
    compiled = deserialize(bytes(program))
    return decode_pipeline(compiled.payload, compiled.pipeline, compiled.original_size)

def compile(data: bytes | bytearray | memoryview, **kwargs) -> bytes:
    return encode(data, **kwargs)

def decompile(program: bytes | bytearray | memoryview) -> bytes:
    return decode(program)

def compress(data: bytes | bytearray | memoryview, *, mode: SearchMode | str = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> bytes:
    return _compress(bytes(data), mode=mode, level=level, block_size=block_size)

def compress_with_stats(data: bytes | bytearray | memoryview, *, mode: SearchMode | str = SearchMode.BALANCED, level: str = "BALANCED", block_size: int = 1 << 20) -> Result:
    return _compress_with_stats(bytes(data), mode=mode, level=level, block_size=block_size)

def decompress(blob: bytes | bytearray | memoryview, *, verify: bool = True) -> bytes:
    return _decompress(bytes(blob), verify=verify)

def compile_to_de2(data: bytes | bytearray | memoryview, **kwargs) -> bytes:
    return compress(data, **kwargs)

def decompile_from_de2(blob: bytes | bytearray | memoryview, *, verify: bool = True) -> bytes:
    return decompress(blob, verify=verify)

__all__ = ["UBCError","SearchMode","Analysis","Result","analyze","rank_candidates","encode","decode","compile","decompile","compress","compress_with_stats","decompress","compile_to_de2","decompile_from_de2"]
