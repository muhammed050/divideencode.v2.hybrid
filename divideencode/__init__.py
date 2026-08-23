from .encoder import compress, recursive_compress, MAGIC as CONTAINER_MAGIC, VERSION
from .decoder import decompress, decompress_with_trace, parse_header
from .universal import compress as universal_compress, decompress as universal_decompress
from .adaptive_universal import compress as adaptive_compress, decompress as adaptive_decompress
from .universal_ir import Kind as UniversalIRKind, Candidate as UniversalIRCandidate
from .universal_ir import transform as universal_ir_transform, inverse as universal_ir_inverse
from .universal_ir import rank as universal_ir_rank, best as universal_ir_best
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
    "decompress_with_trace",
    "parse_header",
    "recursive_compress",
    "render_trace",
    "DivideEncodeError",
    "CorruptedError",
    "NotDivideEncodedError",
    "__version__",
]
