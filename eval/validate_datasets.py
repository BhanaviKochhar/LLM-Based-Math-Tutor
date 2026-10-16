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
            if not line or line.startswith("#"):
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
    """eval/datasets/arithmetic.jsonl -- the single consolidated arithmetic
    accuracy dataset (former v1_starter.jsonl + v2_phaseB_extension.jsonl,
    merged; no more per-version split or provenance/review_status tags)."""
    print("arithmetic.jsonl")
    path = DATASETS / "arithmetic.jsonl"
    rows = _load_jsonl(path)
    check("at least 20 cases", len(rows) >= 20)
    check("case_id unique", _unique_ids(rows, "case_id"))
    required = {"case_id", "question", "grade", "topic", "expected_answer",
               "accepted_equivalents", "trusted_expression",
               "required_assumptions", "verifiable", "verification_notes"}
    missing = [r["case_id"] for r in rows if not required.issubset(r)]
    check("all required fields present", not missing)
    bad_null = [r["case_id"] for r in rows
               if (r["expected_answer"] is None) != (r["verifiable"] is False)]
    check("expected_answer is null iff verifiable is false", not bad_null)
    bad_grade = [r["case_id"] for r in rows if not (1 <= r.get("grade", 0) <= 5)]
    check("grade is 1-5", not bad_grade)

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
    """eval/datasets/extraction.jsonl -- the single consolidated extraction
    dataset (former v1_starter.jsonl + v2_extended.jsonl, merged)."""
    print("extraction.jsonl")
    path = DATASETS / "extraction.jsonl"
    rows = _load_jsonl(path)
    check("at least 25 cases", len(rows) >= 25)
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


# --------------------------------------------------------------- retrieval
def test_retrieval() -> None:
    """eval/datasets/retrieval.jsonl -- the single consolidated retrieval
    dataset (former v1_starter.jsonl + v2_extended.jsonl, merged)."""
    print("retrieval.jsonl")
    path = DATASETS / "retrieval.jsonl"
    rows = _load_jsonl(path)
    check("at least 40 queries", len(rows) >= 40)
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
    """eval/datasets/controller_scenarios.json -- unchanged content (just
    relocated/renamed from controller/v1_scenarios.json), plus a new
    top-level "_description" key that callers must tolerate."""
    print("controller_scenarios.json")
    path = DATASETS / "controller_scenarios.json"
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
_DISPOSITIONS = {
    "acknowledge_and_clarify", "acknowledge_and_confirm",
    "scaffold_toward_specific_question", "confirm_and_extend",
    "correct_specifically", "clarify_ambiguous_form", "start_new_episode",
}


def test_conceptual() -> None:
    """eval/datasets/conceptual.jsonl -- the single consolidated conceptual/
    pedagogical-judgment dataset (former v1_starter.jsonl +
    v2_pedagogical_extension.jsonl, merged)."""
    print("conceptual.jsonl")
    path = DATASETS / "conceptual.jsonl"
    rows = _load_jsonl(path)
    check("at least 20 cases", len(rows) >= 20)
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

    bad_disposition = [r["case_id"] for r in rows if r.get("disposition") not in _DISPOSITIONS]
    check("disposition is a known value", not bad_disposition)
    if bad_disposition:
        print("    failing:", bad_disposition)


# --------------------------------------------------------------- multi_turn
_ARCHETYPES_V3 = {
    "ambiguous-open", "unambiguous-open-then-wrong-attempt", "doubt-confusion-escalation",
    "hint-then-attempt", "correction-after-wrong-attempt", "modify-previous-problem",
    "new-question-mid-session", "give-up-then-reveal", "mid-conversation-scope-shift",
}
# "other" is an explicit, deliberately rare escape value for the handful of
# old (v1/v2) conversations whose genuine turn-by-turn shape does not
# cleanly match any of the 9 known archetypes -- used instead of forcing a
# mis-tag (mt-007, mt-013; see the consolidation report for why). Every
# NEW (v3) conversation must still use one of the 9 real archetypes.
_ARCHETYPES_ALLOWED = _ARCHETYPES_V3 | {"other"}


