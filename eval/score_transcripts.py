"""eval/score_transcripts.py -- the automated final-answer scorer for the
paper evaluation's baseline-vs-system comparison.

Takes a dataset file plus the baseline and/or system checkpoint(s)
eval/baseline_runner.py / eval/system_runner.py produced for it, and scores
each item's LAST turn against its own ground truth, independently -- never
trusting either runner's own "ok" flag as a correctness signal (that flag
only means "non-empty text came back", not "the text was right").

Three scoring paths, chosen per item by which fields it actually has (never
guessed from the dataset's file name):
  - out_of_scope items (have `truly_out_of_scope`): three expected
    behaviours, read from each item's own fields -- ANSWER (a false-rejection
    probe, truly_out_of_scope=False), GLOSS (a bare "what is X" whose
    expected_behavior asks for a short formula-free gloss), DECLINE
    (everything else) -- against three observed outcomes: REFUSED (the
    controller's "scope_refused"/"safety_blocked" mode, or the fixed refusal
    text), GLOSS (system's single-turn scope.generate_gloss reply, mode None)
    and TAUGHT/ANSWERED. On a DECLINE item a refusal or a no-teaching gloss
    are both correct; only teaching the content is wrong (decided
    2026-10-23). Baseline has no scope gate and no gloss path, so its
    non-refusal replies on GLOSS items need the LLM judge (scorable=False,
    needs_judge=True), never a guess.
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
    against the final answer the response COMMITS to, found by
    eval/answer_extraction.py (an "Answer:" line, a concluding sentence, or
    the last bold phrase -- never "the expected value appears somewhere in
    the text", which counted wrong answers as right). A response that
    commits to no answer of the right kind is UNDECIDED (scorable=False,
    needs_llm_extraction=True) until the LLM extraction step settles it.
  - a conceptual item with neither a numeric ground truth nor
    accepted_equivalents cannot be scored this way at all (that is the LLM
    judge's territory, against expected_key_idea) -- recorded as
    scorable=False, never silently skipped or guessed.

Every baseline-vs-system comparison is also reported PAIRED (both conditions
answer the same items): McNemar's exact test and a Newcombe (method 10)
interval on the difference in accuracy, over items scorable in both.

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
import re
from pathlib import Path

from eval import answer_extraction
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
_GLOSS_EXPECTED_PREFIX = "give a short, warm, formula-free gloss"


def expected_oos_behavior(item: dict) -> str:
    """answer | gloss | decline, from the item's own fields."""
    if not item.get("truly_out_of_scope"):
        return "answer"
    if (item.get("expected_behavior") or "").strip().lower().startswith(_GLOSS_EXPECTED_PREFIX):
        return "gloss"
    return "decline"


def observed_oos_outcome(journey: dict) -> str:
    """refused | gloss | broken_gloss | taught -- what the response actually did."""
    if _was_refused(journey):
        return "refused"
    turns = journey["turns"]
    # scope.generate_gloss is the only single-turn, mode-less system reply.
    if len(turns) == 1 and "mode" in turns[0] and turns[0]["mode"] is None:
        # A cut-off gloss ("A logarith") neither teaches nor explains: wrong
        # on every item, but not "taught" either.
        return "broken_gloss" if answer_extraction.is_truncated(turns[0].get("response") or "") else "gloss"
    return "taught"


def _score_out_of_scope(item: dict, journey: dict | None) -> dict:
    if not journey or not journey.get("turns"):
        return {"scorable": False, "correct": None, "note": "no transcript for this item/condition"}
    expected = expected_oos_behavior(item)
    observed = observed_oos_outcome(journey)
    base = {"path": "out_of_scope", "expected_behavior_class": expected, "outcome": observed,
            "boundary_case": bool(item.get("boundary_case"))}
    has_mode = "mode" in journey["turns"][-1]
    if expected == "gloss" and observed == "taught" and not has_mode:
        # Baseline has no gloss path: whether its reply is a formula-free
        # gloss or a full lesson is the judge's call.
        return {**base, "scorable": False, "correct": None, "needs_judge": True,
                "note": "baseline reply to a gloss item: judge decides gloss vs teaching"}
    if expected == "answer":
        correct = observed != "refused"
    elif expected == "gloss":
        correct = observed == "gloss"
    else:
        correct = observed in ("refused", "gloss")
    return {**base, "scorable": True, "correct": correct}


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

    candidates = ground_truth_candidates(item)
    if not candidates:
        return {"scorable": False, "correct": None, "path": "curriculum",
                "note": "no ground truth to score against (conceptual item -- judge territory)"}

    commit = answer_extraction.committed_answer(text)
    verdict = answer_extraction.judge(commit, candidates, item.get("question") or "")
    info = {"path": "curriculum", "mode": mode, "extraction_source": commit.source,
            "committed_segment": commit.segment, "truncated": commit.truncated,
            "expected_any_of": candidates}
    if verdict is None:
        if commit.source == "none" and mode is not None and mode not in ANSWER_BEARING_MODES:
            return {**info, "scorable": False, "correct": None,
                    "note": "system hasn't revealed/confirmed an answer yet (pedagogical "
                           "non-terminal turn, not a wrong answer)"}
        return {**info, "scorable": False, "correct": None, "needs_llm_extraction": True,
                "note": "no committed answer of the right kind found -- LLM extraction decides"}
    return {**info, "scorable": True, "correct": verdict}


