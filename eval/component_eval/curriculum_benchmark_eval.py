"""eval/component_eval/curriculum_benchmark_eval.py — C1-A (curriculum
benchmark variant): trusted-computation scoring for the 175-item Class 1-5
curriculum benchmark.

Deterministic and offline, like arithmetic_eval.py -- same
system_scorable / verified_not_system_scorable / requires_human_rubric
classification (see scoring_helpers.py for the documented resolution of the
verifiable-vs-system-scorable terminology question). Kept as a SEPARATE
runner from arithmetic_eval.py (not merged) because the curriculum
benchmark's item mix is fundamentally different: 60% numeric, 40%
conceptual/comparison/real-life items that must be preserved for a later
rubric-based evaluation pass, not discarded, and its own per-class /
per-question-type / per-topic breakdowns are a distinct, explicitly
requested reporting need.

Run:
    python -m eval.component_eval.curriculum_benchmark_eval
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
    ROOT / "eval" / "datasets" / "curriculum_benchmark" / f"v1_class{g}.jsonl"
    for g in range(1, 6)
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
            "path": str(path.relative_to(ROOT)), "version": path.stem,
            "item_count": len(rows),
        })
        all_items.extend(rows)

    per_example = []
    exclusions = []
    rubric_queue = []  # preserved for a later rubric-evaluation pass, not discarded
    n_scorable = n_verified_not_scorable = n_rubric = 0
    n_match = n_mismatch = n_error = 0
    by_grade: dict[int, dict] = {}
    by_qtype: dict[str, dict] = {}

    for item in all_items:
        cls = classify_item(item)
        grade = item.get("grade")
        qtype = item.get("question_type", "unknown")
        by_grade.setdefault(grade, {"n_scorable": 0, "match": 0, "excluded": 0})
        by_qtype.setdefault(qtype, {"n_scorable": 0, "match": 0, "excluded": 0})

        if cls == SCORABLE:
            n_scorable += 1
            by_grade[grade]["n_scorable"] += 1
            by_qtype[qtype]["n_scorable"] += 1
            outcome = score_trusted_computation(item)
            per_example.append({
                "case_id": item["case_id"], "grade": grade,
                "curriculum_topic": item.get("curriculum_topic"),
                "question_type": qtype, "classification": cls, **outcome,
            })
            if outcome["outcome"] == "match":
                n_match += 1
                by_grade[grade]["match"] += 1
                by_qtype[qtype]["match"] += 1
            elif outcome["outcome"] == "mismatch":
                n_mismatch += 1
            else:
                n_error += 1
        else:
            by_grade[grade]["excluded"] += 1
            by_qtype[qtype]["excluded"] += 1
            if cls == VERIFIED_NOT_SYSTEM_SCORABLE:
                n_verified_not_scorable += 1
                reason = ("verifiable=true but trusted_expression is null -- "
                         "outside the production verifier's current "
                         "arithmetic grammar (e.g. HCF/LCM)")
            else:
                n_rubric += 1
                reason = "verifiable=false; requires human/rubric evaluation, not discarded"
                rubric_queue.append({
                    "case_id": item["case_id"], "grade": grade,
                    "curriculum_topic": item.get("curriculum_topic"),
                    "question_type": qtype,
                    "question": item.get("question"),
                    "expected_key_idea": item.get("expected_key_idea"),
                })
            exclusions.append({"case_id": item["case_id"], "reason": reason})
            per_example.append({"case_id": item["case_id"], "grade": grade,
                                "curriculum_topic": item.get("curriculum_topic"),
                                "question_type": qtype, "classification": cls,
                                "outcome": "excluded", "detail": reason})

    n_total = len(all_items)
    aggregate = {
        "total_items": n_total,
        "system_scorable": n_scorable,
        "verified_not_system_scorable": n_verified_not_scorable,
        "requires_human_rubric_evaluation": n_rubric,
        "answer_accuracy": {
            "numerator_match": n_match, "denominator_scorable": n_scorable,
            "rate": round(n_match / n_scorable, 4) if n_scorable else None,
        },
        "mismatches": n_mismatch,
        "errors": n_error,
        "by_grade": {str(k): v for k, v in sorted(by_grade.items())},
        "by_question_type": by_qtype,
        "rubric_queue_size": len(rubric_queue),
    }

    path = results.write_result(
        "curriculum_benchmark_eval",
        dataset_sources=dataset_sources,
        config={"extract_fn": "known-good trusted_expression (bypasses the LLM "
               "extractor); see extraction_eval.py for the live-extraction path",
               "live_llm_used": False},
        per_example_results=per_example,
        aggregate_metrics=aggregate,
        exclusions=exclusions,
        notes=(f"{n_rubric} rubric/conceptual items are preserved in a separate "
              f"rubric_queue artifact (see rubric_queue_path below), not scored "
              f"and not discarded, pending a future rubric/human-evaluation pass."),
    )

    # Preserve the rubric-required items as their own artifact, per the task's
    # explicit instruction not to throw these away.
    queue_path = path.with_name(path.stem + "_rubric_queue.json")
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump({"source_result": path.name, "items": rubric_queue}, f,
                  indent=2, ensure_ascii=False)

    summary = [
        f"# curriculum_benchmark_eval — {path.name}",
        "",
        f"Total items: {n_total}",
        f"- system-scorable: {n_scorable}",
        f"- verified but not system-scorable: {n_verified_not_scorable}",
        f"- requires human/rubric evaluation (preserved, see {queue_path.name}): {n_rubric}",
        "",
        f"Answer accuracy (of system-scorable items): {n_match}/{n_scorable} "
        f"({aggregate['answer_accuracy']['rate']})" if n_scorable else "n/a",
        f"Mismatches: {n_mismatch}  Errors: {n_error}",
    ]
    results.write_summary_markdown(path, summary)
    return {"result_path": str(path), "rubric_queue_path": str(queue_path),
           "aggregate": aggregate}


if __name__ == "__main__":
    out = run()
    print(json.dumps(out["aggregate"], indent=2))
    print(f"\nWrote {out['result_path']}")
    print(f"Wrote {out['rubric_queue_path']}")
