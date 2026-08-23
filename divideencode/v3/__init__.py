"""DE3-derived research components built on the V3 core.

The package is intentionally not wired into the production DE2 container yet.
It provides the real token coder that will be used for the merged-token-stream
experiment while keeping the stable V3 codec unchanged.
"""

from .coder import decode_tokens, encode_tokens, encoded_size

__all__ = ["encode_tokens", "decode_tokens", "encoded_size"]
