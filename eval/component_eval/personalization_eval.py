"""eval/component_eval/personalization_eval.py — C4: personalization
evaluation.

Most of eval/datasets/personalization/v1_starter.jsonl's 14 items describe
a PROSE-LEVEL difference (explanation depth, terminology register,
scaffolding amount) that genuinely cannot be scored deterministically from
code -- doing so would require live generation plus a human or LLM-judge
rubric pass, which this module does not invent a substitute metric for
(per the task's explicit instruction: "If some intended personalization
behavior cannot be evaluated deterministically from current code, document
that limitation instead of inventing a metric").

What CAN be scored deterministically, because the dataset's own
`mechanism_reference` field names a real, directly-executable code path
(scripts.llm.controller / frontend.app._record_outcome), is run for real
against that code -- not asserted from reading the dataset's claims:

  pz-003 / pz-004  -- the beginner (2) vs advanced (3) co-solve threshold
                       is a genuine, deterministic controller.step() fact.
  pz-006           -- a HINT request must route to MODE_HINT, never
                       MODE_REVEAL, regardless of level (level isn't even
                       a step() input for this branch).
  pz-014           -- GIVE_UP must always route to MODE_CO_SOLVE with
                       outcome='gave_up' and must NOT be recorded as a
                       wrong attempt, regardless of level.

Everything else is preserved in a queue (not scored, not discarded) for a
future live-generation + rubric evaluation pass, exactly like
curriculum_benchmark_eval.py's rubric_queue.

Run:
    python -m eval.component_eval.personalization_eval
"""
from __future__ import annotations

import json
from pathlib import Path

from . import results

ROOT = results.ROOT
DATASET_FILE = ROOT / "eval" / "datasets" / "personalization" / "v1_starter.jsonl"

# Which case_ids this module can check deterministically, and how.
_DETERMINISTIC_CHECKS = {"pz-003", "pz-004", "pz-006", "pz-014"}


def _load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _check_cosolve_threshold(level: str, threshold: int) -> dict:
    """Real controller execution: controller._COSOLVE_AFTER[level] == threshold
    means the THRESHOLD-th wrong attempt itself triggers MODE_CO_SOLVE
    (scripts/llm/controller.py: `state.attempts += 1; if state.attempts >=
    cosolve_threshold(): ... CO_SOLVE` -- the increment happens before the
    comparison, so the Nth wrong attempt is the one that trips it, not the
    (N+1)th). So: the first (threshold-1) wrong attempts must NOT reach
    CO_SOLVE, and the threshold-th one must."""
    from scripts.llm import controller as C

    state, action = C.start("q", 3, level, computed_answer="10", is_math=True)
    for i in range(threshold - 1):
        state, action = C.step(state, "ATTEMPT", "999999")  # always wrong
        if action.mode == C.MODE_CO_SOLVE:
            return {"outcome": "fail",
                   "detail": f"reached co_solve after only {i+1} wrong attempts; "
                   f"expected the {level} threshold ({threshold}) to require "
                   f"{threshold - (i + 1)} more"}
    state, action = C.step(state, "ATTEMPT", "999999")
    reached = action.mode == C.MODE_CO_SOLVE
    return {"outcome": "pass" if reached else "fail",
           "detail": f"reached co_solve on wrong attempt #{threshold}: {reached}"}


def _check_hint_not_reveal(level: str) -> dict:
    from scripts.llm import controller as C

    state, action = C.start("q", 3, level, computed_answer="10", is_math=True)
    state, action = C.step(state, "HINT", None)
    ok = action.mode == C.MODE_HINT
    return {"outcome": "pass" if ok else "fail",
           "detail": f"HINT intent at level={level} -> mode={action.mode}"}


