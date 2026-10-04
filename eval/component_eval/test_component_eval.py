"""eval/component_eval/test_component_eval.py — offline tests for the
component evaluation runners themselves (not the tutor system).

Deterministic, no LLM, no network. Follows this repo's existing
check()/scenario() convention (eval/controller_walk.py,
eval/validate_datasets.py) rather than introducing pytest.

Run:  python -m eval.component_eval.test_component_eval
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from . import results
from .scoring_helpers import (
    RUBRIC_REQUIRED,
    SCORABLE,
    VERIFIED_NOT_SYSTEM_SCORABLE,
    classify_item,
    score_trusted_computation,
)

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


# --------------------------------------------------------- classify_item
def test_classify_item() -> None:
    print("scoring_helpers.classify_item")
    check("verifiable + trusted_expression -> SCORABLE",
         classify_item({"verifiable": True, "trusted_expression": "2+2"}) == SCORABLE)
    check("verifiable + no trusted_expression -> VERIFIED_NOT_SYSTEM_SCORABLE "
         "(the HCF/LCM case)",
         classify_item({"verifiable": True, "trusted_expression": None})
         == VERIFIED_NOT_SYSTEM_SCORABLE)
    check("not verifiable -> RUBRIC_REQUIRED",
         classify_item({"verifiable": False, "trusted_expression": None})
         == RUBRIC_REQUIRED)
    check("not verifiable, even with a trusted_expression present, stays RUBRIC_REQUIRED "
         "(verifiable is the controlling field)",
         classify_item({"verifiable": False, "trusted_expression": "2+2"})
         == RUBRIC_REQUIRED)
    # Boundary: missing fields entirely (malformed item) must not crash.
    check("missing fields entirely -> RUBRIC_REQUIRED, no crash", classify_item({}) == RUBRIC_REQUIRED)


# --------------------------------------------------- score_trusted_computation
def test_score_trusted_computation() -> None:
    print("scoring_helpers.score_trusted_computation")
    check("exact integer match",
         score_trusted_computation({"trusted_expression": "2+2", "expected_answer": "4"})["outcome"] == "match")
    check("deliberate mismatch is caught, not silently passed",
         score_trusted_computation({"trusted_expression": "2+2", "expected_answer": "5"})["outcome"] == "mismatch")
    # NOTE: a BARE fraction-shaped expression like "3/6" is not usable for
    # this fixture -- it collides with the real _PLAIN_DIV withholding rule
    # (the same systematic edge case documented for ar-020/cb-158: a bare
    # "int/int" string is indistinguishable from a non-exact division word
    # problem to that gate, regardless of intent). "(1/2)*1" is NOT bare
    # int/int shaped, so it exercises genuine fraction-equivalence matching
    # instead of colliding with that unrelated gate.
    check("fraction equivalence ((1/2)*1 == 2/4) is recognised as a match via verifier._close",
         score_trusted_computation({"trusted_expression": "(1/2)*1", "expected_answer": "2/4"})["outcome"] == "match")
    check("both sides None (withheld non-exact division) is a MATCH, not a failure",
         score_trusted_computation({"trusted_expression": "20/3", "expected_answer": None})["outcome"] == "match")
    check("computed None vs a stated expected_answer is a MISMATCH "
         "(the bare-fraction-looks-like-division edge case, e.g. ar-020/cb-158)",
         score_trusted_computation({"trusted_expression": "3/10", "expected_answer": "0.3"})["outcome"] == "mismatch")
    check("no trusted_expression at all -> error, not a silent pass",
         score_trusted_computation({"trusted_expression": None, "expected_answer": "4"})["outcome"] == "error")
    check("syntactically malformed expression does not crash, and correctly "
         "produces no computable value against a non-null expected_answer "
         "-> mismatch (not a Python exception/'error', and not silently 'match')",
         score_trusted_computation({"trusted_expression": "2++", "expected_answer": "4"})["outcome"] == "mismatch")


# --------------------------------------------------------------- results.py
def test_write_result_fields_and_no_overwrite() -> None:
    print("results.write_result — artifact shape and non-overwrite guarantee")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        path1 = results.write_result(
            "unit_test_fixture",
            dataset_sources=[{"path": "fake.jsonl", "version": "v1", "item_count": 1}],
            config={"live_llm_used": False},
            per_example_results=[{"case_id": "x-001", "outcome": "match"}],
            aggregate_metrics={"total_items": 1, "match": 1},
            results_dir=tmp_dir,
        )
        check("result file was actually created", path1.exists())
        with open(path1, encoding="utf-8") as f:
            record = json.load(f)
        for field in ("evaluator_name", "run_timestamp_utc", "git", "environment",
                      "dataset_sources", "config", "aggregate_metrics",
                      "exclusions", "execution_errors", "per_example_results"):
            check(f"result record has required field '{field}'", field in record)
        check("per_example_results preserved raw, not aggregated away",
             record["per_example_results"] == [{"case_id": "x-001", "outcome": "match"}])

        # Actually exercise write_result's real collision guard: force the
        # SAME timestamp+commit the previous call used (by monkeypatching
        # the datetime class it calls .now() on), so the computed filename
        # is byte-for-byte identical to path1, and confirm it genuinely
        # raises FileExistsError rather than silently overwriting.
        class _FixedDatetime:
            @classmethod
            def now(cls, tz=None):
                import re
                m = re.search(r"_(\d{8}T\d{6}Z)_", path1.name)
                from datetime import datetime as _dt
                return _dt.strptime(m.group(1), "%Y%m%dT%H%M%SZ")

        orig_datetime = results.datetime
        results.datetime = _FixedDatetime
        raised = False
        try:
            results.write_result(
                "unit_test_fixture",
                dataset_sources=[], config={}, per_example_results=[],
                aggregate_metrics={}, results_dir=tmp_dir,
            )
        except FileExistsError:
            raised = True
        finally:
            results.datetime = orig_datetime
        check("write_result genuinely raises FileExistsError rather than "
             "silently overwriting when the computed path already exists",
             raised)
        check("the original file's content is untouched after the collision attempt",
             json.loads(path1.read_text())["per_example_results"][0]["case_id"] == "x-001")


def test_write_summary_markdown() -> None:
    print("results.write_summary_markdown")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        path = results.write_result(
            "unit_test_fixture2",
            dataset_sources=[], config={}, per_example_results=[],
            aggregate_metrics={}, results_dir=tmp_dir,
        )
        md_path = results.write_summary_markdown(path, ["# title", "body line"])
        check("markdown summary written alongside the json result, same stem",
             md_path.exists() and md_path.stem == path.stem)
        check("markdown content matches what was passed",
             md_path.read_text(encoding="utf-8").strip() == "# title\nbody line")


def main() -> None:
    test_classify_item()
    test_score_trusted_computation()
    test_write_result_fields_and_no_overwrite()
    test_write_summary_markdown()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
