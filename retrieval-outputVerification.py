import os
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.retrieval import (
    DEFAULT_INDEX_PATH,
    DEFAULT_METADATA_PATH,
    build_context,
    load_faiss_index,
    load_metadata,
    load_model,
    retrieve,
)


queries = [
    "What is half?",
    "364 + 52",
    "What is symmetry?",
]

index = load_faiss_index(DEFAULT_INDEX_PATH)
metadata = load_metadata(DEFAULT_METADATA_PATH)

print("total vectors:", index.ntotal)
print("metadata length:", len(metadata))
print("match:", index.ntotal == len(metadata))

try:
    model = load_model()
except RuntimeError as error:
    print("model loaded:", False)
    print("error:", error)
else:
    print("model loaded:", True)

    for query in queries:
        results = retrieve(query, index, metadata, model, top_k=3)

        print()
        print("query:", query)
        print("retrieved results:", len(results))
        print("top score:", results[0]["score"] if results else None)
        print("top source:", results[0]["source"] if results else None)
        print("top page:", results[0]["page"] if results else None)
        print("top text preview:", results[0]["text"][:200] if results else None)
        print("context preview:", build_context(results)[:300])
