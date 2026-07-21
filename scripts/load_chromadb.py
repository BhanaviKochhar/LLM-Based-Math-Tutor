import json
import os
print("started")

from sentence_transformers import SentenceTransformer
print("sentence_transformers loaded")

import chromadb
print("chromadb loaded")

with open("data/extracted_json/ncert_chunks.json","r",encoding="utf-8") as f:
    chunks=json.load(f)
print("chunks loaded:",len(chunks))

client=chromadb.PersistentClient(path="data/chromadb")
try:
    client.delete_collection("ncert_math")
    print("old collection cleared")
except Exception:
    pass

collection=client.create_collection("ncert_math")
print("collection created")

print("loading embedding model...")
model=SentenceTransformer("all-MiniLM-L6-v2")
print("model ready")

BATCH=100
for i in range(0,len(chunks),BATCH):
    batch=chunks[i:i+BATCH]
    texts=[c["text"] for c in batch]
    ids=[f"chunk_{i+j}" for j in range(len(batch))]
    embeddings=model.encode(texts, show_progress_bar=True).tolist()
    metadatas=[{"grade": c["grade"],
            "page": c["page"],
            "topic": c.get("topic") or "",
            "type": c.get("type") or "",
            "source": c.get("source", "NCERT")} for c in batch]
    collection.add(documents=texts,embeddings=embeddings,metadatas=metadatas,ids=ids)
    print(f"batch {i//BATCH+1} done, total so far: {i+len(batch)}")

print("DONE! Total in ChromaDB:",collection.count())