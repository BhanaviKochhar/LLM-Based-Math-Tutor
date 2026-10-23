"""eval/judge.py -- the LLM judge for the paper evaluation (decided
2026-10-23: qwen/qwen3.8-27b on Groq, a different model family from the
openai/gpt-oss-120b generator).

One call per response. The judge sees the question, the grade, the item's
ground truth and the response -- never which condition produced it -- and
returns JSON:

  committed_answer   the final answer the response commits to, or "NONE"
                     (correctness is still decided in code, by
                     eval/answer_extraction.py's matcher, never by the judge)
  key_idea           present | partial | absent | n/a  (conceptual items,
                     against expected_key_idea)
  teaches_advanced   true/false  (out-of-scope items: does it teach the
                     beyond-Class-5 method, formula or a worked solution?)
  rubric             correctness, grade_fit, clarity, restraint, 1-5 each,
                     against the written anchors below
  hallucination      {"flag": bool, "quote": str, "why": str} -- a flag
                     without a quoted false claim and a reason is rejected

The judge is trusted only after it agrees with blind human ratings
(Cohen's kappa on eval/human_ratings/).

CLI:
    python -m eval.judge --dataset eval/datasets/curriculum_benchmark_class3.jsonl \\
        --transcripts eval/results/system_runs/curriculum_benchmark_class3.jsonl \\
        --out eval/results/judge_runs/system_class3.jsonl [--ids cb-1,cb-2] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from eval.baseline_runner import _grade_of, _item_id, load_items
from eval.score_transcripts import expected_oos_behavior, ground_truth_candidates
from scripts.llm import llm_client

JUDGE_MODEL = "qwen/qwen3.8-27b"
# Its own target name: llm_client keys rotation and 429 cooldowns by target
# name, and Groq limits are per model, so a judge 429 must not cool a key
# down for the tutor model. No Hugging Face fallback: the judge model stays fixed.
JUDGE_TARGETS = [llm_client.Target("groq-judge", llm_client.GROQ_URL, "GROQ_API_KEY", JUDGE_MODEL)]
JUDGE_PARAMS = {"temperature": 0.0, "max_tokens": 700}

JUDGE_SYSTEM = """You grade one maths-tutor reply to a primary-school child (India, NCERT Class 1-5). \
Judge only the reply's text. Be strict and literal.

Rubric, 1-5 each (5 best):
- correctness: 5 every maths statement right; 3 the main answer right but a step or side claim wrong; 1 the main answer wrong.
- grade_fit: 5 words and numbers a child of that class follows; 3 some terms or steps above the class; 1 well above it.
- clarity: 5 short, ordered, easy to follow; 3 followable but long or cluttered; 1 confusing.
- restraint: 5 answers what was asked, no padding or off-topic content; 3 some padding; 1 mostly padding, or teaches content beyond Class 5 that was not needed.

hallucination: true only if the reply states something false as fact (a wrong number, rule, \
definition, method step or real-world fact). Quote the false words exactly and say why they are false. \
Rounding, simplification for a child, and a wrong final answer already counted under correctness do not count \
unless a false claim is stated.

committed_answer: the final answer the reply commits to, copied briefly; "NONE" if it gives none \
(a refusal, or only a hint or question back).

