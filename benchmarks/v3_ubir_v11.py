from pathlib import Path
import time
from divideencode.v3 import universal_binary_ir as v1
from divideencode.v3 import ubir_v11 as v11
from divideencode.de2 import compress

CORPUS = Path(__file__).resolve().parent / "corpus"

for name in ("json_small.json", "json_large.json"):
    data = (CORPUS / name).read_bytes()
    t = time.perf_counter(); d = compress(data, block_size=1 << 20, level="BALANCED"); dt = time.perf_counter()-t
    t = time.perf_counter(); b1 = v1.encode(data, "json"); e1=time.perf_counter()-t
    assert v1.decode(b1) == data
    t = time.perf_counter(); p1 = compress(b1, block_size=1 << 20, level="BALANCED"); c1=time.perf_counter()-t
    t = time.perf_counter(); b11 = v11.encode(data, "json"); e11=time.perf_counter()-t
    assert v11.decode(b11) == data
    t = time.perf_counter(); p11 = compress(b11, block_size=1 << 20, level="BALANCED"); c11=time.perf_counter()-t
    print(f"{name:18s} direct={len(d):7d} UBIRv1={len(p1):7d} V1.1={len(p11):7d} "
          f"delta={len(p11)-len(d):+7d} vs_v1={len(p11)-len(p1):+7d} "
          f"ir={len(b11):8d} encode={e11:.2f}s de2={c11:.2f}s")
