"""Offline tests for scripts/retrieval.py's corpus-quality filters.

Deterministic and local (BM25 + ChromaDB, no network/API key) -- same cost
profile as eval/component_eval/retrieval_eval.py, but these lock in the
INTERNAL behavior (front-matter exclusion, answer-blank exclusion, grade-
safe duplicate pooling) rather than scoring against labelled queries.

Run:  python -m scripts.test_retrieval
"""
from __future__ import annotations

from scripts import retrieval as r

_passed = 0
_failed = 0


def check(name: str, cond: bool) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok   {name}")
    else:
        _failed += 1
        print(f"  FAIL {name}")


def test_front_matter_excluded() -> None:
    print("front-matter chunks (page <= 4) are excluded from retrieval candidates")
    chunks = r._load_chunks()
    content = r._content_indices()
    front_matter = [i for i, c in enumerate(chunks) if c["page"] <= r.FRONT_MATTER_MAX_PAGE]
    check("corpus actually has front-matter chunks to test against (sanity)",
         len(front_matter) > 0)
    check("none of them are in _content_indices()",
         not any(i in content for i in front_matter))
    # Live-reported bug: "what is a calendar used for" (Class 2) pulled 2 of
    # 3 context chunks from NCF preface boilerplate duplicated on page 3 of
    # every grade book, biasing the tutor toward refusing a plain
    # always-allowed topic. Confirmed fixed: every returned chunk is now
    # genuinely about the question's topic, page > 4.
    results = r.retrieve_with_metadata("what is a calendar used for", 2)
    check("a real query returns no front-matter chunk",
         all(c.get("page", 0) > r.FRONT_MATTER_MAX_PAGE for c in results))


def test_answer_blanks_excluded() -> None:
    print("answer-blank-only chunks (underscores/dots, no content) are excluded")
    chunks = r._load_chunks()
    content = r._content_indices()
    blanks = [i for i, c in enumerate(chunks) if r._ANSWER_BLANK_RE.match(c["text"])]
    check("corpus actually has answer-blank chunks to test against (sanity)",
         len(blanks) > 0)
    check("none of them are in _content_indices()",
         not any(i in content for i in blanks))
    check("a chunk that MIXES blanks with real question text is NOT excluded "
         "(the filter is 'blanks only', not 'contains any blank')",
         not r._ANSWER_BLANK_RE.match(
             "What is the day on your birthday? ___________"))


def test_duplicate_pages_pool_and_cite_canonically() -> None:
    """Confirmed live: Class 1 pages 146 and 163 are an exact 9-chunk
    duplicate of the same lesson (full page repeated verbatim at a
    different page number in the source PDF) -- same for pages 152/153 vs
    169/170. Before this fix, retrieve_with_metadata() reverse-looked-up
    metadata by matching raw TEXT against the whole corpus, which silently
    resolved every mention of a duplicated passage to whichever copy
    happened to load last -- confirmed, it cited a Class 1 chunk as if it
    were from Class 5 for the front-matter case. Canonicalizing by stable
    chunk index removes the ambiguity: the SAME passage always cites the
    SAME (earliest file-order) page, and the two retrievers' votes for it
    pool onto one ranking entry instead of splitting."""
    print("exact-duplicate pages collapse to one canonical, deterministic citation")
    chunks = r._load_chunks()
    canonical = r._canonical_index()

    def indices_at(grade, page):
        return [i for i, c in enumerate(chunks) if c["grade"] == grade and c["page"] == page]

    p146, p163 = indices_at(1, 146), indices_at(1, 163)
    check("Class 1 pages 146 and 163 are both present and the same length "
         "(sanity -- this is the known duplicate pair)",
         len(p146) == len(p163) > 0)
    check("every page-163 chunk canonicalizes to its page-146 twin",
         all(canonical[a] == b for a, b in zip(p163, p146)))

    rep_idx = canonical[p163[0]]
    check("the canonical representative is itself page 146, not 163 "
         "(earliest file-order wins, so citation is deterministic)",
         chunks[rep_idx]["page"] == 146)


