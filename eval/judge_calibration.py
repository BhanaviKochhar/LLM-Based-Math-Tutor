"""eval/judge_calibration.py -- does the LLM judge (eval/judge.py) agree with
a careful human rater on the blind rating sheet (eval/blind_ratings/)?

Runs the judge on the same 150 replies the humans rated (resumable
checkpoint), then compares with one rater's sheet:
  - hallucination flag and the categorical columns: Cohen's kappa;
  - rubric scores: quadratic-weighted kappa;
  - answer correct: the judge's committed answer is checked against the
    ground truth in code (eval/answer_extraction.py), never by the judge.
A committed answer of NONE counts as N/A on both sides.
Gate: kappa at least 0.6 on the hallucination flag and weighted kappa at
least 0.5 on rubric scores before the judge runs at full scale.

Live (judge model only):
    python -m eval.judge_calibration --rater A
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval import answer_extraction, judge
from eval.baseline_runner import _item_id, load_items
from eval.component_eval.results import write_result, write_summary_markdown
from eval.rating_agreement import RUBRIC, cohen_kappa, load_sheet, norm, weighted_kappa
from eval.score_transcripts import _load_checkpoint, ground_truth_candidates
from scripts.llm import llm_client

ROOT = Path(__file__).resolve().parent.parent
HR = ROOT / "eval" / "blind_ratings"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# One saved-verdicts file per judge prompt version (calibration_v1.jsonl was
# produced by version 1, before JUDGE_PROMPT_VERSION existed).
def checkpoint_path(model: str = judge.JUDGE_MODEL) -> Path:
    suffix = "" if model == judge.JUDGE_MODEL else "_" + model.split("/")[-1]
    return ROOT / "eval" / "results" / "judge_runs" / f"calibration_v{judge.JUDGE_PROMPT_VERSION}{suffix}.jsonl"


def _sources() -> tuple[dict, dict]:
    """item id -> (item, dataset stem) for every dataset the sheet draws from."""
    items = {}
    for g in range(1, 6):
        stem = f"curriculum_benchmark_class{g}"
        for it in load_items(ROOT / f"eval/datasets/{stem}.jsonl"):
            items[_item_id(it)] = (it, stem)
    for it in load_items(ROOT / "eval/datasets/out_of_scope.jsonl"):
        items[_item_id(it)] = (it, "out_of_scope")
    for c in json.load(open(ROOT / "eval/datasets/multi_turn.json", encoding="utf-8"))["conversations"]:
        items[c["conversation_id"]] = (c, "multi_turn")
    return items, {}


def _answer_correct(verdict: dict, item: dict) -> str:
    """yes | no | n/a -- the judge's committed answer checked in code."""
    committed = str(verdict.get("committed_answer") or "").strip()
    cands = ground_truth_candidates(item) if "truly_out_of_scope" not in item and "turns" not in item else []
    if "turns" in item and item.get("reference_answer"):
        cands = [str(item["reference_answer"])]
    if not committed or committed.upper() == "NONE" or not cands:
        return "n/a"
    return "yes" if any(answer_extraction.match(committed, c, item.get("question") or "") for c in cands) else "no"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rater", default="A")
    parser.add_argument("--rows", choices=("all", "odd", "even"), default="all",
                        help="odd = development half, even = test half (split fixed in advance)")
    parser.add_argument("--model", default=judge.JUDGE_MODEL,
                        help="judge model (same instructions); its verdicts get their own file")
    parser.add_argument("--max-workers", type=int, default=8,
                        help="lower it for providers with tight per-minute limits")
    args = parser.parse_args()

    key = json.load(open(HR / "rating_key.json", encoding="utf-8"))["rows"]
    if args.rows != "all":
        key = [k for k in key if k["row"] % 2 == (1 if args.rows == "odd" else 0)]
    items, _ = _sources()
    ckpts: dict[tuple, dict] = {}

    def journey(k):
        item, stem = items[k["item_id"]]
        ck = ckpts.setdefault((k["condition"], stem),
                              _load_checkpoint(ROOT / f"eval/results/{k['condition']}_runs/{stem}.jsonl"))
        return item, ck[k["item_id"]]

    jobs = [{"id": str(k["row"]), "row": k["row"]} for k in key]
    by_row = {k["row"]: k for k in key}

    if args.model == judge.JUDGE_MODEL:
        targets = judge.JUDGE_TARGETS
    elif args.model.startswith("gemini"):
        # Google AI Studio's OpenAI-compatible endpoint; GEMINI_API_KEYS
        # (comma-separated) rotates across keys like GROQ_API_KEYS.
        targets = [llm_client.Target("gemini-judge", GEMINI_URL, "GEMINI_API_KEY", args.model)]
    else:
        targets = [llm_client.Target("groq-judge-" + args.model.split("/")[-1], llm_client.GROQ_URL,
                                     "GROQ_API_KEY", args.model)]
    params = {**judge.JUDGE_PARAMS, "frequency_penalty": None} if args.model.startswith("gemini") else judge.JUDGE_PARAMS
    chat = lambda msgs: llm_client.chat(msgs, params=params, targets=targets)

    def call_fn(job):
        item, j = journey(by_row[job["row"]])
        return judge.judge_one(item, j, chat_fn=chat)

    ckpt = checkpoint_path(args.model)
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    results = {int(r["id"]): r for r in llm_client.run_batch(jobs, call_fn, checkpoint_path=ckpt, max_workers=args.max_workers)}

    human = {x["row"]: x for x in load_sheet(args.rater)}
    pairs = []
    for row, k in by_row.items():
        r = results.get(row) or {}
        if not r.get("ok"):
            continue
        v, h = r["verdict"], human[row]
        item, _ = journey(k)
        h_correct = "n/a" if norm(h["committed"]) in ("", "none") else norm(h["correct"]).replace("unclear", "")
        pairs.append({"row": row, "stratum": k["stratum"],
                      "j_halluc": "yes" if v["hallucination"]["flag"] else "no", "h_halluc": norm(h["halluc"]),
                      "j_key": v["key_idea"], "h_key": norm(h["key_idea"]),
                      "j_teach": {True: "yes", False: "no", None: "n/a"}.get(v.get("teaches_advanced"), "n/a"),
                      "h_teach": norm(h["teaches"]),
                      "j_correct": _answer_correct(v, item), "h_correct": h_correct,
                      **{f"j_{c}": v["rubric"][c] for c in RUBRIC}, **{f"h_{c}": h[c] for c in RUBRIC},
                      "j_quote": v["hallucination"].get("quote"), "h_quote": h["quote"]})

    def kap(a, b, drop_na=True):
        xs = [(p[a], p[b]) for p in pairs if not (drop_na and ("n/a" in (p[a], p[b]) or "" in (p[a], p[b])))]
        return cohen_kappa([x for x, _ in xs], [y for _, y in xs]), len(xs)

    metrics = {"judged": len(pairs), "of": len(key)}
    for name, a, b in (("hallucination", "j_halluc", "h_halluc"), ("key_idea", "j_key", "h_key"),
                       ("teaches_beyond_class_5", "j_teach", "h_teach"), ("answer_correct", "j_correct", "h_correct")):
        metrics[name] = kap(a, b)
    for c in RUBRIC:
        metrics[c] = (weighted_kappa([p[f"j_{c}"] for p in pairs], [p[f"h_{c}"] for p in pairs]), len(pairs))
    metrics["flags"] = {"judge": sum(p["j_halluc"] == "yes" for p in pairs),
                        "human": sum(p["h_halluc"] == "yes" for p in pairs),
                        "both": sum(p["j_halluc"] == p["h_halluc"] == "yes" for p in pairs)}

    lines = [f"# Judge calibration against rater {args.rater} ({args.rows} rows)", "",
             f"judge: {args.model}, prompt version {judge.JUDGE_PROMPT_VERSION}",
             f"replies judged: {metrics['judged']}/{metrics['of']}", ""]
    for name in ("hallucination", "key_idea", "teaches_beyond_class_5", "answer_correct", *RUBRIC):
        k, n = metrics[name]
        lines.append(f"- {name}: kappa {k:.2f} (n = {n})" if k is not None else f"- {name}: n/a")
    f = metrics["flags"]
    lines += ["", f"hallucination flags: judge {f['judge']}, human {f['human']}, both {f['both']}", "",
              "## hallucination disagreements"]
    for p in pairs:
        if p["j_halluc"] != p["h_halluc"]:
            lines.append(f"- row {p['row']} ({p['stratum']}): judge={p['j_halluc']} human={p['h_halluc']}; "
                         f"judge quote: {str(p['j_quote'])[:100]!r}; human quote: {str(p['h_quote'])[:100]!r}")
    print("\n".join(lines))
    path = write_result("judge_calibration", dataset_sources=[{"path": str(HR)}],
                        config={"rater": args.rater, "rows": args.rows, "judge": args.model,
                                "judge_prompt_version": judge.JUDGE_PROMPT_VERSION}, per_example_results=pairs,
                        aggregate_metrics=metrics, notes="LLM judge vs blind human ratings.")
    write_summary_markdown(path, lines)
    print(f"\nRaw: {path}")


if __name__ == "__main__":
    main()
