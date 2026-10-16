"""eval/baseline_runner.py — the O3 baseline condition.

Per the evaluation plan's resolved definition: baseline is a plain-tutor
system prompt plus that same conversation's own growing message history --
the standard way any chat model holds a multi-turn conversation. No
retrieval chunks, no controller mode directive, no verifier-computed answer
injection, no scope gate, no cross-episode thread-notes. Baseline talks to
itself across turns (its own prior replies feed its own next turn) and is
never fed the system's responses -- two parallel conversations, not a
hybrid.

This module therefore calls scripts.llm.llm_client's provider-rotation/
retry substrate DIRECTLY with a hand-built message list. It deliberately
does NOT import scripts.llm.pipeline, scripts.llm.controller,
scripts.llm.retrieval, or scripts.llm.scope -- importing any of those here
would reintroduce exactly the machinery baseline is defined by the ABSENCE
of. Nothing under frontend/ or scripts/llm/ imports this module; it must
stay unreachable from the production app.

Dataset-agnostic by design: eval/datasets/*'s bucket files (in-scope
single-turn, out-of-scope single-turn, multi-turn journeys) use a few
different schemas (see docs/evaluation_dataset_schema.md and the existing
curriculum_benchmark_class*/out_of_scope/multi_turn files), so
`_student_turns()` and `_grade_of()` below are the one adapter layer that
reads whichever shape a given item uses; `run_journey()` itself only ever
sees a plain list of turn strings plus an optional grade.

CLI:
    python -m eval.baseline_runner --dataset eval/datasets/out_of_scope.jsonl
    python -m eval.baseline_runner --dataset eval/datasets/multi_turn.json --limit 5 --dry-run
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.llm import llm_client, response_parser

ROOT = Path(__file__).resolve().parent.parent

BASELINE_PARAMS = {
    "temperature": 0.3,
    "max_tokens": 1024,
    "top_p": 0.9,
    "frequency_penalty": 0.3,
}


def system_prompt(grade: int | None) -> str:
    """The one, deliberately plain, tutoring instruction baseline ever sees
    -- no retrieval context, no mode directive, no injected answer, no
    scope-gate rule. Mirrors only what any ordinary chat-tutor deployment
    would reasonably set as its system prompt."""
    who = f"a Class {grade} student" if grade else "a primary-school (Class 1-5) student"
    return (
        f"You are a friendly maths tutor helping {who} in India, following "
        "the NCERT curriculum. Read the student's message and reply the way "
        "a helpful tutor would in an ordinary conversation: answer their "
        "question, show your reasoning in simple steps, and give a clear "
        "final answer when the question has one."
    )


def build_messages(grade: int | None, history: list[dict], student_message: str) -> list[dict]:
    """[system] + prior turns of THIS journey (baseline's own history only)
    + the new student turn. `history` is baseline's own accumulated
    {"role": "user"/"assistant", ...} list -- never the system's replies."""
    return [{"role": "system", "content": system_prompt(grade)}, *history,
            {"role": "user", "content": student_message}]


def run_turn(
    grade: int | None,
    history: list[dict],
    student_message: str,
    *,
    params: dict | None = None,
    targets=None,
) -> dict:
    """Run one baseline turn. Returns the llm_client result dict plus the
    updated history (student turn + baseline's own reply appended) the
    caller passes into the next turn."""
    messages = build_messages(grade, history, student_message)
    result = llm_client.chat(messages, params=params or BASELINE_PARAMS, targets=targets)
    raw_text = result.get("text") or ""
    # Same cosmetic cleanup the production pipeline applies before storing/
    # displaying a reply (response_parser.py, step 10) -- stray LaTeX and
    # dead blank-line runs, nothing that touches correctness. Applied so
    # baseline's own conversational history (and later analysis reading
    # either condition's transcript) sees the same kind of text either way.
    clean_text = response_parser.collapse_excess_blank_lines(response_parser.strip_latex(raw_text))
    new_history = [*history,
                   {"role": "user", "content": student_message},
                   {"role": "assistant", "content": clean_text}]
    return {**result, "text": clean_text, "raw_text": raw_text, "history": new_history}


def run_journey(
    grade: int | None,
    student_turns: list[str],
    *,
    params: dict | None = None,
    targets=None,
) -> dict:
    """Run every turn of one journey in order, baseline-only. Stops early
    (and flags it) if a turn comes back not-ok, since a broken turn N means
    turn N+1's history is built on an empty/failed reply, not a genuine
    conversational response."""
    history: list[dict] = []
    turns_out = []
    all_ok = True
    for i, student_message in enumerate(student_turns, 1):
        result = run_turn(grade, history, student_message, params=params, targets=targets)
        history = result.pop("history")
        turns_out.append({
            "turn": i,
            "student": student_message,
            "response": result.get("text"),
            "raw_response": result.get("raw_text"),
            "ok": result.get("ok"),
            "provider": result.get("provider"),
            "model_id": result.get("model_id"),
            "latency_s": result.get("latency_s"),
            "finish_reason": result.get("finish_reason"),
            "error": result.get("error"),
        })
        if not result.get("ok"):
            all_ok = False
            break  # no point continuing a conversation whose last turn produced nothing
    return {"grade": grade, "condition": "baseline", "all_turns_ok": all_ok, "turns": turns_out}


# --------------------------------------------------------------- dataset adapter
def _student_turns(item: dict) -> list[str]:
    """Read whichever of eval/datasets/*'s few schemas this item uses."""
    if "turns" in item:  # multi_turn.json conversations
        return [t["student"] for t in item["turns"]]
    question = item.get("question", "")
    prior = item.get("student_prior_statement")
    if prior:
        return [f"{prior}\n\n{question}"]
    return [question]


def _grade_of(item: dict) -> int | None:
    return item.get("grade")  # absent on out_of_scope items today; None is a valid baseline input


def _item_id(item: dict) -> str:
    return (item.get("case_id") or item.get("conversation_id") or item.get("query_id")
            or item.get("scenario_id"))


def load_items(dataset_path: Path) -> list[dict]:
    """Load either a *.jsonl file of flat items (skipping blank lines and
    any '#'-prefixed header/description comment lines), or a *.json file
    shaped like multi_turn.json ({"conversations": [...]}) -- `.get()` on
    the dict already tolerates an unrelated top-level "_description" key."""
    if dataset_path.suffix == ".jsonl":
        items = []
        with open(dataset_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    items.append(json.loads(line))
        return items
    with open(dataset_path, encoding="utf-8") as f:
        doc = json.load(f)
    return doc.get("conversations", doc.get("items", []))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="Path to an eval/datasets/* file")
    parser.add_argument("--checkpoint", default=None,
                        help="JSONL checkpoint path (default: eval/results/baseline_runs/<dataset-stem>.jsonl)")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N items")
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument("--model", default=llm_client.DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would run (item count, ids, grades) without any LLM call")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    items = load_items(dataset_path)
    if args.limit:
        items = items[: args.limit]

    if args.dry_run:
        print(f"{len(items)} item(s) from {dataset_path}")
        for item in items[:5]:
            print(f"  {_item_id(item)}: grade={_grade_of(item)}, "
                  f"{len(_student_turns(item))} turn(s)")
        if len(items) > 5:
            print(f"  ... and {len(items) - 5} more")
        print(f"groq_key_count={llm_client.groq_key_count()}, "
              f"default_max_workers={llm_client.default_max_workers()}")
        return

    checkpoint = (Path(args.checkpoint) if args.checkpoint
                  else ROOT / "eval" / "results" / "baseline_runs" / f"{dataset_path.stem}.jsonl")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    targets = llm_client.default_targets(args.model)
    jobs = [{"id": _item_id(item), "item": item} for item in items]

    def call_fn(job: dict) -> dict:
        item = job["item"]
        return run_journey(_grade_of(item), _student_turns(item), targets=targets)

    already_done = set()
    if checkpoint.exists():
        with open(checkpoint, encoding="utf-8") as f:
            already_done = {json.loads(line)["id"] for line in f if line.strip()}
    n_pending = sum(1 for j in jobs if j["id"] not in already_done)
    print(f"{len(jobs)} job(s) total, {len(already_done & {j['id'] for j in jobs})} already "
          f"in checkpoint, {n_pending} to run -> {checkpoint} "
          f"(max_workers={args.max_workers or llm_client.default_max_workers()})")
    results = llm_client.run_batch(
        jobs, call_fn,
        checkpoint_path=checkpoint,
        max_workers=args.max_workers,
    )
    n_ok = sum(1 for r in results if r.get("all_turns_ok"))
    print(f"Done: {n_ok}/{len(results)} journeys completed every turn ok. "
          f"Checkpoint: {checkpoint}")


if __name__ == "__main__":
    main()
