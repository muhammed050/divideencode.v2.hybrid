"""DE2 "Fast HYB" compression engine (V2/V3).

Pipeline per block:
    scan_features -> one universal representation decision ->
    LZ/TSE core -> separated token streams -> DE2 block container.

The universal front-end uses a bounded sample to choose at most one phrase
representation. It never performs full DE2 trial compression for multiple
phrase candidates. The selected representation is translated once and sent
to DE2 once; direct LZ remains the fallback.
"""
from ..errors import CorruptedError
from ..patterns import rle_encode, rle_decode

from . import container, entropy, lz, transforms, phrase
from . import universal_translator
from .classifier import (MODE_RAW, MODE_RLE, MODE_LZ, MODE_DELTA_LZ,
                         MODE_STRUCT_LZ, classify)
from .container import (MAGIC, VERSION, FLAG_LZ_V2, parse_header,
                        iter_blocks, write_header, write_block,
                        check_block_crc)
from .features import scan_features

DEFAULT_BLOCK_SIZE = 1048576


def _encode_block(data, max_chain=lz.MAX_CHAIN, lazy=lz.LAZY, level=None):
    fs = scan_features(data)
    mode, _hint = classify(fs)
    payload = None
    tmeta = b""

    # Phrase translation is a structural representation. Do not let it
    # change ordinary plain-text blocks from MODE_LZ: the core DE2 classifier
    # contract requires ordinary printable text to use the direct LZ path.
    # Structured text remains eligible for the phrase frontend.
    phrase_eligible = mode == MODE_STRUCT_LZ
    phrase_eligible = phrase_eligible and len(data) >= 64
    phrase_eligible = phrase_eligible and fs.printable_frac >= 0.70
    phrase_eligible = phrase_eligible and fs.match_density >= 0.01
    if phrase_eligible:
        k = universal_translator.choose_phrase_length(data)
        if k is not None:
            transformed, pmeta = universal_translator.translate_phrase(data, k)
            if transformed is not None:
                mode = MODE_STRUCT_LZ
                payload = lz.encode_v2(transformed, max_chain=max_chain,
                                       lazy=lazy, level=level)
                tmeta = pmeta

    if mode == MODE_STRUCT_LZ and payload is None:
        mode = MODE_LZ

    if mode == MODE_RLE:
        blob = rle_encode(data)
        if blob is not None:
            payload = blob
        else:
            mode = MODE_LZ

    if mode == MODE_DELTA_LZ:
        payload, tmeta = transforms.numeric_encode(
            data, mono=fs.mono32, hi_gain=fs.delta_ratio, _enc=lz.encode_v2)

    if mode == MODE_LZ and payload is None:
        payload = lz.encode_v2(data, max_chain=max_chain, lazy=lazy,
                               level=level)

    # Universal invariant: never expand a block.
    if payload is None or len(payload) >= len(data):
        return write_block(MODE_RAW, b"", data, bytes(data))

    return write_block(mode, tmeta, data, payload)


def compress(data, block_size=DEFAULT_BLOCK_SIZE, max_chain=lz.MAX_CHAIN,
             lazy=lz.LAZY, level="BALANCED"):
    """Compress bytes into a DE2 container.

    One block receives one representation decision and one final DE2 encode.
    level: "FAST" | "BALANCED" | "MAX" matcher preset.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("compress expects bytes-like data")
    data = bytes(data)
    n = len(data)
    blocks = []
    for off in range(0, n, block_size):
        chunk = data[off:off + block_size]
        blocks.append(_encode_block(chunk, max_chain=max_chain,
                                     lazy=lazy, level=level))
    out = bytearray()
    out += write_header(n, len(blocks), flags=FLAG_LZ_V2)
    for b in blocks:
        out += b
    return bytes(out)


def block_modes(blob):
    """Introspection: list of mode names, one per block."""
    _orig_total, block_count, _flags, pos = parse_header(blob)
    return [container.MODE_NAMES.get(h.mode, str(h.mode))
            for h, _c in iter_blocks(blob, pos, len(blob), block_count,
                                     _orig_total)]


def decompress(blob, verify=True):
    orig_total, block_count, flags, pos = parse_header(blob)
    end = len(blob)
    tables = entropy.DecodeTables()
    frame_decode = lz.decode_v2 if (flags & FLAG_LZ_V2) else lz.decode
    parts = []
    produced = 0
    for header, crc in iter_blocks(blob, pos, end, block_count, orig_total):
        raw_len = header.raw_len
        payload = header.payload
        mode = header.mode
        if mode == MODE_RAW:
            if len(payload) != raw_len:
                raise CorruptedError("raw block size mismatch")
            data = payload
        elif mode == MODE_RLE:
            data, _p = rle_decode(payload, 0, len(payload), raw_len)
        elif mode == MODE_LZ:
            data, _p = frame_decode(payload, 0, len(payload), raw_len,
                                    tables)
        elif mode == MODE_DELTA_LZ:
            inner, _p = frame_decode(payload, 0, len(payload), raw_len,
                                     tables)
            data = transforms.transform_decode(inner, header.tmeta, raw_len)
            if len(data) != raw_len:
                raise CorruptedError("delta produced wrong block size")
        elif mode == MODE_STRUCT_LZ:
            transformed_len = phrase.transformed_length(header.tmeta)
            inner, _p = frame_decode(payload, 0, len(payload),
                                     transformed_len, tables)
            data = phrase.decode(inner, header.tmeta, raw_len)
        else:
            raise CorruptedError("unhandled block mode %d" % mode)
        if verify:
            check_block_crc(data, crc)
        parts.append(data)
        produced += len(data)
    if produced != orig_total:
        raise CorruptedError("assembled size mismatch")
    return b"".join(parts)