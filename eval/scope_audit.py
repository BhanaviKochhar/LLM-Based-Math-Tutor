"""eval/scope_audit.py -- run the deterministic scope gate (scripts/llm/scope.py)
offline over every evaluation dataset and count its two kinds of error:

  - false refusals: an in-scope question the gate blocks (curriculum_benchmark
    items, out_of_scope false-rejection probes, multi_turn turns the dataset
    expects the tutor to handle);
  - misses: a question the dataset says is beyond Class 1-5 that the gate
    lets through (out_of_scope decline/gloss items, multi_turn turns whose
    expected_controller_action is a scope.check() refusal or gloss).

scope.check() is pure pattern matching -- no LLM, no network -- so this runs
in seconds and is exactly repeatable. It is the "before any live call" check
for every scope.py change: run it before and after, and compare.

CLI:
    python -m eval.scope_audit                      # all datasets
    python -m eval.scope_audit --extra path.jsonl   # also a held-out set
                                                    # (same fields as out_of_scope.jsonl)
    python -m eval.scope_audit --write              # also save a results file
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.baseline_runner import load_items
from eval.component_eval.results import write_result, write_summary_markdown
from eval.score_transcripts import expected_oos_behavior
from scripts.llm import scope

DATASETS = Path(__file__).resolve().parent / "datasets"


def gate_outcome(text: str) -> str:
    """pass | gloss | refuse -- what scope.check() does with this text."""
    r = scope.check(text)
    if r.in_scope:
        return "pass"
    return "gloss" if r.allow_gloss else "refuse"


def _expected_from_action(action: str) -> str:
    """A multi_turn turn's expected gate outcome, from its controller action."""
    a = (action or "").strip()
    if not a.startswith("scope.check()"):
        return "pass"
    return "gloss" if "allow_gloss=True" in a else "refuse"


def audit_out_of_scope(path: Path) -> list[dict]:
    rows = []
    for item in load_items(path):
        expected = expected_oos_behavior(item)
        outcome = gate_outcome(item["question"])
        if expected == "answer":
            ok = outcome == "pass"
        elif expected == "gloss":
            ok = outcome == "gloss"
        else:
            ok = outcome != "pass"   # a refusal or a gloss both stop the teaching
        rows.append({"dataset": path.name, "id": item["case_id"], "expected": expected,
                     "boundary_case": bool(item.get("boundary_case")), "outcome": outcome,
                     "ok": ok, "question": item["question"]})
    return rows


def audit_curriculum() -> list[dict]:
    rows = []
    for g in range(1, 6):
        path = DATASETS / f"curriculum_benchmark_class{g}.jsonl"
        for item in load_items(path):
            outcome = gate_outcome(item["question"])
            rows.append({"dataset": path.name, "id": item["case_id"], "expected": "pass",
                         "boundary_case": False, "outcome": outcome, "ok": outcome == "pass",
                         "question": item["question"]})
    return rows


def audit_multi_turn() -> list[dict]:
    """Each student turn on its own. A turn the gate stops ends the
    conversation early in the live system, so a false refusal here matters
    as much as one on a single-turn item."""
    data = json.load(open(DATASETS / "multi_turn.json", encoding="utf-8"))
    rows = []
    for conv in data["conversations"]:
        for t in conv["turns"]:
            expected = _expected_from_action(t.get("expected_controller_action", ""))
            outcome = gate_outcome(t.get("student") or "")
            ok = outcome == expected if expected != "refuse" else outcome != "pass"
            rows.append({"dataset": "multi_turn.json", "id": f"{conv['conversation_id']}#t{t['turn']}",
                         "expected": expected, "boundary_case": False, "outcome": outcome,
                         "ok": ok, "question": t.get("student") or ""})
    return rows


def summarize(rows: list[dict]) -> dict:
    def block(sel):
        return {"n": len(sel), "ok": sum(r["ok"] for r in sel)}
    out = {}
    for ds in sorted({r["dataset"] for r in rows}):
        sel = [r for r in rows if r["dataset"] == ds]
        out[ds] = {
            "in_scope_false_refusals": block([r for r in sel if r["expected"] in ("pass", "answer")]),
            "gloss": block([r for r in sel if r["expected"] == "gloss"]),
            "decline_plain": block([r for r in sel if r["expected"] in ("decline", "refuse") and not r["boundary_case"]]),
            "decline_boundary": block([r for r in sel if r["expected"] in ("decline", "refuse") and r["boundary_case"]]),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extra", action="append", default=[],
                        help="an extra out_of_scope-shaped JSONL file (e.g. a fresh held-out set)")
    parser.add_argument("--write", action="store_true", help="save a results JSON + .md")
    parser.add_argument("--show-errors", action="store_true", help="list every wrong item")
    args = parser.parse_args()

    rows = audit_curriculum() + audit_out_of_scope(DATASETS / "out_of_scope.jsonl") + audit_multi_turn()
    for extra in args.extra:
        rows += audit_out_of_scope(Path(extra))
    summary = summarize(rows)

    lines = ["# Scope gate audit (offline, scope.check only)", ""]
    for ds, s in summary.items():
        lines.append(f"## {ds}")
        for key, label in (("in_scope_false_refusals", "should pass: passed"),
                           ("gloss", "should gloss: glossed"),
                           ("decline_plain", "should stop (plain): stopped"),
                           ("decline_boundary", "should stop (boundary/disguised): stopped")):
            if s[key]["n"]:
                lines.append(f"- {label}: {s[key]['ok']}/{s[key]['n']}")
        lines.append("")
    errors = [r for r in rows if not r["ok"]]
    if args.show_errors:
        lines.append("## wrong items")
        for r in errors:
            lines.append(f"- {r['id']} expected={r['expected']} got={r['outcome']}: {r['question'][:110]}")
    print("\n".join(lines))

    if args.write:
        path = write_result("scope_audit",
                            dataset_sources=[{"path": r, "version": Path(r).stem} for r in
                                             sorted({str(DATASETS / r["dataset"]) for r in rows})],
                            config={"extra": args.extra}, per_example_results=rows,
                            aggregate_metrics=summary,
                            notes="Offline scope.check() audit; no LLM calls.")
        write_summary_markdown(path, lines)
        print(f"\nRaw: {path}")


if __name__ == "__main__":
    main()