def test_canonical_within_never_crosses_grade_window() -> None:
    """The front-matter case IS a cross-grade duplicate (the same NCF
    preface sentence appears on page 3 of all five books) -- but front
    matter is already excluded by page before this ever matters. For any
    chunk that reaches _canonicalize, redirecting it to a duplicate
    OUTSIDE the requested grade window must never happen; this is the
    safety net for that guarantee, exercised directly rather than hoping
    no future duplicate ever crosses a grade boundary unnoticed."""
    print("_canonicalize never redirects outside the requested grade window")
    chunks = r._load_chunks()
    # Pick any two chunks that genuinely are exact-text duplicates across
    # DIFFERENT grades (the front-matter case) to exercise the guard
    # directly, bypassing the page filter that would normally keep them
    # out of this function's input entirely.
    canonical = r._canonical_index()
    cross_grade_pair = None
    for i, c in enumerate(chunks):
        rep = canonical[i]
        if rep != i and chunks[rep]["grade"] != c["grade"]:
            cross_grade_pair = (i, rep)
            break
    check("the corpus has at least one real cross-grade duplicate to test "
         "against (sanity -- the known NCF-preface case)",
         cross_grade_pair is not None)
    if cross_grade_pair:
        i, rep = cross_grade_pair
        grades = (chunks[i]["grade"],)  # a window that does NOT include rep's grade
        out = r._canonicalize([i], grades)
        check("redirected only within-window, or left as the original "
             "index -- never pointed at the out-of-window canonical twin",
             out == [i] or chunks[out[0]]["grade"] in grades)


def test_grade_window_still_enforced() -> None:
    print("grade window is still enforced end-to-end after the filtering changes")
    for grade in range(1, 6):
        results = r.retrieve_with_metadata("teach me numbers", grade)
        window = {grade, grade - 1} if grade > 1 else {grade}
        check(f"grade {grade}: every returned chunk is within G({grade})={window}",
             all(c.get("grade") in window for c in results))


class _Patch:
    """Swap one module attribute for the length of a with-block."""

    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)


def _fresh_upload_check():
    r._all_chunks_uploaded = None


def test_search_path_choice() -> None:
    print("the meaning-based search uses Supabase only when configured and fully uploaded")
    from scripts.llm import db
    grades = (2, 3)
    chroma_calls, match_calls = [], []

    def fake_chroma(q, g, k):
        chroma_calls.append(q)
        return [999]

    def fake_match(vec, g, min_page, count):
        match_calls.append((tuple(g), min_page, count))
        # Nearest first; includes a front-matter-free but answer-blank chunk
        # and an out-of-content one, which must be filtered like Chroma's.
        blanks = [i for i, c in enumerate(r._load_chunks()) if r._ANSWER_BLANK_RE.match(c["text"])
                  and c["grade"] in g and c["page"] > r.FRONT_MATTER_MAX_PAGE]
        content = sorted(i for i in r._content_indices() if r._load_chunks()[i]["grade"] in g)
        return blanks[:1] + content[:5]

    with _Patch(r, "_chroma_ranked", fake_chroma), _Patch(r, "_embed", lambda t: [0.0] * 384),             _Patch(db, "match_chunks", fake_match):
        with _Patch(r, "_supabase_configured", lambda: False):
            _fresh_upload_check()
            check("not configured (local runs, CI) -> local Chroma",
                  r._dense_ranked("q", grades, 4) == [999])

        with _Patch(r, "_supabase_configured", lambda: True),                 _Patch(db, "chunk_count", lambda: len(r._load_chunks())):
            _fresh_upload_check()
            out = r._dense_ranked("q", grades, 4)
            check("configured and every chunk uploaded -> Supabase", match_calls != [])
            check("asks for the same grades, front-matter cut-off and 2x over-fetch as Chroma",
                  match_calls[-1] == (grades, r.FRONT_MATTER_MAX_PAGE, 8))
            check("answer-blank chunks are filtered out afterwards, as on the Chroma path",
                  len(out) <= 4 and all(i in r._content_indices() for i in out))

        with _Patch(r, "_supabase_configured", lambda: True),                 _Patch(db, "chunk_count", lambda: 10):
            _fresh_upload_check()
            chroma_calls.clear()
            check("configured but chunks not all uploaded -> local Chroma, never a silent half-search",
                  r._dense_ranked("q", grades, 4) == [999] and chroma_calls == ["q"])

        def no_table():
            from postgrest.exceptions import APIError
            raise APIError({"message": "relation public.chunks does not exist", "code": "42P01"})

        with _Patch(r, "_supabase_configured", lambda: True), _Patch(db, "chunk_count", no_table):
            _fresh_upload_check()
            chroma_calls.clear()
            check("configured but the table isn't created yet -> local Chroma, not keyword search alone",
                  r._dense_ranked("q", grades, 4) == [999] and chroma_calls == ["q"])

        def unreachable():
            raise ConnectionError("database unreachable")

        with _Patch(r, "_supabase_configured", lambda: True), _Patch(db, "chunk_count", unreachable):
            _fresh_upload_check()
            chroma_calls.clear()
            check("database unreachable -> no meaning-based hits (keyword search alone), no Chroma build",
                  r._dense_ranked("q", grades, 4) == [] and chroma_calls == [])
            check("and a failed check isn't remembered, so the next question tries again",
                  r._all_chunks_uploaded is None)

        def match_fails(*a):
            raise ConnectionError("database unreachable")

        with _Patch(r, "_supabase_configured", lambda: True),                 _Patch(db, "chunk_count", lambda: len(r._load_chunks())),                 _Patch(db, "match_chunks", match_fails):
            _fresh_upload_check()
            check("search call fails mid-question -> keyword search alone for that question",
                  r._dense_ranked("q", grades, 4) == [])
            hits = r.retrieve_with_metadata("how many legs does a spider have", 3)
            check("and the whole retrieval still returns textbook chunks", len(hits) == 3)
    _fresh_upload_check()


