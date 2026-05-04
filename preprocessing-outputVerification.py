import json
from pathlib import Path

chunks = json.loads(Path("data/processed/chunks.json").read_text(encoding="utf-8"))
print("total_chunks =", len(chunks))
print("first_chunk =", chunks[0])
print("has_required_keys =", {"chunk_id", "text", "source", "page"} <= set(chunks[0]))
print("all_nontrivial =", all(len(chunk["text"]) >= 20 for chunk in chunks))
