"""ABR6 unified selector.

This is an experiment branch only. It does not replace DE2. It collects the
best reversible ABR families already developed plus the new ABR6 JSON/CSV
semantic transforms. The caller must compare final DE2 sizes and keep the
smallest valid result.
"""
from __future__ import annotations
from . import adaptive_binary as abr1
from . import adaptive_binary_v2 as abr2
from . import adaptive_binary_v4 as abr4
from . import adaptive_binary_v5 as abr5
from . import adaptive_binary_v6 as abr6


def candidates(data: bytes, suffix: str):
    out=[]; seen=set()
    for name, mod in (
        ('abr1', abr1), ('abr2', abr2), ('abr4', abr4), ('abr5', abr5), ('abr6', abr6)
    ):
        try:
            for kind, payload in mod.candidates(data, suffix):
                key=payload
                if key in seen: continue
                seen.add(key)
                label=kind if str(kind).startswith('abr6:') else f'{name}:{kind}'
                out.append((label, payload))
        except (UnicodeDecodeError, ValueError, IndexError, TypeError):
            continue
    return out
