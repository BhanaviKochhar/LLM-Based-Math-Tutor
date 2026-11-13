"""eval/opener_eval.py -- validate the session-opener router
(conversation_resolver.classify_opener) before it ships.

Runs the router on every FIRST message the evaluation will send that has no
quantity in it (messages with a quantity never reach the model), and on the
frozen held-out sets, and reports against the gate agreed on 2026-10-23:
  - recall on openers that should get a clarifying question: at least 20 of
    the 24 multi_turn CLARIFY openers;
  - false clarifications on real questions: at most 1%.
The held-out child-style openers (eval/datasets/held_out_openers.jsonl:
misspellings, broken grammar, Hindi-English) are reported separately -- they
were written before the router prompt, so they are the honest check.

Live: one small call per number-free message to the router model.
    python -m eval.opener_eval
"""
from __future__ import annotations

import json
from pathlib import Path

from eval.baseline_runner import _student_turns, load_items
from eval.component_eval.results import write_result, write_summary_markdown
from scripts.llm import conversation_resolver as cr
from scripts.llm import llm_client

DATASETS = Path(__file__).resolve().parent / "datasets"


def openers() -> list[dict]:
    rows = []
    for g in range(1, 6):
        for it in load_items(DATASETS / f"curriculum_benchmark_class{g}.jsonl"):
            # Exactly the first message the runners send (prior statement included).
            rows.append({"set": "curriculum", "id": it["case_id"], "grade": g,
                         "text": _student_turns(it)[0], "expected": "NEW"})
    for it in load_items(DATASETS / "out_of_scope.jsonl"):
        # Only messages the scope gate lets through ever reach the router.
        if not it["truly_out_of_scope"]:
            rows.append({"set": "out_of_scope probes", "id": it["case_id"], "grade": 5, "text": it["question"], "expected": "NEW"})
    for it in load_items(DATASETS / "held_out_ambiguous_everyday.jsonl"):
        rows.append({"set": "held-out ambiguous/everyday", "id": it["case_id"], "grade": it["grade"], "text": it["question"], "expected": "NEW"})
    for c in json.load(open(DATASETS / "multi_turn.json", encoding="utf-8"))["conversations"]:
        t = c["turns"][0]
        # "CLARIFY -- ..." and "CONFUSION or CLARIFY -- ..." both expect a clarifying question.
        exp = "CLARIFY" if "CLARIFY" in t["expected_controller_action"].split("--")[0] else "NEW"
        if t["expected_controller_action"].startswith("scope.check()"):
            continue
        rows.append({"set": "multi_turn openers", "id": c["conversation_id"], "grade": c["grade"], "text": t["student"], "expected": exp})
    for it in load_items(DATASETS / "held_out_openers.jsonl"):
        rows.append({"set": "held-out child-style openers", "id": it["case_id"], "grade": it["grade"], "text": it["question"], "expected": it["expected"]})
    return rows


def main() -> None:
    rows = [r for r in openers() if not cr._HAS_QUANTITY.search(r["text"])]

    def call_fn(job: dict) -> dict:
        return {"got": cr.classify_opener(job["text"], grade=job["grade"])}

    jobs = [{**r, "job": f"{r['set']}|{r['id']}"} for r in rows]
    results = llm_client.run_batch(jobs, call_fn, job_id_key="job", max_workers=8)
    by_job = {r.get("job"): r for r in results}
    for r in jobs:
        r["got"] = (by_job.get(r["job"]) or {}).get("got")
        r["ok"] = r["got"] == r["expected"]

    summary, lines = {}, ["# Opener router validation", "", f"model: {cr.OPENER_MODEL}", ""]
    for s in sorted({r["set"] for r in jobs}):
        sel = [r for r in jobs if r["set"] == s]
        clar = [r for r in sel if r["expected"] == "CLARIFY"]
        new = [r for r in sel if r["expected"] == "NEW"]
        summary[s] = {"clarify_caught": sum(r["ok"] for r in clar), "clarify_n": len(clar),
                      "new_wrongly_clarified": sum(not r["ok"] for r in new), "new_n": len(new)}
        lines.append(f"- {s}: vague openers caught {summary[s]['clarify_caught']}/{len(clar)}; "
                     f"real questions wrongly clarified {summary[s]['new_wrongly_clarified']}/{len(new)}")
    lines += ["", "## errors"] + [f"- {r['id']} expected={r['expected']} got={r['got']}: {r['text']}" for r in jobs if not r["ok"]]
    print("\n".join(lines))
    path = write_result("opener_eval", dataset_sources=[{"path": str(DATASETS)}],
                        config={"model": cr.OPENER_MODEL}, per_example_results=jobs,
                        aggregate_metrics=summary, notes="Live validation of conversation_resolver.classify_opener.")
    write_summary_markdown(path, lines)
    print(f"\nRaw: {path}")


if __name__ == "__main__":
    main()
