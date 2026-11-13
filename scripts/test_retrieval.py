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


def main() -> None:
    test_front_matter_excluded()
    test_answer_blanks_excluded()
    test_duplicate_pages_pool_and_cite_canonically()
    test_canonical_within_never_crosses_grade_window()
    test_grade_window_still_enforced()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
