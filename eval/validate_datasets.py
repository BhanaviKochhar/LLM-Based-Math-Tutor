"""eval/validate_datasets.py — structural validation for eval/datasets/*.

Checks the rules in docs/evaluation_dataset_schema.md: required fields,
unique IDs, and cross-references (retrieval chunk citations against the real
corpus; conceptual rubric-dimension names against docs/evaluation_plan.md).

Does NOT validate subjective content (relevance judgements, rubric scores) --
that is a manual review responsibility. This only catches structural defects:
missing fields, duplicate IDs, and invalid cross-references.

Run:  python -m eval.validate_datasets
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "eval" / "datasets"

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


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise AssertionError(f"{path}:{i} invalid JSON: {e}") from e
    return rows


def _unique_ids(rows: list[dict], field: str) -> bool:
    ids = [r.get(field) for r in rows]
    return len(ids) == len(set(ids)) and all(ids)


# --------------------------------------------------------------- arithmetic
def test_arithmetic() -> None:
    print("arithmetic/v1_starter.jsonl")
    path = DATASETS / "arithmetic" / "v1_starter.jsonl"
    rows = _load_jsonl(path)
    check("at least 10 cases", len(rows) >= 10)
    check("case_id unique", _unique_ids(rows, "case_id"))
    required = {"case_id", "question", "grade", "topic", "expected_answer",
               "accepted_equivalents", "trusted_expression",
               "required_assumptions", "verifiable", "verification_notes",
               "provenance"}
    missing = [r["case_id"] for r in rows if not required.issubset(r)]
    check("all required fields present", not missing)
    bad_null = [r["case_id"] for r in rows
               if (r["expected_answer"] is None) != (r["verifiable"] is False)]
    check("expected_answer is null iff verifiable is false", not bad_null)

    from scripts.llm import verifier
    bad_expr = []
    for r in rows:
        if r["trusted_expression"] is not None:
            if verifier._safe_eval(r["trusted_expression"]) is None:
                bad_expr.append(r["case_id"])
    check("every non-null trusted_expression parses under verifier._safe_eval",
         not bad_expr)
    if bad_expr:
        print("    failing:", bad_expr)


# --------------------------------------------------------------- extraction
def test_extraction() -> None:
    print("extraction/v1_starter.jsonl")
    path = DATASETS / "extraction" / "v1_starter.jsonl"
    rows = _load_jsonl(path)
    check("at least 10 cases", len(rows) >= 10)
    check("case_id unique", _unique_ids(rows, "case_id"))
    check("stage is a known value",
         all(r.get("stage") in ("question_to_expression", "response_to_answer")
            for r in rows))
    s1 = [r for r in rows if r["stage"] == "question_to_expression"]
    s2 = [r for r in rows if r["stage"] == "response_to_answer"]
    check("question_to_expression rows have expected_expression key",
         all("expected_expression" in r for r in s1))
    check("response_to_answer rows have expected_final_answer key",
         all("expected_final_answer" in r for r in s2))


# --------------------------------------------------------------- retrieval
def test_retrieval() -> None:
    print("retrieval/v1_starter.jsonl")
    path = DATASETS / "retrieval" / "v1_starter.jsonl"
    rows = _load_jsonl(path)
    check("at least 8 queries", len(rows) >= 8)
    check("query_id unique", _unique_ids(rows, "query_id"))

    with open(ROOT / "data" / "extracted_json" / "ncert_chunks.json", encoding="utf-8") as f:
        corpus = json.load(f)
    real_pages = {(c.get("grade"), c.get("page")) for c in corpus}

    bad_refs = []
    for r in rows:
        for ch in r.get("relevant_chunks", []):
            if (ch.get("grade"), ch.get("page")) not in real_pages:
                bad_refs.append((r["query_id"], ch))
    check("every cited (grade, page) exists in the real corpus", not bad_refs)
    if bad_refs:
        print("    failing:", bad_refs)

    scope_mismatch_empty = all(
        not r["relevant_chunks"]
        for r in rows if r["category"] in ("grade_scope_mismatch", "out_of_corpus_topic")
    )
    check("grade_scope_mismatch / out_of_corpus_topic categories have no relevant_chunks",
         scope_mismatch_empty)


# --------------------------------------------------------------- controller
def test_controller() -> None:
    print("controller/v1_scenarios.json")
    path = DATASETS / "controller" / "v1_scenarios.json"
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    rows = doc["scenarios"]
    check("at least 15 scenarios", len(rows) >= 15)
    check("scenario_id unique", _unique_ids(rows, "scenario_id"))

    missing_ref = []
    for r in rows:
        ref = r["test_reference"]
        if ref.startswith("none"):
            continue
        file_part = ref.split(":")[0].strip()
        if file_part.startswith("manual"):
            continue
        if not (ROOT / file_part).exists():
            missing_ref.append((r["scenario_id"], file_part))
    check("every referenced test file exists", not missing_ref)
    if missing_ref:
        print("    failing:", missing_ref)


# --------------------------------------------------------------- conceptual
_RUBRIC_DIMENSIONS = {
    "mathematical_correctness", "relevance_to_latest_input",
    "recognition_of_demonstrated_reasoning", "appropriate_scaffolding",
    "context_preservation", "clarity_and_age_appropriateness",
    "avoidance_of_unnecessary_repetition", "appropriate_progression",
}


def test_conceptual() -> None:
    print("conceptual/v1_starter.jsonl")
    path = DATASETS / "conceptual" / "v1_starter.jsonl"
    rows = _load_jsonl(path)
    check("at least 8 cases", len(rows) >= 8)
    check("case_id unique", _unique_ids(rows, "case_id"))
    bad_dims = []
    for r in rows:
        for d in r.get("rubric_dimensions_most_relevant", []):
            if d not in _RUBRIC_DIMENSIONS:
                bad_dims.append((r["case_id"], d))
    check("rubric_dimensions_most_relevant values are all known dimensions",
         not bad_dims)
    if bad_dims:
        print("    failing:", bad_dims)


# --------------------------------------------------------------- multi_turn
def test_multi_turn() -> None:
    print("multi_turn/v1_starter.json")
    path = DATASETS / "multi_turn" / "v1_starter.json"
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    convs = doc["conversations"]
    check("at least 5 conversations", len(convs) >= 5)
    check("conversation_id unique", _unique_ids(convs, "conversation_id"))

    bad_order = []
    for c in convs:
        nums = [t["turn"] for t in c["turns"]]
        if nums != sorted(nums) or nums != list(range(1, len(nums) + 1)):
            bad_order.append(c["conversation_id"])
    check("turn numbers are 1..N in order within each conversation", not bad_order)
    if bad_order:
        print("    failing:", bad_order)


def main() -> None:
    test_arithmetic()
    test_extraction()
    test_retrieval()
    test_controller()
    test_conceptual()
    test_multi_turn()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
