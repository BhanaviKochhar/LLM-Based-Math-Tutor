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
import logging
import re
import threading
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

log = logging.getLogger(__name__)

TOP_K_PER_RETRIEVER = 20   # candidates from each retriever before fusion
TOP_K_FINAL = 3            # team contract: exactly 3 strings
RRF_K = 60                 # standard RRF constant
INCLUDE_GRADE_BELOW = True # Class 3 query also searches Class 2 (prerequisites)

# Front matter (copyright page, NCF preface, advisory-committee lists...) is
# not child-facing content, but it was being indexed and retrieved like any
# other chunk -- confirmed live: "what is a calendar used for" (Class 2, a
# plain always-allowed topic) pulled 2 of its 3 context chunks from NCF
# preface boilerplate that happens to mention "annual calendar" in a school-
# scheduling sense, crowding out the one genuinely relevant chunk and biasing
# the model toward refusing. This is a STRUCTURAL corpus-quality filter, not
# a topic- or wording-specific patch -- it excludes a page RANGE, the same
# "front matter lives on pages 1-4" characterization already measured for
# this corpus (confirmed: exactly 48 chunks, all tagged type='content' with
# no distinguishing field, since front-matter was never tagged at index
# time -- page is the only signal available without re-extracting the PDFs).
FRONT_MATTER_MAX_PAGE = 4

# Answer-blank chunks -- a page's worth of fill-in-the-blank underscores or
# dots with no actual teaching content (confirmed: 15 chunks corpus-wide,
# 13 of them in the Class 1 book -- the same count this corpus's own stats
# already document). These can't inform ANY answer and are pure noise in a
# ranking competing against real content.
_ANSWER_BLANK_RE = re.compile(r"^[\s_.]+$")


