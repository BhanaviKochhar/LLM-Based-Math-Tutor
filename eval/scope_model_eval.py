"""eval/scope_model_eval.py -- validate the full scope decision for messages
that start a new problem, exactly as the system makes it:

  1. the word rules (scope.check): refuse or gloss, no call;
  2. a session's first message with no quantity: the opener router's single
     call (NEW / CLARIFY / ADVANCED);
  3. otherwise the small-model check (scope.needs_beyond_primary), which
     skips bare arithmetic.

Reports, per dataset, how many messages the decision stops, how many
in-scope messages it wrongly stops (gate: at most 1%), and how many model
calls it needed. Mid-conversation new-problem turns are checked on the
child's own words; the live system checks the resolver's self-contained
rewrite, so those rows are an approximation.

Live: small-model calls only (gpt-oss-20b).
    python -m eval.scope_model_eval [--extra eval/datasets/<held-out>.jsonl ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.baseline_runner import _student_turns, load_items
from eval.component_eval.results import write_result, write_summary_markdown
from eval.score_transcripts import expected_oos_behavior
from scripts.llm import conversation_resolver as cr
from scripts.llm import llm_client, scope

DATASETS = Path(__file__).resolve().parent / "datasets"


def decide(text: str, grade: int, opener: bool) -> tuple[str, int]:
    """(outcome, model calls): outcome is refuse | gloss | clarify | pass."""
    r = scope.check(text)
    if not r.in_scope:
        return ("gloss" if r.allow_gloss else "refuse"), 0
    if opener and not cr._HAS_QUANTITY.search(text):
        label = cr.classify_opener(text, grade=grade)
        return {"ADVANCED": "refuse", "CLARIFY": "clarify"}.get(label, "pass"), 1
    if scope.is_plain_arithmetic(text):
        return "pass", 0
    return ("refuse" if scope.needs_beyond_primary(text, grade=grade) else "pass"), 1


def rows() -> list[dict]:
    out = []
    for g in range(1, 6):
        for it in load_items(DATASETS / f"curriculum_benchmark_class{g}.jsonl"):
            out.append({"set": "curriculum", "id": it["case_id"], "grade": g, "opener": True,
                        "text": _student_turns(it)[0], "expect": "in_scope"})

    def oos_rows(path: Path, name: str):
        for it in load_items(path):
            e = expected_oos_behavior(it)
            out.append({"set": name, "id": it["case_id"], "grade": 5, "opener": True, "text": it["question"],
                        "expect": {"answer": "in_scope", "gloss": "gloss", "decline": "stop"}[e],
                        "boundary": bool(it.get("boundary_case"))})
    oos_rows(DATASETS / "out_of_scope.jsonl", "out_of_scope")

    for c in json.load(open(DATASETS / "multi_turn.json", encoding="utf-8"))["conversations"]:
        for i, t in enumerate(c["turns"]):
            a = t["expected_controller_action"]
            new_problem = i == 0 or a.startswith(("NEW_QUESTION", "MATH_FOLLOWUP", "new episode", "scope.check()"))
            if not new_problem:
                continue
            expect = "in_scope"
            if a.startswith("scope.check()"):
                expect = "gloss" if "allow_gloss=True" in a else "stop"
            out.append({"set": "multi_turn new problems", "id": f"{c['conversation_id']}#t{t['turn']}",
                        "grade": c["grade"], "opener": i == 0, "text": t["student"], "expect": expect})
    for it in load_items(DATASETS / "held_out_openers.jsonl"):
        out.append({"set": "held-out child-style openers", "id": it["case_id"], "grade": it["grade"],
                    "opener": True, "text": it["question"], "expect": "in_scope"})
    for it in load_items(DATASETS / "held_out_ambiguous_everyday.jsonl"):
        out.append({"set": "held-out ambiguous/everyday", "id": it["case_id"], "grade": it["grade"],
                    "opener": True, "text": it["question"], "expect": "in_scope"})
    return out, oos_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extra", action="append", default=[], help="an out_of_scope-shaped held-out JSONL")
    args = parser.parse_args()
    data, oos_rows = rows()
    for extra in args.extra:
        oos_rows(Path(extra), Path(extra).stem)

    jobs = [{**r, "job": f"{r['set']}|{r['id']}"} for r in data]

    def call_fn(job: dict) -> dict:
        outcome, calls = decide(job["text"], job["grade"], job["opener"])
        return {"outcome": outcome, "calls": calls}

    results = {r["job"]: r for r in llm_client.run_batch(jobs, call_fn, job_id_key="job", max_workers=8)}
    for j in jobs:
        res = results.get(j["job"]) or {}
        j["outcome"], j["calls"] = res.get("outcome"), res.get("calls", 0)
        if j["expect"] == "in_scope":
            j["ok"] = j["outcome"] in ("pass", "clarify")
        elif j["expect"] == "gloss":
            j["ok"] = j["outcome"] == "gloss"
        else:
            j["ok"] = j["outcome"] in ("refuse", "gloss")

    summary, lines = {}, ["# Scope decision validation (word rules + small model)", "",
                          f"model: {scope.SCOPE_MODEL}, params: {scope.SCOPE_PARAMS}", ""]
    for s in dict.fromkeys(j["set"] for j in jobs):
        sel = [j for j in jobs if j["set"] == s]
        ins = [j for j in sel if j["expect"] == "in_scope"]
        stop = [j for j in sel if j["expect"] == "stop"]
        stop_b = [j for j in stop if j.get("boundary")]
        summary[s] = {"in_scope_wrongly_stopped": sum(not j["ok"] for j in ins), "in_scope_n": len(ins),
                      "stopped": sum(j["ok"] for j in stop), "stop_n": len(stop),
                      "stopped_boundary": sum(j["ok"] for j in stop_b), "stop_boundary_n": len(stop_b),
                      "model_calls": sum(j["calls"] for j in sel), "messages": len(sel)}
        d = summary[s]
        lines.append(f"- {s}: in-scope wrongly stopped {d['in_scope_wrongly_stopped']}/{d['in_scope_n']}; "
                     f"out-of-scope stopped {d['stopped']}/{d['stop_n']}"
                     + (f" (disguised {d['stopped_boundary']}/{d['stop_boundary_n']})" if stop_b else "")
                     + f"; model calls {d['model_calls']} for {d['messages']} messages")
    lines += ["", "## errors"] + [f"- {j['id']} expect={j['expect']} got={j['outcome']}: {j['text'][:110]}"
                                  for j in jobs if not j["ok"]]
    print("\n".join(lines))
    path = write_result("scope_model_eval", dataset_sources=[{"path": str(DATASETS)}],
                        config={"model": scope.SCOPE_MODEL, "params": scope.SCOPE_PARAMS, "extra": args.extra},
                        per_example_results=jobs, aggregate_metrics=summary,
                        notes="Word rules + opener router + small-model scope check, as the system decides.")
    write_summary_markdown(path, lines)
    print(f"\nRaw: {path}")


if __name__ == "__main__":
    main()
