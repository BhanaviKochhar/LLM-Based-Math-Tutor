"""eval/component_eval/arithmetic_eval.py — C1-A: trusted-computation
correctness for the arithmetic datasets.

Scores scripts.llm.verifier's computation+gating logic (NOT the LLM
extractor -- see extraction_eval.py for that, which is a separate,
live-LLM-dependent concern) against every item's own pre-recorded
trusted_expression. This is fully deterministic and offline: no API call,
no network.

Datasets scored:
    eval/datasets/arithmetic/v1_starter.jsonl        (15 items)
    eval/datasets/arithmetic/v2_phaseB_extension.jsonl (6 items)

Run:
    python -m eval.component_eval.arithmetic_eval
"""
from __future__ import annotations

import json
from pathlib import Path

from . import results
from .scoring_helpers import (
    RUBRIC_REQUIRED,
    SCORABLE,
    VERIFIED_NOT_SYSTEM_SCORABLE,
    classify_item,
    score_trusted_computation,
)

ROOT = results.ROOT
DATASET_FILES = [
    ROOT / "eval" / "datasets" / "arithmetic" / "v1_starter.jsonl",
    ROOT / "eval" / "datasets" / "arithmetic" / "v2_phaseB_extension.jsonl",
]


def _load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run() -> dict:
    dataset_sources = []
    all_items = []
    for path in DATASET_FILES:
        rows = _load(path)
        dataset_sources.append({
            "path": str(path.relative_to(ROOT)),
            "version": path.stem,
            "item_count": len(rows),
        })
        all_items.extend(rows)

    per_example = []
    exclusions = []
    n_scorable = n_verified_not_scorable = n_rubric = 0
    n_match = n_mismatch = n_error = 0
    by_grade: dict[int, dict] = {}
    by_topic: dict[str, dict] = {}

    for item in all_items:
        cls = classify_item(item)
        grade = item.get("grade")
        topic = item.get("topic", "unknown")
        by_grade.setdefault(grade, {"n_scorable": 0, "match": 0, "excluded": 0})
        by_topic.setdefault(topic, {"n_scorable": 0, "match": 0, "excluded": 0})

        if cls == SCORABLE:
            n_scorable += 1
            by_grade[grade]["n_scorable"] += 1
            by_topic[topic]["n_scorable"] += 1
            outcome = score_trusted_computation(item)
            per_example.append({
                "case_id": item["case_id"], "grade": grade, "topic": topic,
                "classification": cls, **outcome,
            })
            if outcome["outcome"] == "match":
                n_match += 1
                by_grade[grade]["match"] += 1
                by_topic[topic]["match"] += 1
            elif outcome["outcome"] == "mismatch":
                n_mismatch += 1
            else:
                n_error += 1
        elif cls == VERIFIED_NOT_SYSTEM_SCORABLE:
            n_verified_not_scorable += 1
            by_grade[grade]["excluded"] += 1
            by_topic[topic]["excluded"] += 1
            reason = ("verifiable=true but trusted_expression is null -- "
                     "outside the production verifier's current arithmetic "
                     "grammar (e.g. HCF/LCM); ground truth was checked "
                     "directly with sympy at authoring time, not via the "
                     "live system")
            exclusions.append({"case_id": item["case_id"], "reason": reason})
            per_example.append({"case_id": item["case_id"], "grade": grade,
                                "topic": topic, "classification": cls,
                                "outcome": "excluded", "detail": reason})
        else:
            n_rubric += 1
            by_grade[grade]["excluded"] += 1
            by_topic[topic]["excluded"] += 1
            exclusions.append({"case_id": item["case_id"],
                               "reason": "verifiable=false; not a numeric-answer item"})
            per_example.append({"case_id": item["case_id"], "grade": grade,
                                "topic": topic, "classification": cls,
                                "outcome": "excluded",
                                "detail": "not a numeric-answer item"})

    n_total = len(all_items)
    aggregate = {
        "total_items": n_total,
        "system_scorable": n_scorable,
        "verified_not_system_scorable": n_verified_not_scorable,
        "requires_human_rubric_evaluation": n_rubric,
        "answer_accuracy": {
            "numerator_match": n_match,
            "denominator_scorable": n_scorable,
            "rate": round(n_match / n_scorable, 4) if n_scorable else None,
        },
        "parsing_success_rate": {
            "numerator_parsed": n_match + n_mismatch,
            "denominator_scorable": n_scorable,
            "rate": round((n_match + n_mismatch) / n_scorable, 4) if n_scorable else None,
        },
        "mismatches": n_mismatch,
        "errors": n_error,
        "by_grade": {str(k): v for k, v in sorted(by_grade.items(), key=lambda kv: (kv[0] is None, kv[0]))},
        "by_topic": by_topic,
    }

    path = results.write_result(
        "arithmetic_eval",
        dataset_sources=dataset_sources,
        config={"extract_fn": "known-good trusted_expression (bypasses the LLM "
               "extractor by design; see extraction_eval.py for that path)",
               "live_llm_used": False},
        per_example_results=per_example,
        aggregate_metrics=aggregate,
        exclusions=exclusions,
        notes=("This measures the verifier's COMPUTATION+GATING layer given a "
              "KNOWN-CORRECT expression, not end-to-end question-to-answer "
              "accuracy (which requires the LLM extractor -- see "
              "extraction_eval.py). A 'match' can legitimately mean both "
              "sides are None (a correctly withheld non-exact division)."),
    )

    summary = [
        f"# arithmetic_eval — {path.name}",
        "",
        f"Total items: {n_total}",
        f"- system-scorable: {n_scorable}",
        f"- verified but not system-scorable (e.g. HCF/LCM): {n_verified_not_scorable}",
        f"- requires human/rubric evaluation: {n_rubric}",
        "",
        f"Answer accuracy (of system-scorable items): "
        f"{n_match}/{n_scorable} "
        f"({aggregate['answer_accuracy']['rate']})" if n_scorable else "Answer accuracy: n/a",
        f"Mismatches: {n_mismatch}  Errors: {n_error}",
    ]
    results.write_summary_markdown(path, summary)
    return {"result_path": str(path), "aggregate": aggregate}


if __name__ == "__main__":
    out = run()
    print(json.dumps(out["aggregate"], indent=2))
    print(f"\nWrote {out['result_path']}")