def ground_truth_candidates(item: dict) -> list[str]:
    """Every accepted form of the item's answer, re-verified from its
    trusted_expression where it has one."""
    candidates: list[str] = []
    trusted_expr = item.get("trusted_expression")
    if trusted_expr:
        truth = _truth_value(trusted_expr)
        if isinstance(truth, list):
            candidates.append(", ".join(str(v) for v in truth))
        elif truth is not None:
            candidates.append(str(truth))
    if item.get("expected_answer") is not None:
        candidates.append(str(item["expected_answer"]))
    candidates += [str(v) for v in (item.get("accepted_equivalents") or [])]
    # A quotient-remainder question ("12 remainder 1") is not answered by the
    # exact quotient 97/8 its trusted_expression evaluates to.
    if any(answer_extraction.candidate_kind(c) == "quotient_remainder" for c in candidates):
        candidates = [c for c in candidates
                      if not (answer_extraction.candidate_kind(c) == "number" and "/" in c)]
    return list(dict.fromkeys(c for c in candidates if c))


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
    """Accuracy two ways, so the unscorable share is never hidden:
    correct/scorable (with its Wilson CI) and correct/all items (strict)."""
    scorable = [r for r in results if r["correct"] is not None]
    correct = sum(1 for r in scorable if r["correct"])
    n = len(scorable)
    lo, hi = wilson_ci(correct, n)
    return {"category": label, "n_total": len(results), "n_scorable": n,
            "n_correct": correct, "correct_rate": (correct / n) if n else None,
            "wilson_95_lo": lo, "wilson_95_hi": hi,
            "strict_rate": (correct / len(results)) if results else None,
            "n_needs_llm_extraction": sum(1 for r in results if r.get("needs_llm_extraction")),
            "n_needs_judge": sum(1 for r in results if r.get("needs_judge"))}


def mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact McNemar test: b = only baseline right, c = only
    system right; under no difference b ~ Binomial(b + c, 0.5)."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def newcombe_paired_ci(a: int, b: int, c: int, d: int, z: float = 1.96) -> tuple[float, float, float]:
    """Difference in accuracy, system minus baseline, over n paired items,
    with Newcombe's (1998) method 10 interval. a = both right, b = only
    baseline right, c = only system right, d = both wrong."""
    n = a + b + c + d
    if n == 0:
        return (0.0, 0.0, 0.0)
    p1, p2 = (a + c) / n, (a + b) / n          # system, baseline
    l1, u1 = wilson_ci(a + c, n, z)
    l2, u2 = wilson_ci(a + b, n, z)
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    if denom == 0:
        phi = 0.0
    else:
        num = a * d - c * b
        num = max(num - n / 2, 0) if num > 0 else num
        phi = num / math.sqrt(denom)
    theta = p1 - p2
    dl = math.sqrt(max((p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2, 0))
    du = math.sqrt(max((u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2, 0))
    return (theta, max(-1.0, theta - dl), min(1.0, theta + du))


def paired_row(label: str, pairs: list[tuple[dict, dict]]) -> dict:
    """Paired comparison over items scorable in BOTH conditions."""
    both = [(bl, sy) for bl, sy in pairs if bl["correct"] is not None and sy["correct"] is not None]
    a = sum(1 for bl, sy in both if bl["correct"] and sy["correct"])
    b = sum(1 for bl, sy in both if bl["correct"] and not sy["correct"])
    c = sum(1 for bl, sy in both if not bl["correct"] and sy["correct"])
    d = len(both) - a - b - c
    diff, lo, hi = newcombe_paired_ci(a, b, c, d)
    return {"category": label, "n_paired": len(both), "both_right": a, "only_baseline_right": b,
            "only_system_right": c, "both_wrong": d, "diff_system_minus_baseline": diff,
            "diff_95_lo": lo, "diff_95_hi": hi, "mcnemar_p": mcnemar_exact_p(b, c)}


def holm_adjust(rows: list[dict]) -> None:
    """Holm step-down adjustment of each row's mcnemar_p (in place)."""
    order = sorted(range(len(rows)), key=lambda i: rows[i]["mcnemar_p"])
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(rows) - rank) * rows[i]["mcnemar_p"]))
        rows[i]["mcnemar_p_holm"] = running


