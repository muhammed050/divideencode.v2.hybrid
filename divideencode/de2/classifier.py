"""DE2 deterministic codec classifier (M0/M3).

Decides ONE pipeline per block from the FeatureSet alone. Never runs
candidate compressions to choose. A development compare-mode lives in
benchmarks, not in the hot path.
"""

MODE_RAW = 0
MODE_RLE = 1
MODE_LZ = 2
MODE_DELTA_LZ = 3
MODE_STRUCT_LZ = 4

MODE_NAMES = {
    MODE_RAW: "RAW",
    MODE_RLE: "RLE",
    MODE_LZ: "LZ",
    MODE_DELTA_LZ: "DELTA+LZ",
    MODE_STRUCT_LZ: "STRUCT+LZ",
}

# thresholds (tuned on the project corpus; see benchmarks)
_INCOMPRESSIBLE_H0 = 7.95
_INCOMPRESSIBLE_MATCH = 0.03
_RLE_RUN_FRAC = 0.45
_RLE_BIG_RUN_FRAC = 0.25
_JSON_PER_KB = 24.0
_CSV_PER_KB = 20.0
_XML_PER_KB = 8.0
_MONO32 = 0.85
_DELTA_GAIN = 2.0


def classify(fs):
    """Return (mode, tmeta_hint) from a FeatureSet. Deterministic."""
    n = fs.n
    if n == 0:
        return MODE_RAW, None

    # Run-heavy data first: extreme runs are unambiguous.
    if fs.run_bytes_frac >= _RLE_RUN_FRAC or \
            (fs.big_run and fs.run_bytes_frac >= _RLE_BIG_RUN_FRAC):
        return MODE_RLE, None

    # Highly printable blocks are text-first. This prevents u32 monotonicity
    # and delta heuristics from stealing ordinary prose. Structured text is
    # still handled before the generic LZ fallback.
    if fs.printable_frac >= 0.95:
        if fs.json_score >= _JSON_PER_KB:
            return MODE_STRUCT_LZ, b"J"
        if fs.newline_per_kb > 2.0 and fs.csv_score >= _CSV_PER_KB:
            return MODE_STRUCT_LZ, b"C"
        if fs.xml_score >= _XML_PER_KB:
            return MODE_STRUCT_LZ, b"X"
        return MODE_LZ, None

    # Numeric / sequential detection for non-text blocks only.
    if (fs.mono32 >= _MONO32) or (fs.delta_ratio >= _DELTA_GAIN):
        return MODE_DELTA_LZ, None

    # Incompressible: high entropy, no repetition -> RAW immediately.
    if fs.h0 >= _INCOMPRESSIBLE_H0 and fs.k >= 250 \
            and fs.match_density < _INCOMPRESSIBLE_MATCH:
        return MODE_RAW, None

    # Structured text with weaker printable ratios (e.g. UTF-8/control-heavy
    # formats) remains available after the binary heuristics.
    printable = fs.printable_frac > 0.9
    if printable and fs.json_score >= _JSON_PER_KB:
        return MODE_STRUCT_LZ, b"J"
    if printable and fs.newline_per_kb > 2.0 and fs.csv_score >= _CSV_PER_KB:
        return MODE_STRUCT_LZ, b"C"
    if printable and fs.xml_score >= _XML_PER_KB:
        return MODE_STRUCT_LZ, b"X"

    return MODE_LZ, None
