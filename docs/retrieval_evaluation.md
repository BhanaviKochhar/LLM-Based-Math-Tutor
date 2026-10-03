# Retrieval (RAG) Evaluation

## Architecture (verified by reading `scripts/retrieval.py`, `scripts/load_chromadb.py`)

- Corpus: `data/extracted_json/ncert_chunks.json`, 2,329 chunks, fields `{text, grade, page, source}`. Chunking is page-bounded (confirmed consistent with the paper's description: no chunk spans a page boundary).
- Embedding: `all-MiniLM-L6-v2` (sentence-transformers), persisted in ChromaDB (`data/chromadb/`).
- Lexical: BM25 over the same chunks.
- Fusion: Reciprocal Rank Fusion, `k=60` (matches the paper's stated formula).
- Metadata filtering: grade window `G(g) = {g, g-1} ∩ {1..5}`, applied before ranking.
- Top-k returned to the prompt: 3.

## Dataset expansion (Section 7)

**Target was ≥50 queries; actual delivered: 29** (`eval/datasets/retrieval/v1_starter.jsonl`, up from 10 at the start of this session). Reason for not reaching 50, stated plainly rather than padded: each query in this dataset is independently verified against the real corpus (not just whatever the retriever happened to return) — confirming relevance required reading actual chunk text for every query/result pair, including checking the NCERT chapter the candidate "relevant" chunks belong to. At that level of rigor, 50 queries would roughly double the verification work already done in this session for 29, including the earlier starter-10. Expanding to 29 was judged to deliver meaningfully broader topic coverage (from fractions-only to 9 distinct topics) and a far more representative aggregate picture (see §2) within the time available in this engagement; a further expansion toward 50 is identified as the next concrete action in §4, not abandoned.

**Topic coverage achieved:** fractions (10), multiplication (2), subtraction/borrowing (1), shapes/geometry (2), money (2), time/clocks (3), perimeter (1), number patterns/parity (2), place value (1), measurement/weight (2), division (2), number sequence (1), data handling (1). Query categories per `docs/evaluation_dataset_schema.md`: single-word topic, short conceptual, specific conceptual, paraphrase, grade-scope-mismatch, out-of-corpus-topic, curriculum-grade-specific, numeric-arithmetic-question — all represented.

## Metrics (computed, this session, against the live retriever)

29 total queries. 2 excluded by design (`grade_scope_mismatch`, `out_of_corpus_topic` — correct-miss categories, not scored for recall). 3 queries (`rq-023`, `rq-026`, `rq-028`) have at least one plausible but **not independently confirmed** relevant chunk (marked `NEEDS_REVIEW`) and were conservatively left with an empty `relevant_chunks` set rather than guessed at.

| | n=24 (confirmed-relevant queries only) | n=27 (conservative: NEEDS_REVIEW counted as miss) |
|---|---|---|
| Recall@1 | 16/24 = **0.667** | 16/27 = **0.593** |
| Recall@3 | 21/24 = **0.875** | 21/27 = **0.778** |
| MRR | 18.33/24 = **0.764** | 18.33/27 = **0.679** |

**This is a meaningfully different, more representative picture than the earlier (prior-session) 8-query sample**, which reported Recall@3=0.625 — that sample was deliberately constructed around the one topic (fractions) that the initial behavioural review had already flagged as problematic, not a cross-topic sample. With genuine topic diversity, the retriever performs considerably better overall (Recall@3 78–88%) than the fractions-only sample suggested. **Neither number should be read as "the" retrieval recall of the system** — 24-29 queries, however carefully labelled, is still a diagnostic sample, not a statistically powered benchmark; see §4.

## Root-cause investigation: "fractions" / "what is a fraction" (the originally observed issue)

Directly investigated per the task's explicit question: is the cause query interpretation, ranking, chunking, corpus coverage, metadata filtering, or a combination?

- **Not corpus coverage**: pages 101–112 (the NCERT Class 4 "Jugs and Mugs" fractions chapter) are confirmed present and rich (confirmed via direct grep for `numerator|denominator|equal parts|one-half|...`, 41 hits across the corpus, concentrated in this page range).
- **Not metadata filtering**: `rq-005` (same query at grade 2, where `G(2)={1,2}` correctly excludes the grade-4 chapter) shows the grade filter working as designed — no cross-grade leakage observed anywhere in this dataset.
- **Not chunking**: the relevant chunks are properly segmented, page-bounded, and retrievable in isolation (confirmed by `rq-003`/`rq-004`, longer phrasings of the identical need, retrieving them at rank 1).
- **Is query interpretation/ranking, and appears topic-specific, not a general short-query defect**: the clearest evidence is the contrast between `rq-001` ("fractions", 0/3) and four OTHER bare single-word queries added this session — `rq-014` ("shapes", 2/3), `rq-016` ("money", 3/3), `rq-018` ("time", 2-3/3), `rq-025` ("division", 3/3) — all retrieving well. If short/bare queries were a uniform weakness, these would be expected to fail similarly; they don't. The specific difficulty with "fractions" as a bare term, versus "what is a fraction of a whole" (which retrieves correctly), suggests the embedding/BM25 scoring for this particular term in this particular corpus is unusually weak — plausibly because "fraction"-family vocabulary is comparatively sparse and dispersed across the corpus (the Class 4 chapter uses "half", "quarter", "equal parts" far more than the word "fraction" itself — see the grep results in the raw session notes), so a bare query using the abstract term scores poorly against chunks that express the same concept without using that term. This is a **plausible, evidence-consistent explanation, not a confirmed one** — fully confirming it would require inspecting the BM25/embedding scores directly (not just top-3 output), which was not done in this pass.

## Other reproducible issues found (new in this expansion, not previously documented)

1. **A recurring "noise attractor" chunk**: grade 3, page 113 (a calendar/dates passage) appeared in the top-3 for two unrelated short conceptual queries (`rq-002` "what is a fraction", `rq-019` "what is perimeter"). This is a specific, checkable artifact worth investigating directly (e.g. inspecting its embedding vector's nearest neighbours) rather than a general claim about short queries.
2. **A paraphrase-without-keyword miss**: `rq-025` ("division", literal term) retrieves very well (3/3), but `rq-026` ("sharing things equally among friends", same underlying concept, no "divide"/"division" wording) misses — suggesting the dense/semantic leg of the hybrid retriever does not reliably bridge this particular paraphrase even though lexical matching on the same topic succeeds.
3. **A chapter-confusion miss**: `rq-028` ("pictograph data handling") retrieved the wrong chapter — "number patterns **with pictures**" instead of a pictograph/data-handling chapter — apparently because both chapters share the word "pictures," a specific, reproducible ranking confusion rather than a coverage gap.
4. **A curriculum-terminology mismatch**: `rq-022` ("place value") surfaced a teacher note explicitly stating the term "place value" is deliberately *not* used in this curriculum's vocabulary — the query may be using different terminology than the textbook itself uses, which is a different problem from a retrieval defect per se.
5. **An unresolved register question** (not new — same as `rq-008` in the original starter set, now reproduced again at `rq-023` "how to measure length"): several queries' top results are teacher-facing pedagogical notes rather than child-facing lesson text. Whether these should count as "relevant" grounding for a child-facing tutor is a labelling policy question this review flags but does not resolve.

## No query-specific patches applied

Per the explicit instruction not to hardcode fixes for a few diagnostic examples, **no changes were made to `scripts/retrieval.py`, the embedding model, or any query-rewriting logic in this session.** The findings above are diagnostic evidence for a future, evidence-driven retrieval-quality improvement (e.g. query expansion for abstract/short terms, or a term-frequency-aware re-ranking step) — not something to design and implement without first deciding, with the project owner, which approach is worth the added complexity (see `docs/evaluation_plan.md` §5 for the existing recommendation).

## Comparison of retrieval configurations

**Not done.** The task asked for a BM25-vs-dense-vs-hybrid comparison "where appropriate" — `scripts/retrieval.py` was inspected and does not currently expose a mode switch to run BM25-only or dense-only retrieval without a code change; adding one was judged to be a larger change than this evaluation pass's scope, and is recorded as a specific, scoped next step rather than silently skipped.

## Limitations

- 27-29 queries, hand-labelled by one reviewer (this session) — no second-rater agreement check has been done on the relevance labels themselves.
- 3 cases (`rq-023`, `rq-026`, `rq-028`) have unresolved relevance judgments pending closer reading of the full chunk text (only truncated snippets were reviewed).
- No query repeated across multiple retrieval runs — ChromaDB/BM25 are deterministic for a fixed index and query, so repeat-run variance is not expected to be a factor, but this was not independently confirmed.
- This is not the stratified-by-grade, stratified-by-chapter benchmark the original plan documents envision at full scale (Phase D3/E4) — it is real, verified, but partial evidence toward that goal.