def _pct(x: float | None) -> str:
    return f"{x * 100:.1f}%" if x is not None else "n/a"


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
    pairs: list[tuple[dict, dict]] = []
    pairs_by_grade: dict[int, list[tuple[dict, dict]]] = {}

    for item in items:
        item_id = _item_id(item)
        grade = _grade_of(item)
        scored = {}
        for condition, ckpt in (("baseline", baseline_ckpt), ("system", system_ckpt)):
            if not ckpt:
                continue
            journey = ckpt.get(item_id)
            result = score_item(item, journey)
            scored[condition] = result
            record = {"item_id": item_id, "grade": grade, "condition": condition, **result}
            per_example.append(record)
            by_condition[condition].append(result)
            if grade is not None:
                by_condition_grade[condition].setdefault(grade, []).append(result)
        if len(scored) == 2:
            pairs.append((scored["baseline"], scored["system"]))
            if grade is not None:
                pairs_by_grade.setdefault(grade, []).append((scored["baseline"], scored["system"]))

    aggregate: dict = {}
    for condition in ("baseline", "system"):
        if not by_condition[condition]:
            continue
        aggregate[condition] = {
            "overall": _rate_row("overall", by_condition[condition]),
            "by_grade": [_rate_row(f"grade_{g}", rs)
                        for g, rs in sorted(by_condition_grade[condition].items())],
        }
        oos = [r for r in by_condition[condition] if r.get("path") == "out_of_scope"]
        if oos:
            split: dict = {}
            for r in oos:
                key = f"{r['expected_behavior_class']}|{'boundary' if r['boundary_case'] else 'plain'}|{r['outcome']}"
                split[key] = split.get(key, 0) + 1
            aggregate[condition]["out_of_scope_outcomes"] = dict(sorted(split.items()))
    if pairs:
        by_grade_rows = [paired_row(f"grade_{g}", ps) for g, ps in sorted(pairs_by_grade.items())]
        if by_grade_rows:
            holm_adjust(by_grade_rows)
        aggregate["paired"] = {"overall": paired_row("overall", pairs), "by_grade": by_grade_rows}

    dataset_sources = [{"path": str(dataset_path), "version": dataset_path.stem, "item_count": len(items)}]
    config = {"baseline_checkpoint": args.baseline, "system_checkpoint": args.system,
              "extractor": "eval/answer_extraction.py (committed-answer extraction, no substring fallback)",
              "out_of_scope_scheme": "answer/gloss/decline vs refused/gloss/taught; gloss counts as a decline"}
    result_path = write_result(
        "final_answer_scoring",
        dataset_sources=dataset_sources, config=config,
        per_example_results=per_example, aggregate_metrics=aggregate,
        notes="Automated final-answer correctness scoring; independently re-verified, "
             "never trusted from either runner's own 'ok' flag. Items marked "
             "needs_llm_extraction / needs_judge are not yet scored.",
    )

    lines = [f"# Final-answer scoring -- {dataset_path.name}", ""]
    for condition in ("baseline", "system"):
        if condition not in aggregate:
            continue
        o = aggregate[condition]["overall"]
        lines.append(f"## {condition}")
        lines.append(f"- overall: {o['n_correct']}/{o['n_scorable']} correct ({_pct(o['correct_rate'])}), "
                     f"95% CI [{_pct(o['wilson_95_lo'])}, {_pct(o['wilson_95_hi'])}]; "
                     f"strict (correct / all {o['n_total']}): {_pct(o['strict_rate'])}; "
                     f"{o['n_total'] - o['n_scorable']} not yet scorable "
                     f"({o['n_needs_llm_extraction']} await LLM extraction, {o['n_needs_judge']} await the judge)")
        for row in aggregate[condition]["by_grade"]:
            lines.append(f"  - {row['category']}: {row['n_correct']}/{row['n_scorable']} "
                         f"({_pct(row['correct_rate'])}), strict {_pct(row['strict_rate'])}")
        if "out_of_scope_outcomes" in aggregate[condition]:
            lines.append("- out-of-scope outcomes (expected | boundary? | observed: count):")
            for k, v in aggregate[condition]["out_of_scope_outcomes"].items():
                lines.append(f"  - {k}: {v}")
        lines.append("")
    if "paired" in aggregate:
        lines.append("## paired (items scorable in both conditions)")
        for row in [aggregate["paired"]["overall"], *aggregate["paired"]["by_grade"]]:
            holm = f", Holm p = {row['mcnemar_p_holm']:.4f}" if "mcnemar_p_holm" in row else ""
            lines.append(f"- {row['category']}: n = {row['n_paired']}, only system right = "
                         f"{row['only_system_right']}, only baseline right = {row['only_baseline_right']}, "
                         f"difference {row['diff_system_minus_baseline'] * 100:+.1f} pts "
                         f"[{row['diff_95_lo'] * 100:+.1f}, {row['diff_95_hi'] * 100:+.1f}], "
                         f"McNemar p = {row['mcnemar_p']:.4f}{holm}")
        lines.append("")
    md_path = write_summary_markdown(result_path, lines)

    print(f"Scored {len(items)} item(s). Raw: {result_path}  Summary: {md_path}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
