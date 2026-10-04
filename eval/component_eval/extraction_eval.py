"""eval/component_eval/extraction_eval.py — C1-B/C1-C: extraction scoring.

Two stages, scored SEPARATELY (never conflated):

  response_to_answer   -- scripts.llm.response_parser.final_number_str()
                           against a fixed response TEXT. Fully
                           deterministic, no LLM, no network. Runs always.

  question_to_expression -- scripts.llm.verifier.compute() against a
                           natural-language QUESTION. This calls the real
                           LLM extractor (scripts.llm.verifier._default_extractor
                           -> llm_client.chat) internally -- there is no way
                           to score actual extraction accuracy without a live
                           model call. This stage is built here but NOT
                           executed by default; call run_question_to_expression
                           with live_confirm=True (or `--live-confirm` on the
                           CLI) to actually spend API calls, after reviewing
                           the cost estimate this module prints first.

Datasets scored:
    eval/datasets/extraction/v1_starter.jsonl   (14 items)
    eval/datasets/extraction/v2_extended.jsonl  (15 items)

Run (deterministic stage only, default):
    python -m eval.component_eval.extraction_eval

Run (both stages, spends live API calls -- requires explicit flag):
    python -m eval.component_eval.extraction_eval --live-confirm
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import results

ROOT = results.ROOT
DATASET_FILES = [
    ROOT / "eval" / "datasets" / "extraction" / "v1_starter.jsonl",
    ROOT / "eval" / "datasets" / "extraction" / "v2_extended.jsonl",
]


def _load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_all() -> tuple[list[dict], list[dict]]:
    dataset_sources, all_items = [], []
    for path in DATASET_FILES:
        rows = _load(path)
        dataset_sources.append({
            "path": str(path.relative_to(ROOT)), "version": path.stem,
            "item_count": len(rows),
        })
        all_items.extend(rows)
    return dataset_sources, all_items


def score_response_to_answer(items: list[dict]) -> dict:
    """Deterministic. No LLM call."""
    from scripts.llm import response_parser

    rows = [i for i in items if i["stage"] == "response_to_answer"]
    per_example, n_match, n_error = [], 0, 0
    for item in rows:
        try:
            got = response_parser.final_number_str(item["input"])
        except Exception as e:
            per_example.append({"case_id": item["case_id"], "outcome": "error", "detail": repr(e)})
            n_error += 1
            continue
        expected = item.get("expected_final_answer")
        match = got == expected
        per_example.append({
            "case_id": item["case_id"], "outcome": "match" if match else "mismatch",
            "got": got, "expected": expected,
        })
        if match:
            n_match += 1
    n = len(rows)
    return {
        "stage": "response_to_answer", "live_llm_used": False,
        "total_items": n,
        "exact_match": {"numerator": n_match, "denominator": n,
                        "rate": round(n_match / n, 4) if n else None},
        "errors": n_error,
        "per_example": per_example,
    }


def report_question_to_expression_plan(items: list[dict]) -> dict:
    """No LLM call -- reports what WOULD run and its estimated cost, for
    approval before any paid/live execution."""
    rows = [i for i in items if i["stage"] == "question_to_expression"]
    from scripts.llm import llm_client
    return {
        "stage": "question_to_expression", "status": "PENDING_APPROVAL_NOT_RUN",
        "n_items": len(rows),
        "n_calls_required": len(rows),
        "model": llm_client.DEFAULT_MODEL,
        "provider_order": ["groq-direct", "hf-nscale", "hf-deepinfra"],
        "estimated_cost": ("Groq free tier / no per-token billing configured in "
                           "this repo's .env; HF router fallback billing depends "
                           "on the account's HF Inference Providers plan. No paid "
                           "API key was confirmed in this pass -- verify before running."),
        "estimated_runtime_seconds": f"~{len(rows)} calls * ~2-4s typical latency "
                                     f"(see docs/latency_reliability_evaluation.md) "
                                     f"= roughly {len(rows)*3}s, plus any 429 retries",
        "case_ids": [r["case_id"] for r in rows],
    }


def run_question_to_expression(items: list[dict]) -> dict:
    """ACTUALLY CALLS THE LIVE LLM EXTRACTOR. Only invoked when the caller
    has explicitly confirmed (CLI --live-confirm or live_confirm=True)."""
    from scripts.llm import verifier

    rows = [i for i in items if i["stage"] == "question_to_expression"]
    per_example, n_exact, n_equiv, n_parse_ok, n_error = [], 0, 0, 0, 0
    for item in rows:
        try:
            comp = verifier.compute(item["input"])
        except Exception as e:
            per_example.append({"case_id": item["case_id"], "outcome": "error", "detail": repr(e)})
            n_error += 1
            continue
        expected_expr = item.get("expected_expression")
        equivalents = set(item.get("expected_expression_equivalents", []))
        got_expr = comp.expression if comp.verifiable else "NONE"
        exact = (got_expr == expected_expr) or (expected_expr is None and got_expr == "NONE")
        equiv = exact or (got_expr in equivalents)
        parse_ok = comp.verifiable or expected_expr is None
        if exact:
            n_exact += 1
        if equiv:
            n_equiv += 1
        if parse_ok:
            n_parse_ok += 1
        per_example.append({
            "case_id": item["case_id"], "got_expression": got_expr,
            "expected_expression": expected_expr, "exact_match": exact,
            "equivalent_match": equiv, "has_distractor_numbers":
            item.get("has_distractor_numbers", False),
        })
    n = len(rows)
    return {
        "stage": "question_to_expression", "live_llm_used": True,
        "total_items": n,
        "exact_match": {"numerator": n_exact, "denominator": n, "rate": round(n_exact / n, 4) if n else None},
        "accepted_equivalent_match": {"numerator": n_equiv, "denominator": n, "rate": round(n_equiv / n, 4) if n else None},
        "parse_success": {"numerator": n_parse_ok, "denominator": n, "rate": round(n_parse_ok / n, 4) if n else None},
        "errors": n_error,
        "per_example": per_example,
    }


def run(live_confirm: bool = False) -> dict:
    dataset_sources, all_items = _load_all()

    r2a = score_response_to_answer(all_items)
    plan = report_question_to_expression_plan(all_items)

    live_section = None
    if live_confirm:
        live_section = run_question_to_expression(all_items)

    aggregate = {
        "response_to_answer": {k: v for k, v in r2a.items() if k != "per_example"},
        "question_to_expression_plan": plan,
        "question_to_expression_executed": (
            {k: v for k, v in live_section.items() if k != "per_example"}
            if live_section else None
        ),
    }
    per_example = {"response_to_answer": r2a["per_example"]}
    if live_section:
        per_example["question_to_expression"] = live_section["per_example"]

    path = results.write_result(
        "extraction_eval",
        dataset_sources=dataset_sources,
        config={"live_llm_used": bool(live_confirm),
               "question_to_expression_stage": "executed" if live_confirm else "planned_not_executed"},
        per_example_results=[{"stage": k, "items": v} for k, v in per_example.items()],
        aggregate_metrics=aggregate,
        notes=("response_to_answer is scored deterministically every run. "
              "question_to_expression requires the live LLM extractor and was "
              f"{'executed with explicit --live-confirm' if live_confirm else 'NOT executed -- see question_to_expression_plan for cost/scope before approving a live run'}."),
    )
    summary = [
        f"# extraction_eval — {path.name}",
        "",
        f"response_to_answer: {r2a['exact_match']['numerator']}/{r2a['exact_match']['denominator']} "
        f"exact match ({r2a['exact_match']['rate']})",
        "",
        f"question_to_expression: {plan['n_items']} items "
        f"{'EXECUTED live' if live_confirm else 'PENDING -- not executed, requires approval'}.",
    ]
    results.write_summary_markdown(path, summary)
    return {"result_path": str(path), "aggregate": aggregate}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-confirm", action="store_true",
                    help="Actually call the live LLM extractor for question_to_expression "
                         "items. Without this flag, that stage is only planned/costed, never run.")
    args = ap.parse_args()
    out = run(live_confirm=args.live_confirm)
    print(json.dumps(out["aggregate"], indent=2))
    print(f"\nWrote {out['result_path']}")
