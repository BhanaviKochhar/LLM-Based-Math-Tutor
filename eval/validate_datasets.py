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


# ------------------------------------------------------- arithmetic v2 (Phase B)
def test_arithmetic_v2_phaseb() -> None:
    """eval/datasets/arithmetic/v2_phaseB_extension.jsonl -- a modest,
    separately-versioned addition to v1_starter.jsonl (Class 1 and Class 5
    coverage-gap items; see docs/curriculum_coverage_matrix.md). Kept in its
    own file rather than appended to v1_starter.jsonl, per the versioning
    rule in docs/evaluation_dataset_schema.md: v1_starter.jsonl's exact
    content is cited by docs/extraction_evaluation.md and
    docs/retrieval_evaluation.md's prior results and must not change under
    them."""
    print("arithmetic/v2_phaseB_extension.jsonl")
    path = DATASETS / "arithmetic" / "v2_phaseB_extension.jsonl"
    rows = _load_jsonl(path)
    check("at least 1 case", len(rows) >= 1)
    check("case_id unique within this file", _unique_ids(rows, "case_id"))

    v1_rows = _load_jsonl(DATASETS / "arithmetic" / "v1_starter.jsonl")
    v1_ids = {r["case_id"] for r in v1_rows}
    v2_ids = {r["case_id"] for r in rows}
    check("no case_id collides with v1_starter.jsonl (IDs are never reused)",
         not (v1_ids & v2_ids))

    required = {"case_id", "question", "grade", "topic", "expected_answer",
               "accepted_equivalents", "trusted_expression",
               "required_assumptions", "verifiable", "verification_notes",
               "provenance", "review_status"}
    missing = [r["case_id"] for r in rows if not required.issubset(r)]
    check("all required fields present (including the Phase B review_status field)",
         not missing)
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

    bad_grade = [r["case_id"] for r in rows if not (1 <= r.get("grade", 0) <= 5)]
    check("grade is 1-5", not bad_grade)


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


# --------------------------------------------------------------- out_of_scope
def test_out_of_scope() -> None:
    """eval/datasets/out_of_scope/v1_starter.jsonl -- deliberately NOT mixed
    into the in-scope arithmetic/extraction accuracy datasets (B4): it tests
    scope recognition and honest refusal, not primary-curriculum correctness.
    A category-specific schema, not the arithmetic one -- these items have no
    'expected_answer' to verify, by design."""
    print("out_of_scope/v1_starter.jsonl")
    path = DATASETS / "out_of_scope" / "v1_starter.jsonl"
    rows = _load_jsonl(path)
    check("at least 10 cases", len(rows) >= 10)
    check("case_id unique", _unique_ids(rows, "case_id"))
    check("case_id uses the oos- prefix (never collides with in-scope ar-/ex-/rq-/ctl-/co-/mt- IDs)",
         all(r["case_id"].startswith("oos-") for r in rows))
    required = {"case_id", "question", "out_of_scope_topic", "out_of_scope_reason",
               "boundary_case", "expected_behavior", "must_avoid", "provenance",
               "review_status"}
    missing = [r["case_id"] for r in rows if not required.issubset(r)]
    check("all required fields present", not missing)
    check("this file lives in its own directory, never eval/datasets/arithmetic/ "
         "or eval/datasets/extraction/ (out-of-scope items must not be mixed "
         "into in-scope accuracy datasets)",
         path.parent.name == "out_of_scope")
    not_curriculum_topics = [
        "algebra", "quadratic", "calculus", "trigonometry", "complex number",
        "logarithm", "matri", "permutation", "combination", "limit", "vector",
        "factorial",
    ]
    bad_topic = [r["case_id"] for r in rows
                if not any(t in r["out_of_scope_topic"].lower() for t in not_curriculum_topics)]
    check("out_of_scope_topic names a recognised beyond-Class-1-5 concept",
         not bad_topic)
    if bad_topic:
        print("    failing (topic string didn't match the known out-of-scope list):", bad_topic)