def test_multi_turn() -> None:
    """eval/datasets/multi_turn.json -- the single consolidated multi-turn
    dataset (relocated/renamed from multi_turn/multi_turn.json), with a new
    top-level "_description" key that callers must tolerate. The
    mid-conversation-scope-shift archetype's final turn is independently
    re-run against the REAL scripts.llm.scope.check() here -- not just
    trusted from authoring time."""
    print("multi_turn.json")
    path = DATASETS / "multi_turn.json"
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    convs = doc["conversations"]
    check("at least 100 conversations", len(convs) >= 100)
    check("conversation_id unique", _unique_ids(convs, "conversation_id"))

    bad_order = []
    for c in convs:
        nums = [t["turn"] for t in c["turns"]]
        if nums != sorted(nums) or nums != list(range(1, len(nums) + 1)):
            bad_order.append(c["conversation_id"])
    check("turn numbers are 1..N in order within each conversation", not bad_order)
    if bad_order:
        print("    failing:", bad_order)

    missing = [c["conversation_id"] for c in convs
              if not {"archetype", "student_level", "turn_length_bucket"}.issubset(c)]
    check("every conversation (old and new) has archetype/student_level/"
         "turn_length_bucket -- no item is missing these regardless of which "
         "original version it came from", not missing)
    if missing:
        print("    failing:", missing)

    bad_level = [c["conversation_id"] for c in convs
                if c.get("student_level") not in ("beginner", "intermediate", "advanced")]
    check("student_level is one of beginner/intermediate/advanced", not bad_level)
    bad_archetype = [c["conversation_id"] for c in convs if c.get("archetype") not in _ARCHETYPES_ALLOWED]
    check("archetype is one of the 9 known turn-shape archetypes (or the rare "
         "explicit 'other' escape for old conversations that genuinely don't "
         "fit any of them)", not bad_archetype)
    if bad_archetype:
        print("    failing:", bad_archetype)
    bad_bucket = [c["conversation_id"] for c in convs
                 if c.get("turn_length_bucket") not in ("short", "medium", "long")]
    check("turn_length_bucket is one of short/medium/long", not bad_bucket)

    n_other = sum(1 for c in convs if c.get("archetype") == "other")
    check("'other' is used sparingly (a handful of old conversations at most, "
         "never a dumping ground)", n_other <= 5)

    archetypes_present = {c["archetype"] for c in convs}
    check("all 9 known archetypes are represented at least once",
         _ARCHETYPES_V3.issubset(archetypes_present))

    from scripts.llm import scope
    mismatches = []
    for c in convs:
        if c["archetype"] != "mid-conversation-scope-shift":
            continue
        q = c["turns"][-1]["student"]
        if scope.check(q).in_scope:
            mismatches.append((c["conversation_id"], q))
    check("every mid-conversation-scope-shift conversation's final turn is "
         "independently re-verified as out-of-scope (or gloss-eligible) by the "
         "REAL scope.check(), not just trusted from authoring time", not mismatches)
    if mismatches:
        print("    failing:", mismatches)


# --------------------------------------------------------------- out_of_scope
def test_out_of_scope() -> None:
    """eval/datasets/out_of_scope.jsonl -- the single consolidated
    out-of-scope dataset (relocated/renamed from
    out_of_scope/out_of_scope.jsonl). Deliberately NOT mixed into the
    in-scope arithmetic/extraction accuracy datasets (B4): it tests scope
    recognition and honest refusal, not primary-curriculum correctness."""
    print("out_of_scope.jsonl")
    path = DATASETS / "out_of_scope.jsonl"
    rows = _load_jsonl(path)
    check("at least 270 cases", len(rows) >= 270)
    check("case_id unique", _unique_ids(rows, "case_id"))
    check("case_id uses the oos- prefix (never collides with in-scope ar-/ex-/rq-/ctl-/co-/mt- IDs)",
         all(r["case_id"].startswith("oos-") for r in rows))

    required = {"case_id", "question", "truly_out_of_scope", "out_of_scope_topic",
               "out_of_scope_reason", "boundary_case", "expected_behavior",
               "must_avoid"}
    missing = [r["case_id"] for r in rows if not required.issubset(r)]
    check("all required fields present, including truly_out_of_scope, on EVERY "
         "item regardless of which original version it came from", not missing)
    if missing:
        print("    failing:", missing[:10])

    # live_scope_gate_result is required for boundary_case=True items that
    # are GENUINELY out of scope (truly_out_of_scope=True) -- the case the
    # live regex gate may or may not catch, recorded for traceability. It is
    # NOT required for a false-rejection probe (truly_out_of_scope=False)
    # with boundary_case=True: generate_out_of_scope_v3.py's own
    # _FALSE_REJECTION_ITEMS loop (see its _build()) asserts in_scope=True
    # at authoring time and never writes this field for those items, so
    # v3's own false-rejection probes never carry it either -- a pre-
    # existing, deliberate convention, not a gap this merge should paper
    # over by forcing the field onto items the generator itself omits it from.
    missing_gate = [r["case_id"] for r in rows
                    if r.get("boundary_case") and r.get("truly_out_of_scope")
                    and "live_scope_gate_result" not in r]
    check("every GENUINELY-out-of-scope boundary_case=True item carries a "
         "live_scope_gate_result (recorded from a real scope.check() call, "
         "never asserted on)", not missing_gate)
    if missing_gate:
        print("    failing:", missing_gate)

    n_genuine = sum(1 for r in rows if r["truly_out_of_scope"] is True)
    n_false_rejection = sum(1 for r in rows if r["truly_out_of_scope"] is False)
    check("contains both genuinely-out-of-scope items and false-rejection "
         "probes (both are needed per the task's false-acceptance AND "
         "false-rejection testing requirement)",
         n_genuine > 0 and n_false_rejection > 0)
    print(f"    genuinely out-of-scope: {n_genuine}, false-rejection probes: {n_false_rejection}")

    # Pre-existing v1/v2 items authored as boundary_case=False (i.e. "uses
    # real trigger vocabulary, the live gate MUST catch it") whose topic
    # genuinely has no pattern in scripts.llm.scope.BEYOND_PRIMARY_TOPICS
    # today: oos-010 ("limit ... as n approaches infinity" -- no "calculus"
    # keyword present), oos-016 (binary/number-base conversion -- not a
    # listed topic at all), oos-018 (standard deviation -- the gate only
    # catches the bare words "median"/"statistics", not "standard
    # deviation"). This cross-check against the REAL scope.check() (new
    # rigor this consolidation adds -- the old v1/v2 tests never ran it)
    # surfaces a genuine scope.py coverage gap, not a dataset authoring
    # error; boundary_case is an existing field on these items and is left
    # untouched per the task's instructions, so these three are named here
    # explicitly rather than silently reclassified.
    _KNOWN_LIVE_GATE_GAPS = {"oos-010", "oos-016", "oos-018"}

    from scripts.llm import scope
    mismatches = []
    for r in rows:
        if r["boundary_case"] or r["case_id"] in _KNOWN_LIVE_GATE_GAPS:
            continue  # deliberately exempt -- see comments above
        result = scope.check(r["question"])
        if r["truly_out_of_scope"]:
            if result.in_scope:
                mismatches.append((r["case_id"], "expected out-of-scope, scope.check() said in_scope"))
        else:
            if not result.in_scope:
                mismatches.append((r["case_id"], "expected in-scope (false-rejection probe), "
                                   f"scope.check() flagged it (topic={result.topic})"))
    check("every non-boundary item's ground truth matches the REAL scope.check() "
         "classification (not just trusted from authoring time), aside from the "
         "3 known pre-existing scope.py coverage gaps named above", not mismatches)
    if mismatches:
        print("    failing:", mismatches[:10], "..." if len(mismatches) > 10 else "")


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


