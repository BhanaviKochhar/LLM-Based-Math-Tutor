import json
import numpy as np
from pathlib import Path

path = Path("data/processed/embeddings.json")
records = json.loads(path.read_text(encoding="utf-8"))

print("total embeddings:", len(records))
print("first embedding length:", len(records[0]["embedding"]) if records else 0)

if records:
    first_embedding = np.array(records[0]["embedding"], dtype=np.float32)
    print("dtype after float32 cast:", first_embedding.dtype)
