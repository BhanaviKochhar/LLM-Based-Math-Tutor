"""Upload the textbook chunks' vectors to Supabase (public.chunks).

One-off, and again whenever data/extracted_json/ncert_chunks.json changes.
Each chunk is embedded with Chroma's built-in all-MiniLM-L6-v2 -- the model
scripts/retrieval.py embeds questions with -- and written with its position
in the JSON file as its id. Safe to re-run: rows are upserted, and ids past
the end of the file are deleted.

Writing needs the project's SECRET key (the app's public key can only
read this table). It is read from SUPABASE_SECRET_KEY and never printed;
remove it from .env once the upload is done.

Run (from the repo root):  python -m scripts.upload_chunks
"""
from __future__ import annotations

import os
import sys
import time

from scripts import retrieval

_BATCH = 200


def main() -> None:
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv()
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        sys.exit("Set SUPABASE_URL and SUPABASE_SECRET_KEY first.")
    client = create_client(url, key)

    chunks = retrieval._load_chunks()
    embed = retrieval._query_embedder()
    started = time.time()
    for start in range(0, len(chunks), _BATCH):
        batch = chunks[start:start + _BATCH]
        vectors = embed([c["text"] for c in batch])
        rows = [{"id": start + j, "grade": c["grade"], "page": c["page"],
                 "embedding": [float(x) for x in vectors[j]]}
                for j, c in enumerate(batch)]
        client.table("chunks").upsert(rows).execute()
        print(f"  {start + len(batch)}/{len(chunks)} uploaded")
    client.table("chunks").delete().gte("id", len(chunks)).execute()

    count = client.table("chunks").select("id", count="exact", head=True).execute().count
    print(f"done in {time.time() - started:.0f}s: {count} chunks in Supabase, "
          f"{len(chunks)} in the JSON file")
    if count != len(chunks):
        sys.exit("Counts differ: the app will keep using the local Chroma index.")


if __name__ == "__main__":
    main()
