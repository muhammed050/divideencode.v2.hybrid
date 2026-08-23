from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from divideencode import de2
from divideencode.v3 import binary_json

CORPUS=Path(__file__).parent/"corpus"
BS=1<<20

def main():
    print("V3 BINARY JSON V2 — typed tree -> DE2")
    for name in ("json_small.json","json_large.json"):
        data=(CORPUS/name).read_bytes()
        t=time.perf_counter(); direct=de2.compress(data,block_size=BS,level="BALANCED"); dt=time.perf_counter()-t
        t=time.perf_counter(); blob=binary_json.encode(data); et=time.perf_counter()-t
        assert binary_json.decode(blob)==data
        t=time.perf_counter(); packed=de2.compress(blob,block_size=BS,level="BALANCED"); pt=time.perf_counter()-t
        print(f"{name:20s} source={len(data):9,d} direct={len(direct):8,d} bjson={len(blob):9,d} packed={len(packed):8,d} delta={len(packed)-len(direct):+8,d} ({(len(packed)/len(direct)-1)*100:+.2f}%) encode={et:.2f}s de2={pt:.2f}s")

if __name__=="__main__": main()
