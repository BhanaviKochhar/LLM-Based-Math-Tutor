"""eval/score_transcripts.py -- the automated final-answer scorer for the
paper evaluation's baseline-vs-system comparison.

Takes a dataset file plus the baseline and/or system checkpoint(s)
eval/baseline_runner.py / eval/system_runner.py produced for it, and scores
each item's LAST turn against its own ground truth, independently -- never
trusting either runner's own "ok" flag as a correctness signal (that flag
only means "non-empty text came back", not "the text was right").

Three scoring paths, chosen per item by which fields it actually has (never
guessed from the dataset's file name):
  - out_of_scope items (have `truly_out_of_scope`): scored on whether the
    response actually refused/hedged, compared against whether it SHOULD
    have (truly_out_of_scope=True) or should NOT have (a false-rejection
    probe). Refusal is detected from the real controller mode when the
    transcript carries one (system_runner's "scope_refused"/"safety_blocked",
    a precise signal), OR by the fixed refusal text's own marker
    (response_parser.is_refusal) otherwise -- which is the ONLY signal
    available for baseline, since baseline has no scope gate and therefore
    no "mode" at all. That asymmetry is not a scorer bug -- it is the
    architecture difference O3 exists to measure.
  - multi_turn items (have `turns` in the ORIGINAL dataset record): scored
    best-effort against `reference_answer`, which is free text, sometimes
    multi-part (e.g. "50 then 58") -- every numeric token found in it is a
    candidate, and the response's own final stated number is checked for
    sympy-equivalence against ANY of them. Weaker than the other two paths;
    flagged as such in every result record, not silently equated with them.
  - everything else (curriculum_benchmark-shaped single-turn items): scored
    via the SAME independent-recomputation discipline used throughout this
    repo's datasets -- expected_answer/accepted_equivalents re-verified via
    scripts.llm.verifier (_safe_eval for plain arithmetic, _parse_function_call
    for the lcm/hcf/is_prime/factors/angle_type/time_add registry), compared
    against the response's extracted final number via
    scripts.llm.response_parser.final_number_str + verifier._close (exact
    sympy equality or float tolerance) -- a text/substring fallback only for
    categorical or quotient-remainder-worded expected answers, where there is
    no single number to extract.
  - a conceptual item with neither a numeric ground truth nor
    accepted_equivalents cannot be scored this way at all (that is Track F's
    human-rubric territory) -- recorded as scorable=False, never silently
    skipped or guessed.

Artifact shape follows the plan's own stated convention, reusing the
existing shared writer (eval/component_eval/results.py) rather than
inventing a new one: one raw per-item JSON with full traceability, one
derived .md summary table generated FROM that JSON by this same script
(never hand-copied).

CLI:
    python -m eval.score_transcripts --dataset eval/datasets/curriculum_benchmark_class1.jsonl \
        --baseline eval/results/baseline_runs/curriculum_benchmark_class1.jsonl \
        --system eval/results/system_runs/curriculum_benchmark_class1.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from eval.baseline_runner import _grade_of, _item_id, load_items
from eval.component_eval.results import write_result, write_summary_markdown
from scripts.llm import response_parser, verifier

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- ground truth
def _truth_value(expr: str):
    """Independently re-evaluate a trusted_expression, mirroring the exact
    two-path discipline the dataset generators used -- never trust a
    pre-recorded expected_answer string alone when the expression itself
    is available to recompute from."""
    import re
    m = re.match(r"^\s*([a-z_]+)\s*\(\s*(.*?)\s*\)\s*$", expr, re.IGNORECASE)
    if m:
        parsed = verifier._parse_function_call(expr)
        return parsed[0] if parsed else None
    return verifier._safe_eval(expr)


def _load_checkpoint(path: Path | None) -> dict[str, dict]:
    if not path or not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                out[rec["id"]] = rec
    return out


def _last_turn(journey: dict | None) -> dict | None:
    if not journey or not journey.get("turns"):
        return None
    return journey["turns"][-1]


def _last_turn_text(journey: dict | None) -> str | None:
    last = _last_turn(journey)
    return last.get("response") if last else None


# The 3 controller modes where episode.py's own _post_check (see
# frontend/episode.py) actually expects a trusted answer to appear in the
# text -- reused here as-is rather than inventing a separate boundary.
# Everything else (teach_invite, hint, ack_conceptual, diagnose_wrong,
# redirect, ...) is a legitimate PEDAGOGICAL non-reveal, by design -- the
# system withholding the answer on a cold single-turn open is not the same
# thing as the system getting the answer wrong, and scoring it as "wrong"
# would unfairly understate system's correctness on exactly the bucket
# that matters most. Only applies when a `mode` is actually present (i.e.
# a system-condition transcript); baseline has no controller and no
# pedagogical withholding, so for baseline a missing number is scored as
# wrong, same as always.
#
# Public (not _-prefixed): eval/system_runner.py imports this same set to
# decide whether a single-turn item's one real turn already reached a
# scorable state, or needs a forced follow-up -- one canonical boundary,
# defined once, instead of two definitions that could silently drift apart.
ANSWER_BEARING_MODES = {"co_solve", "reveal", "diagnose_correct"}


def _was_refused(journey: dict | None) -> bool | None:
    """True/False once a last turn exists; None if there's no transcript at
    all (journey never ran)."""
    if not journey or not journey.get("turns"):
        return None
    last = journey["turns"][-1]
    mode_refused = last.get("mode") in ("scope_refused", "safety_blocked")
    text_refused = response_parser.is_refusal(last.get("response") or "")
    return bool(mode_refused or text_refused)


# --------------------------------------------------------------------------- scoring paths
def _score_out_of_scope(item: dict, journey: dict | None) -> dict:
    refused = _was_refused(journey)
    if refused is None:
        return {"scorable": False, "correct": None, "note": "no transcript for this item/condition"}
    expected_refusal = bool(item.get("truly_out_of_scope"))
    return {"scorable": True, "correct": refused == expected_refusal,
            "refused": refused, "expected_refusal": expected_refusal, "path": "out_of_scope"}


def _score_multi_turn(item: dict, journey: dict | None) -> dict:
    text = _last_turn_text(journey)
    if text is None:
        return {"scorable": False, "correct": None, "note": "no transcript for this item/condition"}
    reference = item.get("reference_answer") or ""
    model_num_str = response_parser.final_number_str(text)
    model_val = verifier._safe_eval(model_num_str) if model_num_str else None
    if model_val is None:
        return {"scorable": False, "correct": None, "path": "multi_turn",
                "note": "couldn't extract a final number from the response"}
    target_tokens = response_parser._all_number_tokens(reference)
    target_vals = [v for v in (verifier._safe_eval(t) for t in target_tokens) if v is not None]
    if not target_vals:
        return {"scorable": False, "correct": None, "path": "multi_turn",
                "note": "reference_answer has no extractable number to compare against"}
    correct = any(verifier._close(model_val, tv) for tv in target_vals)
    return {"scorable": True, "correct": correct, "path": "multi_turn", "best_effort": True,
            "model_value": str(model_val), "reference_answer": reference}


def _score_curriculum(item: dict, journey: dict | None) -> dict:
    last = _last_turn(journey)
    if last is None:
        return {"scorable": False, "correct": None, "note": "no transcript for this item/condition"}
    text = last.get("response") or ""
    mode = last.get("mode")
    if response_parser.is_refusal(text):
        return {"scorable": True, "correct": False, "path": "curriculum", "note": "model refused"}

    candidates: list[str] = []
    trusted_expr = item.get("trusted_expression")
    if trusted_expr:
        truth = _truth_value(trusted_expr)
        if isinstance(truth, list):
            candidates += [str(v) for v in truth]
        elif truth is not None:
            candidates.append(str(truth))
    if item.get("expected_answer") is not None:
        candidates.append(str(item["expected_answer"]))
    candidates += [str(v) for v in (item.get("accepted_equivalents") or [])]

    if not candidates:
        return {"scorable": False, "correct": None, "path": "curriculum",
                "note": "no ground truth to score against (conceptual item -- Track F territory)"}

    model_num_str = response_parser.final_number_str(text)
    model_val = verifier._safe_eval(model_num_str) if model_num_str else None
    for cand in candidates:
        cand_val = verifier._safe_eval(cand)
        if cand_val is not None and model_val is not None and verifier._close(cand_val, model_val):
            return {"scorable": True, "correct": True, "path": "curriculum",
                    "matched_against": cand, "model_value": str(model_val)}
    low = text.lower()
    for cand in candidates:
        if cand and str(cand).lower() in low:
            return {"scorable": True, "correct": True, "path": "curriculum",
                    "matched_against": cand, "note": "text match (categorical/worded answer)"}
    if model_val is None and mode is not None and mode not in ANSWER_BEARING_MODES:
        return {"scorable": False, "correct": None, "path": "curriculum", "mode": mode,
                "note": "system hasn't revealed/confirmed an answer yet (pedagogical "
                       "non-terminal turn, not a wrong answer) -- a single-turn item run "
                       "through system with no follow-up may never reach a scorable state"}
    return {"scorable": True, "correct": False, "path": "curriculum", "mode": mode,
            "model_value": str(model_val) if model_val is not None else None,
            "expected_any_of": candidates}


def score_item(item: dict, journey: dict | None) -> dict:
    if "truly_out_of_scope" in item:
        return _score_out_of_scope(item, journey)
    if "turns" in item:
        return _score_multi_turn(item, journey)
    return _score_curriculum(item, journey)


# --------------------------------------------------------------------------- stats
def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% confidence interval for a binomial proportion, per the
    plan's own stated statistical treatment."""
    if n == 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom))


