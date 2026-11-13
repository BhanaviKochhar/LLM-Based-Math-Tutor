"""eval/retrieval_ablation.py -- the standard information-retrieval measures for
the tutor's retriever, and the same measures with one part of it removed.

Variants (all run locally: BM25 and the ChromaDB embedding model, no API):
  hybrid           the production retriever: BM25 + dense, RRF (k = 60), classes G(g)
  bm25_only        BM25 alone, classes G(g)
  dense_only       dense (all-MiniLM-L6-v2 in ChromaDB) alone, classes G(g)
  hybrid_all_classes  BM25 + dense, RRF, no class filter (all five books)

Queries and relevance labels: eval/datasets/retrieval.jsonl, the 88 queries
with labelled relevant pages (the other 12 have no ground truth by design).
Relevance is labelled per (class, page); a retrieved chunk is relevant if it
sits on a labelled page or is the same passage as one (the corpus repeats some
pages verbatim; see eval/component_eval/retrieval_eval.py).

Measures, for k = 1, 3, 5, 10 (the tutor uses the top 3):
  Hit@k        1 if any relevant chunk is in the top k (what retrieval_eval calls Recall@k)
  Recall@k     share of the query's labelled relevant pages found in the top k
  Precision@k  relevant chunks in the top k / k
  nDCG@k       DCG@k / IDCG@k, DCG = sum rel_i / log2(i + 1), binary relevance;
               IDCG uses min(R, k) relevant chunks, R = relevant chunks in the corpus
  AP@k         (1 / min(R, k)) * sum over relevant ranks i <= k of Precision@i
  MRR          mean 1 / rank of the first relevant chunk (0 if none in the top 10)
Cross-class leakage: queries with a top-3 chunk outside G(g), over the scored
queries and the wrong-class queries.

Run:  python -m eval.retrieval_ablation
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

from eval.component_eval.results import write_result, write_summary_markdown
from eval.component_eval.retrieval_eval import _NO_GROUND_TRUTH_CATEGORIES, _page_canonical_groups
from scripts import retrieval as R

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "eval" / "datasets" / "retrieval.jsonl"
KS = (1, 3, 5, 10)
TOP = max(KS)
ALL_CLASSES = (1, 2, 3, 4, 5)
VARIANTS = ("hybrid", "bm25_only", "dense_only", "hybrid_all_classes")


def ranked(variant: str, query: str, grade: int) -> list[int]:
    grades = ALL_CLASSES if variant == "hybrid_all_classes" else R._grade_filter(grade)
    if variant == "bm25_only":
        return R._bm25_ranked(query, grades, R.TOP_K_PER_RETRIEVER)[:TOP]
    if variant == "dense_only":
        return R._chroma_ranked(query, grades, R.TOP_K_PER_RETRIEVER)[:TOP]
    bm25 = R._bm25_ranked(query, grades, R.TOP_K_PER_RETRIEVER)
    dense = R._chroma_ranked(query, grades, R.TOP_K_PER_RETRIEVER)
    return R._rrf_fuse([bm25, dense])[:TOP]


class Relevance:
    """Relevance of a chunk to one query's labelled pages, with the corpus's
    verbatim duplicate pages counted as the same passage."""

    def __init__(self) -> None:
        self.chunks = R._load_chunks()
        self.groups = _page_canonical_groups()
        self.content = R._content_indices()

    def matches(self, i: int, page: tuple) -> bool:
        c = self.chunks[i]
        key = (c["grade"], c["page"])
        return key == page or bool(self.groups.get(key, set()) & self.groups.get(page, set()))

    def query(self, relevant: list[dict]) -> tuple[list[tuple], int]:
        pages = [(r["grade"], r["page"]) for r in relevant]
        n_rel = sum(1 for i in self.content if any(self.matches(i, p) for p in pages))
        return pages, n_rel


def score(top: list[int], pages: list[tuple], n_rel: int, rel: Relevance) -> dict:
    flags = [any(rel.matches(i, p) for p in pages) for i in top]
    out = {}
    for k in KS:
        f = flags[:k]
        found = {p for p in pages if any(rel.matches(i, p) for i in top[:k])}
        dcg = sum(1 / math.log2(r + 2) for r, x in enumerate(f) if x)
        idcg = sum(1 / math.log2(r + 2) for r in range(min(n_rel, k)))
        hits, ap = 0, 0.0
        for r, x in enumerate(f):
            if x:
                hits += 1
                ap += hits / (r + 1)
        out[k] = {"hit": float(any(f)), "recall": len(found) / len(pages), "precision": sum(f) / k,
                  "ndcg": dcg / idcg if idcg else 0.0, "ap": ap / min(n_rel, k) if n_rel else 0.0}
    first = next((r + 1 for r, x in enumerate(flags) if x), None)
    out["rr"] = 1 / first if first else 0.0
    out["first_rank"] = first
    return out


def mean_block(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    agg = {"n": len(rows), "mrr": float(np.mean([r["rr"] for r in rows]))}
    for k in KS:
        for m in ("hit", "recall", "precision", "ndcg", "ap"):
            agg[f"{m}@{k}"] = float(np.mean([r[k][m] for r in rows]))
    return agg


def run() -> dict:
    items = [json.loads(l) for l in open(DATASET, encoding="utf-8") if l.strip().startswith("{")]
    rel = Relevance()
    per_query, leakage = [], {v: {"queries": 0, "leaked": 0} for v in VARIANTS}
    for it in items:
        q, g, cat = it["query"], it["grade"], it.get("category", "unknown")
        window = set(R._grade_filter(g))
        scored = cat not in _NO_GROUND_TRUTH_CATEGORIES and bool(it.get("relevant_chunks"))
        row = {"query_id": it["query_id"], "grade": g, "category": cat, "scored": scored, "variants": {}}
        pages, n_rel = rel.query(it.get("relevant_chunks") or []) if scored else ([], 0)
        for v in VARIANTS:
            top = ranked(v, q, g)
            if scored or cat == "grade_scope_mismatch":
                leakage[v]["queries"] += 1
                leakage[v]["leaked"] += any(rel.chunks[i]["grade"] not in window for i in top[:3])
            if scored:
                row["variants"][v] = score(top, pages, n_rel, rel)
        row["n_relevant_chunks"] = n_rel
        per_query.append(row)

    scored_rows = [r for r in per_query if r["scored"]]
    agg = {"queries_scored": len(scored_rows), "queries_total": len(per_query), "variants": {}}
    for v in VARIANTS:
        rows = [r["variants"][v] for r in scored_rows]
        block = mean_block(rows)
        block["cross_class_leakage"] = leakage[v]
        if v != "hybrid":
            a = [r["variants"]["hybrid"][3]["ndcg"] for r in scored_rows]
            b = [r["variants"][v][3]["ndcg"] for r in scored_rows]
            d = [x - y for x, y in zip(a, b)]
            block["ndcg@3_vs_hybrid_wilcoxon_p"] = float(wilcoxon(a, b).pvalue) if any(d) else 1.0
        agg["variants"][v] = block
    for field in ("grade", "category"):
        groups = defaultdict(list)
        for r in scored_rows:
            groups[r[field]].append(r["variants"]["hybrid"])
        agg[f"hybrid_by_{field}"] = {str(k): mean_block(v) for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))}
    return {"aggregate": agg, "per_query": per_query}


def main() -> None:
    res = run()
    agg = res["aggregate"]
    lines = ["# Retrieval: standard measures and variants", "",
             f"{agg['queries_scored']} scored queries of {agg['queries_total']}.", "",
             "| Variant | Hit@3 | Recall@3 | Precision@3 | nDCG@3 | MAP@3 | MRR | nDCG@10 | leakage (top 3) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for v, b in agg["variants"].items():
        lk = b["cross_class_leakage"]
        lines.append(f"| {v} | {b['hit@3']:.3f} | {b['recall@3']:.3f} | {b['precision@3']:.3f} | {b['ndcg@3']:.3f} | "
                     f"{b['ap@3']:.3f} | {b['mrr']:.3f} | {b['ndcg@10']:.3f} | {lk['leaked']}/{lk['queries']} |")
    lines += ["", "Hybrid by class: " + ", ".join(f"{g}: nDCG@3 {b['ndcg@3']:.2f}, Hit@1 {b['hit@1']:.2f} (n={b['n']})"
                                                 for g, b in agg["hybrid_by_grade"].items())]
    print("\n".join(lines))
    path = write_result("retrieval_ablation", dataset_sources=[{"path": str(DATASET.relative_to(ROOT))}],
                        config={"variants": list(VARIANTS), "ks": list(KS), "rrf_k": R.RRF_K,
                                "candidates_per_retriever": R.TOP_K_PER_RETRIEVER},
                        per_example_results=res["per_query"], aggregate_metrics=agg)
    write_summary_markdown(path, lines)
    print(f"\nRaw: {path}")


if __name__ == "__main__":
    main()
