"""
retrieval.py — Hybrid retrieval over the NCERT Class 1-5 chunks.

Combines:
  - Dense retrieval: ChromaDB, using the same all-MiniLM-L6-v2 embeddings
    load_chromadb.py used to index the 2329 chunks.
  - Sparse retrieval: BM25 over the same chunk texts, good for catching
    exact term matches (e.g. "LCM", "Roman numerals") that embeddings can
    sometimes blur.

Scores from both are normalised to [0, 1] and combined with a weighted sum
(RRF-lite). Results are filtered by `grade` using ChromaDB metadata BEFORE
scoring, so grade filtering is free and exact rather than a re-rank step.

--------------------------------------------------------------------------
ASSUMPTIONS TO VERIFY AGAINST YOUR ACTUAL load_chromadb.py / parse_ncert.py
--------------------------------------------------------------------------
1. Chroma collection name: "ncert_math_chunks"        -> change COLLECTION_NAME
2. Chroma persist directory: "./chroma_db"             -> change PERSIST_DIR
3. Each chunk's metadata has these keys:
     - "grade"  (int, 1-5)
     - "source" (str, e.g. "NCERT Class 3, Chapter 5: Fun with Multiplication")
   If your metadata uses different key names (e.g. "class" instead of
   "grade", or "chapter" instead of "source"), update GRADE_KEY / SOURCE_KEY
   below rather than renaming things everywhere.
4. Embedding function used at index time: all-MiniLM-L6-v2 via
   sentence-transformers. Query-time embedding must match — see
   `_embed_query()`.
"""

from __future__ import annotations

from dataclasses import dataclass

from rank_bm25 import BM25Okapi

# ---------------------------------------------------------------------------
# Config — adjust these three blocks to match your actual pipeline
# ---------------------------------------------------------------------------

COLLECTION_NAME = "ncert_math_chunks"
PERSIST_DIR = "./chroma_db"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

GRADE_KEY = "grade"    # metadata key holding the class/grade number
SOURCE_KEY = "source"  # metadata key holding the chapter/book reference

# Weight given to dense (ChromaDB) vs sparse (BM25) scores when combining.
DENSE_WEIGHT = 0.6
SPARSE_WEIGHT = 0.4


@dataclass
class RetrievedChunk:
    text: str
    source: str
    grade: int
    score: float


class HybridRetriever:
    """
    Loads the ChromaDB collection once, builds a BM25 index over its chunks
    once, and answers `retrieve()` calls cheaply after that.

    Usage:
        retriever = HybridRetriever()
        chunks = retriever.retrieve("what is 3 x 4", grade=3, top_k=5)
    """

    def __init__(
        self,
        collection_name: str = COLLECTION_NAME,
        persist_dir: str = PERSIST_DIR,
        embedding_model: str = EMBEDDING_MODEL,
    ):
        import chromadb
        from sentence_transformers import SentenceTransformer

        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_collection(collection_name)
        self._embedder = SentenceTransformer(embedding_model)

        # Pull everything once to build the BM25 sparse index. Fine at
        # ~2329 chunks; if the corpus grows a lot, move this to a cached
        # build step (pickle the BM25 index) instead of rebuilding on init.
        all_docs = self._collection.get(include=["documents", "metadatas"])
        self._doc_ids = all_docs["ids"]
        self._doc_texts = all_docs["documents"]
        self._doc_metas = all_docs["metadatas"]

        tokenised = [self._tokenise(t) for t in self._doc_texts]
        self._bm25 = BM25Okapi(tokenised)

    @staticmethod
    def _tokenise(text: str) -> list[str]:
        return text.lower().split()

    def _embed_query(self, query: str) -> list[float]:
        return self._embedder.encode(query).tolist()

    @staticmethod
    def _normalise(scores: list[float]) -> list[float]:
        if not scores:
            return scores
        lo, hi = min(scores), max(scores)
        if hi == lo:
            return [1.0 for _ in scores]
        return [(s - lo) / (hi - lo) for s in scores]

    def retrieve(self, query: str, grade: int, top_k: int = 5) -> list[RetrievedChunk]:
        # ---- Dense: ChromaDB, pre-filtered by grade via `where` ----
        dense_result = self._collection.query(
            query_embeddings=[self._embed_query(query)],
            n_results=min(top_k * 3, len(self._doc_texts)),  # over-fetch, then re-rank
            where={GRADE_KEY: grade},
            include=["documents", "metadatas", "distances"],
        )

        dense_ids = dense_result["ids"][0]
        dense_docs = dense_result["documents"][0]
        dense_metas = dense_result["metadatas"][0]
        # Chroma returns distances (lower = closer); convert to similarity.
        dense_distances = dense_result["distances"][0]
        dense_sims = [1 / (1 + d) for d in dense_distances]
        dense_sims_norm = self._normalise(dense_sims)

        # ---- Sparse: BM25 over the FULL corpus, then filter by grade ----
        bm25_scores = self._bm25.get_scores(self._tokenise(query))
        sparse_candidates = [
            (self._doc_ids[i], self._doc_texts[i], self._doc_metas[i], bm25_scores[i])
            for i in range(len(self._doc_ids))
            if self._doc_metas[i].get(GRADE_KEY) == grade
        ]
        sparse_candidates.sort(key=lambda x: x[3], reverse=True)
        sparse_candidates = sparse_candidates[: top_k * 3]
        sparse_scores_norm = self._normalise([c[3] for c in sparse_candidates])

        # ---- Merge into one score per chunk id ----
        combined: dict[str, dict] = {}

        for cid, doc, meta, sim in zip(dense_ids, dense_docs, dense_metas, dense_sims_norm):
            combined[cid] = {
                "text": doc,
                "meta": meta,
                "score": DENSE_WEIGHT * sim,
            }

        for (cid, doc, meta, _raw), sim in zip(sparse_candidates, sparse_scores_norm):
            if cid in combined:
                combined[cid]["score"] += SPARSE_WEIGHT * sim
            else:
                combined[cid] = {
                    "text": doc,
                    "meta": meta,
                    "score": SPARSE_WEIGHT * sim,
                }

        ranked = sorted(combined.values(), key=lambda x: x["score"], reverse=True)[:top_k]

        return [
            RetrievedChunk(
                text=r["text"],
                source=r["meta"].get(SOURCE_KEY, "NCERT"),
                grade=r["meta"].get(GRADE_KEY, grade),
                score=r["score"],
            )
            for r in ranked
        ]


# ---------------------------------------------------------------------------
# Module-level singleton so app.py doesn't rebuild the BM25 index on every
# request (this is the expensive part — building it once at import time).
# ---------------------------------------------------------------------------

_retriever_instance: HybridRetriever | None = None


def hybrid_retrieve(query: str, grade: int, top_k: int = 5) -> list[dict]:
    """
    Convenience entry point used by app.py / llm.py.
    Returns a list of dicts: [{"text": ..., "source": ..., "grade": ..., "score": ...}, ...]
    """
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = HybridRetriever()

    chunks = _retriever_instance.retrieve(query, grade=grade, top_k=top_k)
    return [c.__dict__ for c in chunks]
