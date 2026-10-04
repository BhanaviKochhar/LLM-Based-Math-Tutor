"""eval/component_eval/scoring_helpers.py — shared scoring primitives.

Resolves the terminology ambiguity flagged in the preceding dataset-expansion
pass around 'verifiable' vs. system-scorable (the HCF/LCM cases in
eval/datasets/arithmetic/v2_phaseB_extension.jsonl and
eval/datasets/curriculum_benchmark/v1_class5.jsonl).

RESOLUTION (documented here, not a silent redefinition):

  `verifiable` (existing dataset field) means: this item has ONE
  independently-confirmed correct value -- a ground-truth claim about the
  ITEM, authored and checked at dataset-authoring time (by
  scripts.llm.verifier._safe_eval directly, or for HCF/LCM, by a raw
  sympy.gcd/sympy.lcm call made outside the production verifier). It says
  nothing about whether the LIVE SYSTEM can currently compute that value.

  `system_scorable` (NEW, defined only here, as a scoring-time derived
  classification -- deliberately NOT a new dataset field, since the
  smallest justified change here is at the scoring layer, not by editing
  already-published dataset files) means: `trusted_expression` is non-null,
  i.e. scripts.llm.verifier._safe_eval can actually evaluate it. This is
  what determines whether the LIVE production verifier can score the item
  end-to-end today.

  An item can be verifiable=True and system_scorable=False at the same time
  -- that is exactly the HCF/LCM case, and this module makes it a named,
  reported category (VERIFIED_NOT_SYSTEM_SCORABLE) rather than letting it
  silently fall into either "pass" or "fail".
"""
from __future__ import annotations

from scripts.llm import verifier

# Scoring-time classification labels (not dataset fields).
SCORABLE = "system_scorable"
VERIFIED_NOT_SYSTEM_SCORABLE = "verified_not_system_scorable"
RUBRIC_REQUIRED = "requires_human_rubric_evaluation"


def classify_item(item: dict) -> str:
    """One of SCORABLE / VERIFIED_NOT_SYSTEM_SCORABLE / RUBRIC_REQUIRED.

    Works for both eval/datasets/arithmetic/*.jsonl (always has
    `verifiable`/`trusted_expression`) and
    eval/datasets/curriculum_benchmark/v1_class*.jsonl (same two fields,
    plus `verifiable: false` items that use `expected_key_idea` instead of
    `expected_answer`).
    """
    if item.get("verifiable") is True and item.get("trusted_expression"):
        return SCORABLE
    if item.get("verifiable") is True and not item.get("trusted_expression"):
        return VERIFIED_NOT_SYSTEM_SCORABLE
    return RUBRIC_REQUIRED


def score_trusted_computation(item: dict) -> dict:
    """Run the item's `trusted_expression` through the REAL verifier
    computation+gating path (verifier._grade_appropriate_answer via
    verifier.solve's injected-extractor mode), and compare the result to
    `expected_answer`.

    This exercises the actual gating logic (e.g. the bare-non-exact-division
    withholding rule, and the division-by-zero/parenthesized-division fixes
    made in the preceding correctness pass) -- NOT just whether
    trusted_expression parses, which eval/validate_datasets.py already
    checks. A correct result here can legitimately be `answer is None` when
    the dataset's own `expected_answer` is also null (e.g. a withheld
    remainder case) -- that is a MATCH, not a failure.

    Returns {"outcome": "match"|"mismatch"|"error", "computed": ..., "detail": ...}.
    Never raises.
    """
    te = item.get("trusted_expression")
    if not te:
        return {"outcome": "error", "computed": None,
               "detail": "no trusted_expression; use classify_item() first"}
    # Pass the item's real natural-language `question` (not just the bare
    # expression) as solve()'s `question` argument -- verifier.solve now
    # uses that text to tell a fraction/decimal-conversion question (e.g.
    # "Convert 7/20 to a decimal") apart from a genuine non-exact-division
    # word problem when the trusted_expression is bare "int/int" shaped.
    # extract_fn still forces the KNOWN-GOOD expression regardless of what's
    # passed positionally, so this only changes what the gating logic sees,
    # not what gets "extracted".
    question_text = item.get("question") or te
    try:
        answer, is_math = verifier.solve(question_text, extract_fn=lambda q: te)
    except Exception as e:
        return {"outcome": "error", "computed": None, "detail": repr(e)}

    expected = item.get("expected_answer")
    if answer is None and expected is None:
        return {"outcome": "match", "computed": None,
               "detail": "both None (withheld remainder/non-exact-division case)"}
    if answer is None or expected is None:
        return {"outcome": "mismatch", "computed": answer,
               "detail": f"one side is None: computed={answer!r} expected={expected!r}"}
    try:
        got_val = verifier._safe_eval(answer)
        exp_val = verifier._safe_eval(expected)
    except Exception as e:
        return {"outcome": "error", "computed": answer, "detail": repr(e)}
    if got_val is None or exp_val is None:
        # expected_answer may be free text (e.g. "two lakh ... seventy-eight")
        # for non-numeric curriculum_benchmark items that still have a
        # trusted_expression on a DIFFERENT sub-part -- not an error, just
        # not string-comparable; fall back to an exact string compare.
        match = str(answer).strip() == str(expected).strip()
        return {"outcome": "match" if match else "mismatch", "computed": answer,
               "detail": "compared as strings (non-numeric expected_answer)"}
    match = verifier._close(got_val, exp_val)
    return {"outcome": "match" if match else "mismatch", "computed": answer,
           "detail": f"computed={got_val} expected={exp_val}"}