# ----------------------------------------------- curriculum_benchmark (B)
# The authoritative taxonomy from docs/verified_ncert_class_1_5_topics.md,
# copied here ONLY as a validation lookup -- the source-of-truth document
# itself is never modified by this validator.
_CURRICULUM_TAXONOMY = {
    1: {"Shapes & Spatial Understanding", "Numbers 1 to 9",
        "Addition & Subtraction (1 to 9)", "Numbers 10 to 20", "Patterns",
        "Measurement", "Data Handling & Money"},
    2: {"Shapes & Spatial Geometry", "Numbers up to 100",
        "Addition & Subtraction (Up to 99)",
        "Measurement (Length, Weight, Capacity)", "Time & Calendar",
        "Data Handling & Patterns"},
    3: {"Numbers up to 1000", "Addition & Subtraction with Regrouping",
        "Multiplication (Basic)", "Division (Introduction)",
        "Shapes, 2D Nets & Symmetry", "Measurement (Standard Units)",
        "Time & Money"},
    4: {"Numbers up to 100,000", "Multiplication & Division", "Fractions",
        "Geometry & Circles", "Perimeter & Area",
        "Metric Conversions & Time", "Data Handling"},
    5: {"Large Numbers & Operations", "Shapes & Angles",
        "Symmetry & Rotations", "Factors & Multiples",
        "Fractions & Decimals", "Area, Perimeter & Volume",
        "Data & Mapping Skills"},
}
_QUESTION_TYPES = {
    "direct_numerical", "word_problem", "paraphrased", "conceptual",
    "real_life", "multi_step", "misconception", "comparison", "ambiguous",
}


def test_curriculum_benchmark() -> None:
    """eval/datasets/curriculum_benchmark/v1_class{1..5}.jsonl -- the main
    custom Class 1-5 benchmark. Validates against the authoritative
    taxonomy (docs/verified_ncert_class_1_5_topics.md, copied read-only
    into _CURRICULUM_TAXONOMY above) and independently re-verifies every
    numeric item's trusted_expression against its expected_answer, rather
    than trusting the authoring-time claim."""
    print("curriculum_benchmark/v1_class1..5.jsonl")
    from scripts.llm import verifier

    all_rows = []
    for grade in range(1, 6):
        path = DATASETS / "curriculum_benchmark" / f"v1_class{grade}.jsonl"
        rows = _load_jsonl(path)
        for r in rows:
            r["_file_grade"] = grade
        all_rows.extend(rows)

    check("at least 100 items across all 5 class files", len(all_rows) >= 100)
    check("case_id unique across all 5 class files", _unique_ids(all_rows, "case_id"))

    required = {"case_id", "grade", "curriculum_topic", "question_type",
               "question", "accepted_equivalents", "trusted_expression",
               "verifiable", "required_assumptions", "corpus_support_status",
               "verification_notes", "provenance", "review_status"}
    missing = [r["case_id"] for r in all_rows if not required.issubset(r)]
    check("all required fields present", not missing)
    if missing:
        print("    failing:", missing[:10], "..." if len(missing) > 10 else "")

    bad_grade_file = [r["case_id"] for r in all_rows if r["grade"] != r["_file_grade"]]
    check("item 'grade' field matches the class file it lives in", not bad_grade_file)

    bad_topic = [(r["case_id"], r["curriculum_topic"]) for r in all_rows
                if r["curriculum_topic"] not in _CURRICULUM_TAXONOMY.get(r["grade"], set())]
    check("curriculum_topic is one of the authoritative taxonomy's exact topic "
         "strings FOR THIS ITEM'S GRADE", not bad_topic)
    if bad_topic:
        print("    failing:", bad_topic[:10])

    bad_qtype = [r["case_id"] for r in all_rows if r["question_type"] not in _QUESTION_TYPES]
    check("question_type is a known value", not bad_qtype)

    bad_null = [r["case_id"] for r in all_rows
               if r.get("expected_answer") is None and r["verifiable"] is True
               and "expected_key_idea" not in r]
    check("verifiable items have either expected_answer or expected_key_idea", not bad_null)

    mismatches = []
    for r in all_rows:
        te, ea = r.get("trusted_expression"), r.get("expected_answer")
        if te and ea:
            val = verifier._safe_eval(te)
            ev = verifier._safe_eval(ea)
            if val is None or ev is None or not verifier._close(val, ev):
                mismatches.append((r["case_id"], te, ea))
    check("every item with both trusted_expression and expected_answer: "
         "independently re-verified via verifier._safe_eval/_close (not just "
         "trusted from authoring time)", not mismatches)
    if mismatches:
        print("    failing:", mismatches)


