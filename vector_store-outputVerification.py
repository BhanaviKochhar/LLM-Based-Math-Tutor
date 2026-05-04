import json
from pathlib import Path
import faiss

index = faiss.read_index("indexes/faiss.index")
metadata = json.loads(Path("indexes/metadata.json").read_text(encoding="utf-8"))

print("total vectors:", index.ntotal)
print("metadata length:", len(metadata))
print("match:", index.ntotal == len(metadata))
