"""
scripts/retrieval.py — Hybrid retrieval for LLM-Based Math Tutor (NCERT 1-5)

Team contract (Person 3 calls this directly):
    retrieve(question, grade) -> ["chunk1", "chunk2", "chunk3"]

Pipeline:
    BM25 (lexical) + ChromaDB (semantic) -> Reciprocal Rank Fusion -> top 3
    Grade filter applied to BOTH retrievers: {grade-1, grade}

Smoke test (from project root):
    python -u scripts/retrieval.py
"""

import json
import re
from functools import lru_cache
from pathlib import Path

import chromadb
from rank_bm25 import BM25Okapi

# ---------------------------------------------------------------------------
# Paths — this file lives in scripts/, data lives one level up in data/
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_JSON = PROJECT_ROOT / "data" / "extracted_json" / "ncert_chunks.json"
CHROMADB_DIR = PROJECT_ROOT / "data" / "chromadb"
COLLECTION_NAME = "ncert_math"

TOP_K_PER_RETRIEVER = 20   # candidates from each retriever before fusion
TOP_K_FINAL = 3            # team contract: exactly 3 strings
RRF_K = 60                 # standard RRF constant
INCLUDE_GRADE_BELOW = True # Class 3 query also searches Class 2 (prerequisites)


# ---------------------------------------------------------------------------
# Cached loaders (Streamlit will call retrieve() on every message)
# ---------------------------------------------------------------------------
def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@lru_cache(maxsize=1)
def _load_chunks() -> list[dict]:
    with open(CHUNKS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=8)
def _bm25_for_grades(grades: tuple[int, ...]) -> tuple[BM25Okapi, list[dict]]:
    subset = [c for c in _load_chunks() if c["grade"] in grades]
    corpus = [_tokenize(c["text"]) for c in subset]
    return BM25Okapi(corpus), subset


@lru_cache(maxsize=1)
def _chroma_collection():
    client = chromadb.PersistentClient(path=str(CHROMADB_DIR))
    return client.get_collection(COLLECTION_NAME)


# ---------------------------------------------------------------------------
# Retrieval internals
# ---------------------------------------------------------------------------
def _grade_filter(grade: int) -> tuple[int, ...]:
    if INCLUDE_GRADE_BELOW and grade > 1:
        return (grade - 1, grade)
    return (grade,)


def _bm25_ranked(question: str, grades: tuple[int, ...], k: int) -> list[str]:
    bm25, subset = _bm25_for_grades(grades)
    scores = bm25.get_scores(_tokenize(question))
    ranked = sorted(range(len(subset)), key=lambda i: scores[i], reverse=True)
    return [subset[i]["text"] for i in ranked[:k] if scores[i] > 0]


def _chroma_ranked(question: str, grades: tuple[int, ...], k: int) -> list[str]:
    col = _chroma_collection()
    where = {"grade": grades[0]} if len(grades) == 1 else {"grade": {"$in": list(grades)}}
    res = col.query(query_texts=[question], n_results=k, where=where)
    return res["documents"][0] if res["documents"] else []


def _rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


# ---------------------------------------------------------------------------
# Public API — the team contract
# ---------------------------------------------------------------------------
def retrieve(question: str, grade: int, top_k: int = TOP_K_FINAL) -> list[str]:
    """retrieve(question, grade) -> list of top_k chunk texts (default 3)."""
    if not 1 <= grade <= 5:
        raise ValueError(f"grade must be 1-5, got {grade}")

    grades = _grade_filter(grade)
    bm25_hits = _bm25_ranked(question, grades, TOP_K_PER_RETRIEVER)
    dense_hits = _chroma_ranked(question, grades, TOP_K_PER_RETRIEVER)
    fused = _rrf_fuse([bm25_hits, dense_hits])
    return fused[:top_k]


def retrieve_with_metadata(question: str, grade: int, top_k: int = TOP_K_FINAL) -> list[dict]:
    """Same ranking, but returns full chunk dicts (grade/page/topic/type)."""
    texts = retrieve(question, grade, top_k)
    by_text = {c["text"]: c for c in _load_chunks()}
    return [by_text.get(t, {"text": t}) for t in texts]


# ---------------------------------------------------------------------------
# Smoke test:  python -u scripts/retrieval.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        ("How do I add two numbers together?", 1),
        ("What is subtraction with borrowing?", 3),
        ("How do I find the perimeter of a rectangle?", 5),
    ]
    for q, g in tests:
        print(f"\nQ (Class {g}): {q}")
        for i, c in enumerate(retrieve_with_metadata(q, g), 1):
            print(f"  {i}. [grade {c.get('grade')}, topic {c.get('topic')}] {c['text'][:90]}...")