# --------------------------------------------- conceptual v2 (pedagogical)
def test_conceptual_v2() -> None:
    print("conceptual/v2_pedagogical_extension.jsonl")
    path = DATASETS / "conceptual" / "v2_pedagogical_extension.jsonl"
    rows = _load_jsonl(path)
    check("at least 10 cases", len(rows) >= 10)

    v1_rows = _load_jsonl(DATASETS / "conceptual" / "v1_starter.jsonl")
    v1_ids = {r["case_id"] for r in v1_rows}
    v2_ids = {r["case_id"] for r in rows}
    check("case_id unique within v2", len(v2_ids) == len(rows))
    check("no case_id collides with v1_starter.jsonl", not (v1_ids & v2_ids))

    bad_dims = []
    for r in rows:
        for d in r.get("rubric_dimensions_most_relevant", []):
            if d not in _RUBRIC_DIMENSIONS:
                bad_dims.append((r["case_id"], d))
    check("rubric_dimensions_most_relevant values are all known dimensions", not bad_dims)

    _DISPOSITIONS = {
        "acknowledge_and_clarify", "acknowledge_and_confirm",
        "scaffold_toward_specific_question", "confirm_and_extend",
        "correct_specifically", "clarify_ambiguous_form", "start_new_episode",
    }
    bad_disposition = [r["case_id"] for r in rows if r.get("disposition") not in _DISPOSITIONS]
    check("disposition is a known value (same vocabulary as v1_starter.jsonl)",
         not bad_disposition)
    if bad_disposition:
        print("    failing:", bad_disposition)


# ----------------------------------------------------- personalization
def test_personalization() -> None:
    print("personalization/v1_starter.jsonl")
    path = DATASETS / "personalization" / "v1_starter.jsonl"
    rows = _load_jsonl(path)
    check("at least 10 cases", len(rows) >= 10)
    check("case_id unique", _unique_ids(rows, "case_id"))
    check("case_id uses the pz- prefix", all(r["case_id"].startswith("pz-") for r in rows))
    required = {"case_id", "scenario", "learner_level", "mechanism_reference",
               "learner_state_description", "underlying_question",
               "expected_to_change", "expected_to_remain_invariant",
               "expected_behavior", "provenance", "review_status"}
    missing = [r["case_id"] for r in rows if not required.issubset(r)]
    check("all required fields present", not missing)
    bad_level = [r["case_id"] for r in rows
                if r["learner_level"] not in ("beginner", "intermediate", "advanced")]
    check("learner_level is one of beginner/intermediate/advanced", not bad_level)

    paired = [r for r in rows if r.get("paired_case_id")]
    ids = {r["case_id"] for r in rows}
    dangling_pairs = [r["case_id"] for r in paired if r["paired_case_id"] not in ids]
    check("every paired_case_id points to another case actually in this file",
         not dangling_pairs)


# -------------------------------------------------------- multi_turn v2
def test_multi_turn_v2() -> None:
    print("multi_turn/v2_extended.json")
    path = DATASETS / "multi_turn" / "v2_extended.json"
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    convs = doc["conversations"]
    check("at least 8 new conversations", len(convs) >= 8)
    check("conversation_id unique within v2", _unique_ids(convs, "conversation_id"))

    with open(DATASETS / "multi_turn" / "v1_starter.json", encoding="utf-8") as f:
        v1_doc = json.load(f)
    v1_ids = {c["conversation_id"] for c in v1_doc["conversations"]}
    v2_ids = {c["conversation_id"] for c in convs}
    check("no conversation_id collides with v1_starter.json", not (v1_ids & v2_ids))

    bad_order = []
    for c in convs:
        nums = [t["turn"] for t in c["turns"]]
        if nums != sorted(nums) or nums != list(range(1, len(nums) + 1)):
            bad_order.append(c["conversation_id"])
    check("turn numbers are 1..N in order within each conversation", not bad_order)
    if bad_order:
        print("    failing:", bad_order)