# ---------------------------------------------------------------------------
# Cached loaders (Streamlit will call retrieve() on every message)
# ---------------------------------------------------------------------------
def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@lru_cache(maxsize=1)
def _load_chunks() -> list[dict]:
    """The full corpus, in file order. A chunk's position in this list IS
    its stable identity (chunk_i) -- ChromaDB's own ids (ids=['chunk_0',
    'chunk_1', ...], confirmed live to correspond 1:1 to this list's index
    at build time) already use the same scheme, so ranking on this index
    throughout keeps both retrievers' results trivially mappable back to
    their real chunk, with no second lookup needed."""
    with open(CHUNKS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _canonical_index() -> dict[int, int]:
    """Maps every chunk index to ONE representative index for its exact
    text: itself, unless this exact text also appears at an earlier
    (lower file-order) chunk elsewhere in the corpus, in which case it maps
    to THAT one. 137 distinct texts repeat across 289 chunks in this corpus
    (confirmed) -- mostly shared NCF front matter (already excluded by page)
    and genuine same-book near-duplicates (e.g. the exact same "2D-shapes:
    visual recognition..." passage chunked separately at two different
    pages). Used to POOL the two retrievers' votes for what's really the
    same passage onto one ranking entry instead of splitting across two --
    confirmed via eval/component_eval/retrieval_eval.py that NOT pooling
    measurably hurt Recall@1 relative to the prior (accidentally pooling,
    via its own now-fixed text-keyed bug) behavior, by diluting each
    duplicate's individual rank instead of combining them. ALSO fixes the
    citation-arbitrariness bug on its own: every mention of a duplicated
    passage now resolves to the same, deterministic (lowest file-order)
    chunk, not whichever happened to load last into a dict."""
    canonical: dict[int, int] = {}
    by_text: dict[str, int] = {}
    for i, c in enumerate(_load_chunks()):
        first = by_text.setdefault(c["text"], i)
        canonical[i] = first
    return canonical


@lru_cache(maxsize=1)
def _content_indices() -> frozenset[int]:
    """Indices of chunks that pass the structural noise filters: not front
    matter, not an answer-blank-only page. (Duplicate collapsing is handled
    separately, per-query, in _canonicalize -- it must stay grade-aware,
    which this corpus-wide cache deliberately is not.)"""
    return frozenset(
        i for i, c in enumerate(_load_chunks())
        if c["page"] > FRONT_MATTER_MAX_PAGE and not _ANSWER_BLANK_RE.match(c["text"])
    )


def _canonicalize(indices: list[int], grades: tuple[int, ...]) -> list[int]:
    """Remap exact-duplicate text to one representative per _canonical_index,
    but ONLY to a representative that is ALSO within the requested grade
    window -- so this can never cite a grade outside G(g) even if the same
    text happens to also appear, elsewhere, in some other grade's book (the
    front-matter case; real same-book duplicates seen in this corpus are
    within one grade, so this guard is a safety net, not the common case).

    Deliberately does NOT de-duplicate the list -- a single retriever can
    independently rank TWO chunks that are the same underlying passage (the
    corpus has whole-page duplicates, e.g. Class 1 pages 146/163 repeat the
    same 9-chunk lesson verbatim), and if BOTH surface in that retriever's
    own top-k, leaving both occurrences (now sharing one canonical id) lets
    _rrf_fuse's existing per-ranking summation naturally pool their
    reciprocal-rank contributions onto that one entry, same as a real "both
    retrievers agree" boost. Confirmed via eval/component_eval/
    retrieval_eval.py: dropping the second occurrence outright (an earlier
    version of this function) measurably hurt Recall@3 by splitting what
    should be one combined signal across two separately-ranked copies."""
    canonical = _canonical_index()
    chunks = _load_chunks()
    out = []
    for i in indices:
        rep = canonical.get(i, i)
        if chunks[rep]["grade"] not in grades:
            rep = i
        out.append(rep)
    return out


@lru_cache(maxsize=8)
def _bm25_for_grades(grades: tuple[int, ...]) -> tuple[BM25Okapi, list[int]]:
    content = _content_indices()
    indices = [i for i, c in enumerate(_load_chunks())
              if c["grade"] in grades and i in content]
    corpus = [_tokenize(_load_chunks()[i]["text"]) for i in indices]
    return BM25Okapi(corpus), indices


_BUILD_BATCH = 100
_build_lock = threading.Lock()


def build_index(path: Path = CHROMADB_DIR):
    """(Re)build the ChromaDB collection from data/extracted_json.

    data/chromadb is gitignored, so a fresh host (CI, Streamlit Cloud) has no
    index. This builds one with the same ids, documents and metadata as
    scripts/load_chromadb.py, but lets Chroma embed with its built-in
    all-MiniLM-L6-v2 -- the embedding function every query here already
    uses -- so the host needs no torch or sentence-transformers."""
    client = chromadb.PersistentClient(path=str(path))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    col = client.create_collection(COLLECTION_NAME)
    chunks = _load_chunks()
    for start in range(0, len(chunks), _BUILD_BATCH):
        batch = chunks[start:start + _BUILD_BATCH]
        col.add(
            ids=[f"chunk_{start + j}" for j in range(len(batch))],
            documents=[c["text"] for c in batch],
            metadatas=[{"grade": c["grade"],
                        "page": c["page"],
                        "topic": c.get("topic") or "",
                        "type": c.get("type") or "",
                        "source": c.get("source", "NCERT")} for c in batch],
        )
    return col


@lru_cache(maxsize=1)
def _chroma_collection():
    # Locked so two sessions starting at once on a fresh host build once.
    # A missing or partial collection (an interrupted build) is rebuilt.
    with _build_lock:
        client = chromadb.PersistentClient(path=str(CHROMADB_DIR))
        try:
            col = client.get_collection(COLLECTION_NAME)
            if col.count() == len(_load_chunks()):
                return col
        except Exception:
            pass
        return build_index()


# ---------------------------------------------------------------------------
# Retrieval internals -- both retrievers rank and return chunk INDICES (int
# positions into _load_chunks()), never raw text. Previously each returned
# text strings, and retrieve_with_metadata() reverse-looked-up metadata by
# matching that text against the full corpus (`{c["text"]: c for c in
# _load_chunks()}`) -- silently WRONG whenever a chunk's text is duplicated
# elsewhere in the corpus, which the dict comprehension resolves to
# whichever duplicate happens to load last. Confirmed live: the exact NCF
# preface text implicated in the front-matter bug above appears VERBATIM on
# page 3 of all five grade books, so that lookup was citing a child's
# retrieved Class 1 chunk as if it were from Class 5. Ranking on the stable
# index throughout removes the need for that lookup entirely.
# ---------------------------------------------------------------------------
def _grade_filter(grade: int) -> tuple[int, ...]:
    if INCLUDE_GRADE_BELOW and grade > 1:
        return (grade - 1, grade)
    return (grade,)


def _bm25_ranked(question: str, grades: tuple[int, ...], k: int) -> list[int]:
    bm25, indices = _bm25_for_grades(grades)
    scores = bm25.get_scores(_tokenize(question))
    ranked = sorted(range(len(indices)), key=lambda i: scores[i], reverse=True)
    hits = [indices[i] for i in ranked[:k] if scores[i] > 0]
    return _canonicalize(hits, grades)


def _chroma_ranked(question: str, grades: tuple[int, ...], k: int) -> list[int]:
    col = _chroma_collection()
    grade_clause = {"grade": grades[0]} if len(grades) == 1 else {"grade": {"$in": list(grades)}}
    where = {"$and": [grade_clause, {"page": {"$gt": FRONT_MATTER_MAX_PAGE}}]}
    # Over-fetch: the answer-blank filter and duplicate collapsing both
    # happen AFTER this query (Chroma's `where` can express the page-range
    # exclusion but not "text isn't just underscores" or "collapse to
    # canonical duplicate"), so asking for only k here could under-fill
    # once those are applied.
    res = col.query(query_texts=[question], n_results=k * 2, where=where)
    ids = res["ids"][0] if res["ids"] else []
    content = _content_indices()
    hits = [int(cid.removeprefix("chunk_")) for cid in ids]
    hits = [i for i in hits if i in content][:k]
    return _canonicalize(hits, grades)


# ---------------------------------------------------------------------------
# The meaning-based half in Supabase (pgvector). Same model, grade window,
# front-matter rule and distance as the Chroma path above; the database only
# replaces the local index (supabase/schema.sql match_chunks). Chroma stays
# the path wherever Supabase isn't configured -- local runs and CI -- and
# while the chunks haven't all been uploaded yet.
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _query_embedder():
    """Chroma's built-in all-MiniLM-L6-v2: the same function the Chroma
    collection embeds queries with, used here without the collection."""
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    return DefaultEmbeddingFunction()


def _embed(text: str) -> list[float]:
    return [float(x) for x in _query_embedder()([text])[0]]


def _supabase_configured() -> bool:
    try:
        from scripts.llm import db
    except ImportError:  # run as a plain script (python scripts/retrieval.py)
        return False
    return db.configured()


_all_chunks_uploaded: bool | None = None


def _supabase_has_all_chunks() -> bool:
    """Whether every chunk is in Supabase. Only a completed check is
    remembered; one that fails (database unreachable) raises and is tried
    again on the next question. A refusal from the database itself -- the
    table not created yet -- counts as "not uploaded", so the local index
    is used rather than keyword search alone."""
    global _all_chunks_uploaded
    if _all_chunks_uploaded is None:
        from postgrest.exceptions import APIError

        from scripts.llm import db
        try:
            _all_chunks_uploaded = db.chunk_count() == len(_load_chunks())
        except APIError:
            _all_chunks_uploaded = False
    return _all_chunks_uploaded


def _supabase_ranked(question: str, grades: tuple[int, ...], k: int) -> list[int]:
    from scripts.llm import db
    # Same over-fetch and post-filtering as _chroma_ranked.
    hits = db.match_chunks(_embed(question), grades, FRONT_MATTER_MAX_PAGE, k * 2)
    content = _content_indices()
    hits = [i for i in hits if i in content][:k]
    return _canonicalize(hits, grades)


def _dense_ranked(question: str, grades: tuple[int, ...], k: int) -> list[int]:
    if not _supabase_configured():
        return _chroma_ranked(question, grades, k)
    try:
        if _supabase_has_all_chunks():
            return _supabase_ranked(question, grades, k)
    except Exception as exc:
        # The child still gets an answer: this one question is ranked by the
        # keyword half alone.
        log.warning("textbook search unreachable, using keyword search alone: %s", exc)
        return []
    return _chroma_ranked(question, grades, k)


def warm_up() -> None:
    """Load what the first question needs: the embedding model when the
    vectors are in Supabase, otherwise the local Chroma index (built if
    missing)."""
    if _supabase_configured():
        try:
            ready = _supabase_has_all_chunks()
        except Exception:
            ready = True  # unreachable for now; questions use keyword search until it's back
        if ready:
            _embed("warm up")
            return
    _chroma_collection()


def _rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> list[int]:
    scores: dict[int, float] = {}
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
    dense_hits = _dense_ranked(question, grades, TOP_K_PER_RETRIEVER)
    fused = _rrf_fuse([bm25_hits, dense_hits])
    chunks = _load_chunks()
    return [chunks[i]["text"] for i in fused[:top_k]]


def retrieve_with_metadata(question: str, grade: int, top_k: int = TOP_K_FINAL) -> list[dict]:
    """Same ranking, but returns full chunk dicts (grade/page/topic/type) --
    indexed directly off the fused ranking's own chunk ids, not a reverse
    text lookup (see the module-level note above for why that was wrong)."""
    if not 1 <= grade <= 5:
        raise ValueError(f"grade must be 1-5, got {grade}")

    grades = _grade_filter(grade)
    bm25_hits = _bm25_ranked(question, grades, TOP_K_PER_RETRIEVER)
    dense_hits = _dense_ranked(question, grades, TOP_K_PER_RETRIEVER)
    fused = _rrf_fuse([bm25_hits, dense_hits])
    chunks = _load_chunks()
    return [chunks[i] for i in fused[:top_k]]


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