def _check_give_up_handling(level: str) -> dict:
    from scripts.llm import controller as C
    from frontend import app

    calls = []
    orig_record = app.record_feedback
    app.record_feedback = lambda *a, **kw: calls.append(a)
    try:
        state, action = C.start("q", 3, level, computed_answer="10", is_math=True)
        state, action = C.step(state, "GIVE_UP", None)
        app._record_outcome(state, action)
    finally:
        app.record_feedback = orig_record

    ok = (action.mode == C.MODE_CO_SOLVE and action.outcome == "gave_up"
         and not calls)
    return {"outcome": "pass" if ok else "fail",
           "detail": f"mode={action.mode} outcome={action.outcome} "
           f"recorded_as_attempt={bool(calls)}"}


def run() -> dict:
    items = _load(DATASET_FILE)
    dataset_sources = [{"path": str(DATASET_FILE.relative_to(ROOT)),
                        "version": DATASET_FILE.stem, "item_count": len(items)}]

    per_example = []
    exclusions = []
    prose_queue = []
    n_pass = n_fail = 0

    for item in items:
        cid = item["case_id"]
        if cid not in _DETERMINISTIC_CHECKS:
            exclusions.append({"case_id": cid,
                               "reason": "prose-level personalization difference "
                               "(explanation depth/terminology/scaffolding); "
                               "cannot be scored deterministically -- requires "
                               "live generation plus human/rubric judgment"})
            prose_queue.append({"case_id": cid, "scenario": item.get("scenario"),
                                "learner_level": item.get("learner_level"),
                                "underlying_question": item.get("underlying_question"),
                                "expected_to_change": item.get("expected_to_change"),
                                "mechanism_reference": item.get("mechanism_reference")})
            per_example.append({"case_id": cid, "outcome": "excluded_requires_rubric"})
            continue

        if cid == "pz-003":
            result = _check_cosolve_threshold("beginner", 2)
        elif cid == "pz-004":
            result = _check_cosolve_threshold("advanced", 3)
        elif cid == "pz-006":
            result = _check_hint_not_reveal("advanced")
        elif cid == "pz-014":
            result = _check_give_up_handling("beginner")
        else:
            result = {"outcome": "fail", "detail": "unmapped deterministic check"}

        if result["outcome"] == "pass":
            n_pass += 1
        else:
            n_fail += 1
        per_example.append({"case_id": cid, **result})

    aggregate = {
        "total_items": len(items),
        "deterministically_checked": len(_DETERMINISTIC_CHECKS),
        "pass": n_pass,
        "fail": n_fail,
        "requires_live_generation_and_rubric_judgment": len(prose_queue),
    }

    path = results.write_result(
        "personalization_eval",
        dataset_sources=dataset_sources,
        config={"method": "direct execution of scripts.llm.controller / "
               "frontend.app against the real mechanism_reference claims; "
               "prose-dependent items preserved in a queue, not scored",
               "live_llm_used": False},
        per_example_results=per_example,
        aggregate_metrics=aggregate,
        exclusions=exclusions,
        notes=(f"Only {len(_DETERMINISTIC_CHECKS)} of {len(items)} personalization "
              "items describe a mechanism this module can verify from code "
              "alone. The remaining items are genuine prose/register "
              "differences this pass does not fabricate a metric for -- see "
              "the preserved queue artifact."),
    )
    queue_path = path.with_name(path.stem + "_rubric_queue.json")
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump({"source_result": path.name, "items": prose_queue}, f,
                  indent=2, ensure_ascii=False)

    summary = [
        f"# personalization_eval — {path.name}",
        "",
        f"Deterministically checked: {n_pass} pass, {n_fail} fail (of {len(_DETERMINISTIC_CHECKS)})",
        f"Requires live generation + rubric judgment (preserved, see {queue_path.name}): "
        f"{len(prose_queue)}",
    ]
    results.write_summary_markdown(path, summary)
    return {"result_path": str(path), "rubric_queue_path": str(queue_path),
           "aggregate": aggregate}


if __name__ == "__main__":
    out = run()
    print(json.dumps(out["aggregate"], indent=2))
    print(f"\nWrote {out['result_path']}")
    print(f"Wrote {out['rubric_queue_path']}")
