from .encoder import compress, recursive_compress, MAGIC as CONTAINER_MAGIC, VERSION
from .decoder import decompress, decompress_with_trace, parse_header
from .universal import compress as universal_compress, decompress as universal_decompress
from .adaptive_universal import compress as adaptive_compress, decompress as adaptive_decompress
from .universal_ir import Kind as UniversalIRKind, Candidate as UniversalIRCandidate
from .universal_ir import transform as universal_ir_transform, inverse as universal_ir_inverse
from .universal_ir import rank as universal_ir_rank, best as universal_ir_best
from .universal_binary import SearchMode as UniversalBinarySearchMode
from .universal_binary import Analysis as UniversalBinaryAnalysis, Result as UniversalBinaryResult
from .universal_binary import analyze as universal_binary_analyze
from .universal_binary import rank_candidates as universal_binary_rank_candidates
from .universal_binary import compress as universal_binary_compress
from .universal_binary import compress_with_stats as universal_binary_compress_with_stats
from .universal_binary import decompress as universal_binary_decompress
from .errors import DivideEncodeError, CorruptedError, NotDivideEncodedError
from .strategies import render_trace

__version__ = "0.1.0"

__all__ = [
    "compress",
    "decompress",
    "universal_compress",
    "universal_decompress",
    "adaptive_compress",
    "adaptive_decompress",
    "UniversalIRKind",
    "UniversalIRCandidate",
    "universal_ir_transform",
    "universal_ir_inverse",
    "universal_ir_rank",
    "universal_ir_best",
    "UniversalBinarySearchMode",
    "UniversalBinaryAnalysis",
    "UniversalBinaryResult",
    "universal_binary_analyze",
    "universal_binary_rank_candidates",
    "universal_binary_compress",
    "universal_binary_compress_with_stats",
    "universal_binary_decompress",
    "decompress_with_trace",
    "parse_header",
    "recursive_compress",
    "render_trace",
    "DivideEncodeError",
    "CorruptedError",
    "NotDivideEncodedError",
    "__version__",
]
