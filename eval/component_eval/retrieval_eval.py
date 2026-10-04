"""eval/component_eval/retrieval_eval.py — C2: retrieval scoring.

Deterministic and offline in the sense that matters for cost: BM25 and
ChromaDB are both LOCAL (no network, no API key, no per-call cost) -- only
the one-time sentence-transformers embedding model load touches disk, not
a paid API. This is NOT an LLM evaluation.

Re-runs scripts.retrieval.retrieve_with_metadata LIVE for every query (does
not trust the dataset's own pre-recorded `observed_result` narrative text,
which is a point-in-time snapshot from authoring time) and computes
Recall@1/3/5 and MRR against each query's independently-labelled
`relevant_chunks`.

Categories handled per the task's explicit distinction:
  1. relevant chunk exists, retrieval finds it      -> scored normally
  2. relevant chunk exists, retrieval misses it      -> scored normally (a miss)
  3. no relevant chunk exists / out_of_corpus_topic  -> EXCLUDED from Recall@k
  4. grade_scope_mismatch                            -> EXCLUDED from Recall@k,
                                                         checked separately for
                                                         cross-grade leakage
  5. ambiguous/weak query (NEEDS_REVIEW in notes)    -> scored but flagged,
                                                         not silently dropped

Datasets scored:
    eval/datasets/retrieval/v1_starter.jsonl   (29 queries)
    eval/datasets/retrieval/v2_extended.jsonl  (20 queries)

Run:
    python -m eval.component_eval.retrieval_eval
"""
from __future__ import annotations

import json
from pathlib import Path

from . import results

ROOT = results.ROOT
DATASET_FILES = [
    ROOT / "eval" / "datasets" / "retrieval" / "v1_starter.jsonl",
    ROOT / "eval" / "datasets" / "retrieval" / "v2_extended.jsonl",
]
_NO_GROUND_TRUTH_CATEGORIES = {"grade_scope_mismatch", "out_of_corpus_topic"}
TOP_K = 5


def _load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _is_relevant(chunk_meta: dict, relevant: list[dict]) -> bool:
    key = (chunk_meta.get("grade"), chunk_meta.get("page"))
    return any((r.get("grade"), r.get("page")) == key for r in relevant)


def run() -> dict:
    from scripts.retrieval import retrieve_with_metadata

    dataset_sources, all_items = [], []
    for path in DATASET_FILES:
        rows = _load(path)
        dataset_sources.append({
            "path": str(path.relative_to(ROOT)), "version": path.stem,
            "item_count": len(rows),
        })
        all_items.extend(rows)

    per_example = []
    exclusions = []
    scored = []  # for Recall@k/MRR aggregation
    n_leakage = 0

    for item in all_items:
        qid, query, grade = item["query_id"], item["query"], item["grade"]
        category = item.get("category", "unknown")
        relevant = item.get("relevant_chunks", [])
        needs_review = "NEEDS_REVIEW" in (item.get("ambiguity_notes") or "")

        try:
            top5 = retrieve_with_metadata(query, grade, top_k=TOP_K)
        except Exception as e:
            per_example.append({"query_id": qid, "outcome": "error", "detail": repr(e)})
            continue

        relevant_ranks = [i + 1 for i, c in enumerate(top5) if _is_relevant(c, relevant)]
        first_rank = relevant_ranks[0] if relevant_ranks else None

        if category in _NO_GROUND_TRUTH_CATEGORIES or not relevant:
            reason = (f"category={category!r} or no relevant_chunks labelled -- "
                     "no ground truth to score Recall@k against; this is the "
                     "CORRECT outcome for this category, not a retrieval miss")
            exclusions.append({"query_id": qid, "reason": reason})
            if category == "grade_scope_mismatch":
                # Check for cross-grade leakage: did a chunk from an
                # off-limits (out-of-window) grade appear in the top results?
                window = {grade, grade - 1} if grade > 1 else {grade}
                leaked = [c for c in top5 if c.get("grade") not in window]
                if leaked:
                    n_leakage += 1
                per_example.append({"query_id": qid, "outcome": "excluded",
                                    "category": category,
                                    "cross_grade_leakage": bool(leaked),
                                    "detail": reason})
            else:
                per_example.append({"query_id": qid, "outcome": "excluded",
                                    "category": category, "detail": reason})
            continue

        scored.append(first_rank)
        per_example.append({
            "query_id": qid, "category": category, "needs_review": needs_review,
            "outcome": "hit" if first_rank else "miss",
            "first_relevant_rank": first_rank,
            "top5_grade_page": [(c.get("grade"), c.get("page")) for c in top5],
        })

    n_scored = len(scored)
    def recall_at(k: int) -> float | None:
        if not n_scored:
            return None
        return round(sum(1 for r in scored if r is not None and r <= k) / n_scored, 4)

    mrr = round(sum((1.0 / r) for r in scored if r) / n_scored, 4) if n_scored else None

    aggregate = {
        "total_queries": len(all_items),
        "scored_queries": n_scored,
        "excluded_queries": len(exclusions),
        "recall_at_1": recall_at(1),
        "recall_at_3": recall_at(3),
        "recall_at_5": recall_at(5),
        "mrr": mrr,
        "needs_review_count": sum(1 for r in per_example if r.get("needs_review")),
        "grade_scope_mismatch_cross_grade_leakage_count": n_leakage,
    }

    path = results.write_result(
        "retrieval_eval",
        dataset_sources=dataset_sources,
        config={"retriever": "scripts.retrieval.retrieve_with_metadata (BM25 + "
               "ChromaDB, local, no LLM/API call)", "top_k": TOP_K,
               "live_llm_used": False},
        per_example_results=per_example,
        aggregate_metrics=aggregate,
        exclusions=exclusions,
        notes=("Recall@k/MRR exclude grade_scope_mismatch/out_of_corpus_topic "
              "queries and any query with no labelled relevant_chunks, per the "
              "dataset's own documented scoring convention "
              "(docs/evaluation_dataset_schema.md). A retrieval miss here is a "
              "retrieval-component finding only -- it does not imply the "
              "generated tutoring response was wrong, and a hit does not prove "
              "the eventual generation was grounded in that chunk."),
    )
    summary = [
        f"# retrieval_eval — {path.name}",
        "",
        f"Scored queries: {n_scored} / {len(all_items)} "
        f"({len(exclusions)} excluded -- no ground truth to score, by design)",
        f"Recall@1: {aggregate['recall_at_1']}  Recall@3: {aggregate['recall_at_3']}  "
        f"Recall@5: {aggregate['recall_at_5']}  MRR: {mrr}",
        f"Grade-scope-mismatch cross-grade leakage: {n_leakage} "
        f"(should be 0 -- any >0 is a real grade-filter defect)",
    ]
    results.write_summary_markdown(path, summary)
    return {"result_path": str(path), "aggregate": aggregate}


if __name__ == "__main__":
    out = run()
    print(json.dumps(out["aggregate"], indent=2))
    print(f"\nWrote {out['result_path']}")