Reply with JSON only, reasoning first:
{"reasoning": "<2-4 sentences>", "committed_answer": "...", "key_idea": "present|partial|absent|n/a", \
"teaches_advanced": true|false|null, "rubric": {"correctness": n, "grade_fit": n, "clarity": n, "restraint": n}, \
"hallucination": {"flag": true|false, "quote": "...", "why": "..."}}"""


def item_context(item: dict) -> str:
    """The ground truth the judge may use, by item type."""
    if "truly_out_of_scope" in item:
        return (f"Expected behaviour: {item.get('expected_behavior')}\n"
                f"Must avoid: {'; '.join(item.get('must_avoid') or [])}\n"
                "Set teaches_advanced to true if the reply teaches a beyond-Class-5 method, formula or worked "
                "solution; key_idea is n/a.")
    if "turns" in item:
        return (f"Reference answer for the conversation: {item.get('reference_answer')}\n"
                "key_idea is n/a; teaches_advanced is null.")
    cands = ground_truth_candidates(item)
    lines = []
    if cands:
        lines.append(f"Correct answer (any of): {', '.join(cands)}")
    if item.get("expected_key_idea"):
        lines.append(f"Expected key idea: {item['expected_key_idea']} -- set key_idea by whether the reply "
                     "gets this idea across.")
    else:
        lines.append("key_idea is n/a.")
    lines.append("teaches_advanced is null.")
    return "\n".join(lines)


def build_messages(item: dict, journey: dict) -> list[dict]:
    turns = journey["turns"]
    convo = "\n".join(f"Child: {t['student']}\nTutor: {t.get('response') or ''}" for t in turns[:-1])
    last = turns[-1]
    user = (f"Class {_grade_of(item) or 'unknown'}.\n"
            + (f"Earlier in the conversation:\n{convo}\n\n" if convo else "")
            + f"Child's message: {last['student']}\n\n{item_context(item)}\n\n"
            f"Reply to grade:\n<<<\n{last.get('response') or ''}\n>>>\n/no_think")
    return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}]


_RUBRIC_KEYS = ("correctness", "grade_fit", "clarity", "restraint")


def parse_verdict(text: str) -> dict | None:
    """The last JSON object in the reply, validated; None if unusable."""
    text = re.sub(r"(?s)<think>.*?</think>", "", text or "")
    start = text.find("{")
    if start < 0:
        return None
    for end in range(len(text), start, -1):
        if text[end - 1] != "}":
            continue
        try:
            v = json.loads(text[start:end])
            break
        except json.JSONDecodeError:
            continue
    else:
        return None
    rub = v.get("rubric") or {}
    hall = v.get("hallucination") or {}
    if not all(isinstance(rub.get(k), int) and 1 <= rub[k] <= 5 for k in _RUBRIC_KEYS):
        return None
    if v.get("key_idea") not in ("present", "partial", "absent", "n/a"):
        return None
    if not isinstance(hall.get("flag"), bool):
        return None
    if hall["flag"] and not (str(hall.get("quote") or "").strip() and str(hall.get("why") or "").strip()):
        return None   # a bare yes is rejected by design
    return v


def judge_one(item: dict, journey: dict, chat_fn=None, retries: int = 1) -> dict:
    fn = chat_fn or (lambda msgs: llm_client.chat(msgs, params=JUDGE_PARAMS, targets=JUDGE_TARGETS))
    messages = build_messages(item, journey)
    last = None
    for _ in range(retries + 1):
        result = fn(messages)
        last = result
        verdict = parse_verdict(result.get("text") or "")
        if verdict is not None:
            return {"ok": True, "verdict": verdict, "prompt_tokens": result.get("prompt_tokens"),
                    "completion_tokens": result.get("completion_tokens"),
                    "rate_limited_attempts": result.get("rate_limited_attempts")}
    return {"ok": False, "verdict": None, "raw": (last or {}).get("text"), "error": (last or {}).get("error")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--transcripts", required=True, help="a baseline_runs/ or system_runs/ checkpoint")
    parser.add_argument("--out", required=True, help="JSONL checkpoint of verdicts (resumable)")
    parser.add_argument("--ids", default=None, help="comma-separated item ids to judge (default: all)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-workers", type=int, default=None)
    args = parser.parse_args()

    items = {_item_id(i): i for i in load_items(Path(args.dataset))}
    transcripts = {}
    for line in open(args.transcripts, encoding="utf-8"):
        if line.strip():
            rec = json.loads(line)
            transcripts[rec["id"]] = rec
    ids = args.ids.split(",") if args.ids else [i for i in items if i in transcripts]
    if args.limit:
        ids = ids[: args.limit]
    jobs = [{"id": i} for i in ids if transcripts.get(i, {}).get("turns")]

    def call_fn(job: dict) -> dict:
        return judge_one(items[job["id"]], transcripts[job["id"]])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    results = llm_client.run_batch(jobs, call_fn, checkpoint_path=out, max_workers=args.max_workers)
    ok = sum(1 for r in results if r.get("ok"))
    print(f"judged {ok}/{len(jobs)} -> {out}")


if __name__ == "__main__":
    main()