def _rate_row(label: str, results: list[dict]) -> dict:
    scorable = [r for r in results if r["correct"] is not None]
    correct = sum(1 for r in scorable if r["correct"])
    n = len(scorable)
    lo, hi = wilson_ci(correct, n)
    return {"category": label, "n_total": len(results), "n_scorable": n,
            "n_correct": correct, "correct_rate": (correct / n) if n else None,
            "wilson_95_lo": lo, "wilson_95_hi": hi}


# --------------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--baseline", default=None, help="baseline_runner.py checkpoint path")
    parser.add_argument("--system", default=None, help="system_runner.py checkpoint path")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    items = load_items(dataset_path)
    baseline_ckpt = _load_checkpoint(Path(args.baseline)) if args.baseline else {}
    system_ckpt = _load_checkpoint(Path(args.system)) if args.system else {}
    if not baseline_ckpt and not system_ckpt:
        raise SystemExit("Need at least one of --baseline / --system to score anything.")

    per_example: list[dict] = []
    by_condition: dict[str, list[dict]] = {"baseline": [], "system": []}
    by_condition_grade: dict[str, dict[int, list[dict]]] = {"baseline": {}, "system": {}}

    for item in items:
        item_id = _item_id(item)
        grade = _grade_of(item)
        for condition, ckpt in (("baseline", baseline_ckpt), ("system", system_ckpt)):
            if not ckpt:
                continue
            journey = ckpt.get(item_id)
            result = score_item(item, journey)
            record = {"item_id": item_id, "grade": grade, "condition": condition, **result}
            per_example.append(record)
            by_condition[condition].append(result)
            if grade is not None:
                by_condition_grade[condition].setdefault(grade, []).append(result)

    aggregate = {}
    for condition in ("baseline", "system"):
        if not by_condition[condition]:
            continue
        aggregate[condition] = {
            "overall": _rate_row("overall", by_condition[condition]),
            "by_grade": [_rate_row(f"grade_{g}", rs)
                        for g, rs in sorted(by_condition_grade[condition].items())],
        }

    dataset_sources = [{"path": str(dataset_path), "version": dataset_path.stem, "item_count": len(items)}]
    config = {"baseline_checkpoint": args.baseline, "system_checkpoint": args.system}
    result_path = write_result(
        "final_answer_scoring",
        dataset_sources=dataset_sources, config=config,
        per_example_results=per_example, aggregate_metrics=aggregate,
        notes="Automated final-answer correctness scoring; independently re-verified, "
             "never trusted from either runner's own 'ok' flag.",
    )

    lines = [f"# Final-answer scoring -- {dataset_path.name}", ""]
    for condition, metrics in aggregate.items():
        o = metrics["overall"]
        rate = f"{o['correct_rate']*100:.1f}%" if o["correct_rate"] is not None else "n/a"
        lines.append(f"## {condition}")
        lines.append(f"- overall: {o['n_correct']}/{o['n_scorable']} correct ({rate}), "
                     f"95% CI [{o['wilson_95_lo']*100:.1f}%, {o['wilson_95_hi']*100:.1f}%], "
                     f"{o['n_total'] - o['n_scorable']} not automatically scorable")
        for row in metrics["by_grade"]:
            r = f"{row['correct_rate']*100:.1f}%" if row["correct_rate"] is not None else "n/a"
            lines.append(f"  - {row['category']}: {row['n_correct']}/{row['n_scorable']} ({r})")
        lines.append("")
    md_path = write_summary_markdown(result_path, lines)

    print(f"Scored {len(items)} item(s). Raw: {result_path}  Summary: {md_path}")
    for condition, metrics in aggregate.items():
        o = metrics["overall"]
        rate = f"{o['correct_rate']*100:.1f}%" if o["correct_rate"] is not None else "n/a"
        print(f"  {condition}: {o['n_correct']}/{o['n_scorable']} correct ({rate})")


if __name__ == "__main__":
    main()