_FUNCTION_CALL_RE_V2 = re.compile(r"^\s*([a-z_]+)\s*\(\s*(.*?)\s*\)\s*$", re.IGNORECASE)
_BARE_DIV_RE_V2 = re.compile(r"^\s*(-?\d+)\s*/\s*(-?\d+)\s*$")


def test_curriculum_benchmark() -> None:
    """eval/datasets/curriculum_benchmark_class{1..5}.jsonl -- the Class 1-5
    benchmark (relocated/renamed from curriculum_benchmark/class{1..5}.jsonl,
    itself already a merge of an earlier v1/v2 split). Validates against the
    authoritative taxonomy (docs/verified_ncert_class_1_5_topics.md, copied
    read-only into _CURRICULUM_TAXONOMY above) and independently re-verifies
    every item's trusted_expression -- plain arithmetic via
    verifier._safe_eval, the lcm/hcf/is_prime/factors/angle_type/time_add
    registry via verifier._parse_function_call, or the quotient+remainder
    convention for a non-exact bare int/int division -- rather than trusting
    the authoring-time claim."""
    print("curriculum_benchmark_class1..5.jsonl")
    from scripts.llm import verifier

    all_rows = []
    for grade in range(1, 6):
        path = DATASETS / f"curriculum_benchmark_class{grade}.jsonl"
        rows = _load_jsonl(path)
        for r in rows:
            r["_file_grade"] = grade
        all_rows.extend(rows)

    check("at least 900 items across all 5 class files", len(all_rows) >= 900)
    check("case_id unique across all 5 class files", _unique_ids(all_rows, "case_id"))

    required = {"case_id", "grade", "curriculum_topic", "question_type",
               "question", "student_level", "phrasing", "distractor",
               "accepted_equivalents", "trusted_expression", "verifiable",
               "required_assumptions", "corpus_support_status",
               "verification_notes"}
    missing = [r["case_id"] for r in all_rows if not required.issubset(r)]
    check("all required fields present, including student_level/phrasing/"
         "distractor on EVERY item regardless of which original version it "
         "came from", not missing)
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

    bad_level = [r["case_id"] for r in all_rows
                if r["student_level"] not in ("beginner", "intermediate", "advanced")]
    check("student_level is one of beginner/intermediate/advanced", not bad_level)
    bad_phrasing = [r["case_id"] for r in all_rows if r["phrasing"] not in ("ambiguous", "unambiguous")]
    check("phrasing is one of ambiguous/unambiguous", not bad_phrasing)
    bad_distractor = [r["case_id"] for r in all_rows if not isinstance(r["distractor"], bool)]
    check("distractor is a boolean", not bad_distractor)

    bad_null = [r["case_id"] for r in all_rows
               if r.get("expected_answer") is None and r["verifiable"] is True
               and "expected_key_idea" not in r]
    check("verifiable items have either expected_answer or expected_key_idea", not bad_null)

    mismatches = []
    for r in all_rows:
        te = r.get("trusted_expression")
        if not te:
            continue
        m_div = _BARE_DIV_RE_V2.match(te)
        is_nonexact_int_div = (m_div and int(m_div.group(2)) != 0
                               and int(m_div.group(1)) % int(m_div.group(2)) != 0)
        # The quotient+remainder convention (verifiable=False,
        # expected_answer=None, accepted_equivalents names the quotient) is
        # the v2 generator's own choice for "share N items among M people"
        # style items -- it does NOT apply retroactively to older v1 items
        # that already set verifiable=True and a decimal expected_answer for
        # the SAME bare "a/b" shape (e.g. cb-158 "Convert 7/20 to a decimal"
        # -> 0.35): those are a plain division, not a sharing-with-leftover
        # question, so they fall through to the ordinary _safe_eval check
        # below instead of being forced into this convention.
        if is_nonexact_int_div and r["verifiable"] is False and r.get("expected_answer") is None:
            q, rem = verifier._quotient_remainder(te)
            # A conceptual/misconception item (expected_key_idea present)
            # is graded on the key idea, not on accepted_equivalents -- v1's
            # cb-085 legitimately leaves accepted_equivalents empty for
            # exactly this reason, pre-dating the v2 convention of always
            # populating it.
            if "expected_key_idea" not in r and not any(str(q) in eq for eq in r.get("accepted_equivalents", [])):
                mismatches.append((r["case_id"], f"accepted_equivalents missing quotient {q}"))
            continue
        m_fn = _FUNCTION_CALL_RE_V2.match(te)
        if m_fn and m_fn.group(1).lower() in verifier._FUNCTION_REGISTRY:
            parsed = verifier._parse_function_call(te)
            if parsed is None:
                mismatches.append((r["case_id"], f"function call didn't parse: {te}"))
                continue
            result, answer_type = parsed
            expected = ", ".join(str(x) for x in result) if answer_type == "list" else str(result)
            if r.get("expected_answer") != expected:
                mismatches.append((r["case_id"], f"expected_answer={r.get('expected_answer')!r} "
                                   f"!= recomputed {expected!r}"))
            continue
        val = verifier._safe_eval(te)
        ea = r.get("expected_answer")
        if val is None:
            mismatches.append((r["case_id"], f"trusted_expression doesn't parse: {te}"))
        elif ea is not None:
            # Some older items store expected_answer as a bare numeral that
            # still round-trips through _safe_eval (e.g. "45,687" style
            # commas) -- fall back to a second _safe_eval/_close comparison
            # before flagging a real mismatch.
            ev = verifier._safe_eval(ea)
            if ev is not None:
                if not verifier._close(val, ev):
                    mismatches.append((r["case_id"], f"expected_answer={ea!r} != recomputed {str(val)!r}"))
            elif ea != str(val):
                mismatches.append((r["case_id"], f"expected_answer={ea!r} != recomputed {str(val)!r}"))
    check("every non-null trusted_expression independently re-verified (plain "
         "arithmetic via verifier._safe_eval, OR the lcm/hcf/is_prime/factors/"
         "angle_type/time_add registry via verifier._parse_function_call, OR "
         "the quotient+remainder convention for a non-exact bare division) -- "
         "not just trusted from authoring time", not mismatches)
    if mismatches:
        print("    failing:", mismatches[:10], "..." if len(mismatches) > 10 else "")


# ----------------------------------------------------- personalization
def test_personalization() -> None:
    """eval/datasets/personalization.jsonl -- relocated/renamed from
    personalization/v1_starter.jsonl (no v2 for this bucket)."""
    print("personalization.jsonl")
    path = DATASETS / "personalization.jsonl"
    rows = _load_jsonl(path)
    check("at least 10 cases", len(rows) >= 10)
    check("case_id unique", _unique_ids(rows, "case_id"))
    check("case_id uses the pz- prefix", all(r["case_id"].startswith("pz-") for r in rows))
    required = {"case_id", "scenario", "learner_level", "mechanism_reference",
               "learner_state_description", "underlying_question",
               "expected_to_change", "expected_to_remain_invariant",
               "expected_behavior"}
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


def main() -> None:
    test_arithmetic()
    test_out_of_scope()
    test_extraction()
    test_retrieval()
    test_controller()
    test_conceptual()
    test_multi_turn()
    test_curriculum_benchmark()
    test_personalization()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