# ----------------------------------------------------- out_of_scope v2
def test_out_of_scope_v2() -> None:
    print("out_of_scope/v2_extended.jsonl")
    path = DATASETS / "out_of_scope" / "v2_extended.jsonl"
    rows = _load_jsonl(path)
    check("at least 10 cases", len(rows) >= 10)

    v1_rows = _load_jsonl(DATASETS / "out_of_scope" / "v1_starter.jsonl")
    v1_ids = {r["case_id"] for r in v1_rows}
    v2_ids = {r["case_id"] for r in rows}
    check("case_id unique within v2", len(v2_ids) == len(rows))
    check("no case_id collides with v1_starter.jsonl", not (v1_ids & v2_ids))
    check("case_id uses the oos- prefix", all(r["case_id"].startswith("oos-") for r in rows))

    required = {"case_id", "question", "truly_out_of_scope", "out_of_scope_topic",
               "out_of_scope_reason", "boundary_case", "expected_behavior",
               "must_avoid", "provenance", "review_status"}
    missing = [r["case_id"] for r in rows if not required.issubset(r)]
    check("all required fields present (including the new truly_out_of_scope field)",
         not missing)

    n_genuine = sum(1 for r in rows if r["truly_out_of_scope"] is True)
    n_false_rejection = sum(1 for r in rows if r["truly_out_of_scope"] is False)
    check("v2 contains both genuinely-out-of-scope items and false-rejection "
         "probes (both are needed per the task's false-acceptance AND "
         "false-rejection testing requirement)",
         n_genuine > 0 and n_false_rejection > 0)
    print(f"    genuinely out-of-scope: {n_genuine}, false-rejection probes: {n_false_rejection}")


# ------------------------------------------------------- retrieval v2
def test_retrieval_v2() -> None:
    print("retrieval/v2_extended.jsonl")
    path = DATASETS / "retrieval" / "v2_extended.jsonl"
    rows = _load_jsonl(path)
    check("at least 15 queries", len(rows) >= 15)

    v1_rows = _load_jsonl(DATASETS / "retrieval" / "v1_starter.jsonl")
    v1_ids = {r["query_id"] for r in v1_rows}
    v2_ids = {r["query_id"] for r in rows}
    check("query_id unique within v2", len(v2_ids) == len(rows))
    check("no query_id collides with v1_starter.jsonl", not (v1_ids & v2_ids))

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


# ------------------------------------------------------- extraction v2
def test_extraction_v2() -> None:
    print("extraction/v2_extended.jsonl")
    path = DATASETS / "extraction" / "v2_extended.jsonl"
    rows = _load_jsonl(path)
    check("at least 10 cases", len(rows) >= 10)

    v1_rows = _load_jsonl(DATASETS / "extraction" / "v1_starter.jsonl")
    v1_ids = {r["case_id"] for r in v1_rows}
    v2_ids = {r["case_id"] for r in rows}
    check("case_id unique within v2", len(v2_ids) == len(rows))
    check("no case_id collides with v1_starter.jsonl", not (v1_ids & v2_ids))
    check("stage is a known value",
         all(r.get("stage") in ("question_to_expression", "response_to_answer")
            for r in rows))

    from scripts.llm import response_parser, verifier
    mismatches = []
    for r in rows:
        if r["stage"] == "response_to_answer":
            got = response_parser.final_number_str(r["input"])
            if got != r.get("expected_final_answer"):
                mismatches.append((r["case_id"], got, r.get("expected_final_answer")))
        elif r["stage"] == "question_to_expression" and r.get("expected_expression") not in (None, "NONE"):
            val = verifier._safe_eval(r["expected_expression"])
            if val is None:
                mismatches.append((r["case_id"], "expected_expression doesn't parse"))
    check("every response_to_answer item independently re-verified against the "
         "live response_parser.final_number_str; every question_to_expression "
         "item's expected_expression parses under verifier._safe_eval",
         not mismatches)
    if mismatches:
        print("    failing:", mismatches)


def main() -> None:
    test_arithmetic()
    test_arithmetic_v2_phaseb()
    test_out_of_scope()
    test_out_of_scope_v2()
    test_extraction()
    test_extraction_v2()
    test_retrieval()
    test_retrieval_v2()
    test_controller()
    test_conceptual()
    test_conceptual_v2()
    test_multi_turn()
    test_multi_turn_v2()
    test_curriculum_benchmark()
    test_personalization()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