def test_exact_search_matches_chroma() -> None:
    """What the SQL function does -- exact nearest-by-L2 over the same
    vectors, same filters -- reproduced here over the local index's own
    vectors, against Chroma's answers for every retrieval-eval query."""
    print("exact search over the same vectors ranks like Chroma on the retrieval-eval queries")
    import json
    import math

    from scripts.llm import db
    col = r._chroma_collection()
    got = col.get(include=["embeddings"])
    vectors = {int(i.removeprefix("chunk_")): list(map(float, e))
               for i, e in zip(got["ids"], got["embeddings"])}
    chunks = r._load_chunks()

    def exact_match(vec, grades, min_page, count):
        cand = [i for i in vectors if chunks[i]["grade"] in grades and chunks[i]["page"] > min_page]
        dist = {i: math.fsum((a - b) ** 2 for a, b in zip(vectors[i], vec)) for i in cand}
        return sorted(cand, key=lambda i: (dist[i], i))[:count]

    queries = []
    with open(r.PROJECT_ROOT / "eval" / "datasets" / "retrieval.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                row = json.loads(line)
                queries.append((row["query"], row["grade"]))

    # Chroma's index is approximate (HNSW), so deep in the list it can skip a
    # chunk that is really nearer; exact search can't. Measured: 98 of 100
    # queries identical to rank 20, the other two first differ at ranks 15
    # and 18, each time an exact nearer chunk Chroma missed. What must hold
    # is the top of the list, which is all the final ranking draws on.
    top, full = 10, 0
    same_top = 0
    with _Patch(db, "match_chunks", exact_match):
        for q, g in queries:
            grades = r._grade_filter(g)
            exact = r._supabase_ranked(q, grades, r.TOP_K_PER_RETRIEVER)
            chroma = r._chroma_ranked(q, grades, r.TOP_K_PER_RETRIEVER)
            same_top += exact[:top] == chroma[:top]
            full += exact == chroma
    check(f"identical top-{top} on {same_top} of {len(queries)} queries "
          f"(all {r.TOP_K_PER_RETRIEVER} identical on {full})", same_top == len(queries))


def main() -> None:
    test_front_matter_excluded()
    test_answer_blanks_excluded()
    test_duplicate_pages_pool_and_cite_canonically()
    test_canonical_within_never_crosses_grade_window()
    test_grade_window_still_enforced()
    test_search_path_choice()
    test_exact_search_matches_chroma()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
