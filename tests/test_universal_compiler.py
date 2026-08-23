from __future__ import annotations

import os

from divideencode.universal_compiler import (
    Instruction,
    Op,
    Pipeline,
    compile_ir,
    decode_pipeline,
    encode_pipeline,
    plan,
    verify_pipeline,
)
from divideencode.universal_binary import compress, decompress


def _samples() -> list[bytes]:
    return [
        b"",
        b"hello world " * 257,
        bytes(range(256)) * 97,
        bytes((i * 37 + (i >> 3)) & 0xFF for i in range(8193)),
        os.urandom(8192),
    ]


def test_every_ir_opcode_roundtrips():
    data = bytes((i * 73 + i // 11) & 0xFF for i in range(4097))
    for op in Op:
        pipeline = Pipeline((Instruction(op),))
        verify_pipeline(data, pipeline)


def test_composed_pipelines_roundtrip():
    data = (b"ABCD" * 1000) + bytes(range(64)) * 20
    pipelines = [
        Pipeline((Instruction(Op.DELTA8), Instruction(Op.BYTE_LANES4))),
        Pipeline((Instruction(Op.XOR32), Instruction(Op.BYTE_LANES4))),
        Pipeline((Instruction(Op.NIBBLE), Instruction(Op.DELTA8))),
        Pipeline((Instruction(Op.DELTA8), Instruction(Op.NIBBLE))),
        Pipeline((Instruction(Op.RLE), Instruction(Op.BYTE_LANES4))),
        Pipeline((Instruction(Op.BITPLANE), Instruction(Op.BYTE_LANES4))),
        Pipeline((Instruction(Op.BYTE_LANES4), Instruction(Op.BITPLANE))),
        Pipeline((Instruction(Op.BITPLANE), Instruction(Op.RLE))),
        Pipeline((Instruction(Op.RLE), Instruction(Op.BITPLANE))),
    ]
    for pipeline in pipelines:
        encoded = encode_pipeline(data, pipeline)
        assert decode_pipeline(encoded, pipeline, len(data)) == data


def test_compiled_ir_roundtrip():
    data = b"0123456789" * 500
    pipeline = Pipeline((Instruction(Op.DELTA32), Instruction(Op.BYTE_LANES4)))
    compiled = compile_ir(data, pipeline)
    assert compiled.original_size == len(data)
    assert compiled.payload
    assert decode_pipeline(compiled.payload, compiled.pipeline, compiled.original_size) == data


def test_ubir2_container_roundtrip_for_arbitrary_bytes():
    for data in _samples():
        blob = compress(data, mode="FAST")
        assert decompress(blob) == data


def test_corruption_is_detected():
    data = b"corruption test " * 1000
    blob = bytearray(compress(data, mode="BALANCED"))
    blob[-1] ^= 1
    try:
        decompress(bytes(blob))
    except Exception:
        pass
    else:
        raise AssertionError("corruption was not detected")
